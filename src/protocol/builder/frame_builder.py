"""Two-pass frame builder.

Pass 1: encode each field using defaults + overrides, emitting placeholder
        bytes (zeros) for auto-fields.
Pass 2: walk auto-fields in declaration order (topological sort would be
        needed only if one auto-field's range covers another; we treat the
        schema as already in the correct order — declare length before
        checksum, checksum-of-header before checksum-of-whole).
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..algo.registry import AlgoRegistry
from ..codec.registry import CodecRegistry
from ..context import BuildContext
from ..errors import BuildError
from ..schema.model import FieldSchema, FrameSchema, ProtocolBase, ServiceSchema
from ..util.bitops import insert_bits
from ..util.dotpath import expand_dot_dict
from ..util.hexutil import to_bytes


def build_frame(
    *,
    base: ProtocolBase,
    service: Optional[ServiceSchema],
    frame_type: Optional[str],
    fields: Optional[Mapping[str, Any]],
    codecs: CodecRegistry,
    algos: AlgoRegistry,
) -> bytes:
    overrides = expand_dot_dict(fields or {})

    # Step 1 — build inner frame if a service/frame_type is given
    inner_bytes = b""
    if service is not None and frame_type is not None:
        if frame_type not in service.frames:
            raise BuildError(f"service 0x{service.service_code:02X} has no '{frame_type}' frame")
        inner_frame = service.frames[frame_type]
        if not inner_frame.enabled:
            raise BuildError(f"frame '{frame_type}' is disabled for service "
                             f"0x{service.service_code:02X}")
        inner_overrides_raw = overrides.get("data") or overrides.get("apdu") or {}
        inner_bytes = _encode_frame(
            frame=inner_frame,
            overrides=inner_overrides_raw,
            codecs=codecs,
            algos=algos,
            payload_field=None,
            payload_bytes=None,
            outer_protocol=base.name,
            outer_afn_byte=service.service_code if base.name == "gw3762" else None,
        )

    # Step 2 — build outer frame with inner_bytes as the payload
    # Strip apdu/data overrides from the outer set (they were consumed).
    outer_overrides = {k: v for k, v in overrides.items() if k not in ("data", "apdu")}

    # If user is building outer-only (no service), they may provide raw payload via 'data' or 'apdu'
    if service is None:
        payload_raw = overrides.get("data", overrides.get("apdu"))
        if payload_raw is not None:
            if isinstance(payload_raw, (bytes, bytearray)):
                inner_bytes = bytes(payload_raw)
            elif isinstance(payload_raw, str):
                inner_bytes = to_bytes(payload_raw)
            elif isinstance(payload_raw, dict):
                raise BuildError("outer-only build requires raw bytes/hex for payload, not dict")
            else:
                raise BuildError(f"cannot use {payload_raw!r} as raw payload")

    # 376.2: also inject the AFN value from the service code
    if service is not None and base.name == "gw3762":
        outer_overrides.setdefault("afn", service.service_code)

    return _encode_frame(
        frame=base.base_frame,
        overrides=outer_overrides,
        codecs=codecs,
        algos=algos,
        payload_field=base.payload_field,
        payload_bytes=inner_bytes,
    )


# ---------------------------------------------------------------------------
def _encode_frame(
    *,
    frame: FrameSchema,
    overrides: Mapping[str, Any],
    codecs: CodecRegistry,
    algos: AlgoRegistry,
    payload_field: Optional[str],
    payload_bytes: Optional[bytes],
    outer_protocol: Optional[str] = None,
    outer_afn_byte: Optional[int] = None,
) -> bytes:
    """Encode one frame's fields into bytes, computing auto-fields after the first pass."""
    ctx = BuildContext(codecs=codecs, algos=algos)

    # Pre-compute placeholder bytes for each field in declaration order.
    # We track (FieldSchema, raw_bytes) pairs so we can later mutate auto-field bytes.
    pieces: List[Tuple[FieldSchema, bytes]] = []
    for fs in frame.fields:
        if payload_field and fs.name == payload_field:
            pieces.append((fs, payload_bytes or b""))
            continue

        if fs.auto:
            # placeholder of correct width
            size = fs.length if isinstance(fs.length, int) else 1
            pieces.append((fs, bytes(size)))
            continue

        value = _resolve_value(fs, overrides)

        # Apply bit_field overrides if any
        if fs.bit_fields:
            value = _assemble_bit_fields(fs, value, overrides)

        try:
            raw = codecs.get(fs.type).encode(value, _field_schema_dict(fs), ctx)
        except Exception as e:
            raise BuildError(f"encoding field {fs.name!r}: {e}") from e
        # For fixed-length fields, ensure the codec produced the right length
        if isinstance(fs.length, int) and fs.length > 0 and len(raw) != fs.length:
            raise BuildError(f"field {fs.name!r}: codec produced {len(raw)} bytes, "
                             f"schema says {fs.length}")
        pieces.append((fs, raw))

    # Now fill auto-fields.
    # 376.2 special case: if the encoded afn byte should reflect the service code, ensure it.
    if outer_protocol == "gw3762" and outer_afn_byte is not None:
        for i, (fs, raw) in enumerate(pieces):
            if fs.name == "afn":
                pieces[i] = (fs, bytes([outer_afn_byte & 0xFF]))
                break

    # Resolve auto-fields in declaration order; copy_field references siblings.
    for i, (fs, _placeholder) in enumerate(pieces):
        if not fs.auto:
            continue
        if fs.algorithm == "copy_field":
            src = fs.source_field
            if not src:
                raise BuildError(f"{fs.name}: copy_field needs 'source'")
            src_idx = next((j for j, (g, _) in enumerate(pieces) if g.name == src), None)
            if src_idx is None or src_idx > i:
                raise BuildError(f"{fs.name}: copy_field source {src!r} must come earlier")
            pieces[i] = (fs, pieces[src_idx][1])
            continue

        if not fs.range_start or not fs.range_end:
            raise BuildError(f"{fs.name}: auto field needs range.start and range.end")

        # Slice the placeholder buffer over the declared range and compute the algorithm.
        names = [p[0].name for p in pieces]
        try:
            i_start = names.index(fs.range_start)
        except ValueError:
            raise BuildError(f"{fs.name}: range.start {fs.range_start!r} not in frame")
        try:
            i_end = names.index(fs.range_end)
        except ValueError:
            raise BuildError(f"{fs.name}: range.end {fs.range_end!r} not in frame")

        # Build the range buffer (inclusive end). For length covering "start..end" this includes
        # the entire frame. For CRC covering "length..apdu" this includes length+control+address+
        # hcs+apdu (range_end = apdu means the last field included is apdu, not the CRC field).
        range_bytes = b"".join(p[1] for p in pieces[i_start:i_end + 1])
        params: Dict[str, Any] = {}
        if fs.algorithm == "length_le":
            params["size"] = fs.length if isinstance(fs.length, int) else 2
            params["mask"] = fs.transform_mask
            params["reserved_bits"] = fs.transform_reserved_bits
        elif fs.algorithm == "length_bits14_le":
            params["reserved_bits"] = fs.transform_reserved_bits
        try:
            new_bytes = algos.get(fs.algorithm)(range_bytes, **params)
        except Exception as e:
            raise BuildError(f"{fs.name}: algorithm {fs.algorithm} failed: {e}") from e
        expected_size = fs.length if isinstance(fs.length, int) else len(new_bytes)
        if len(new_bytes) != expected_size:
            raise BuildError(f"{fs.name}: algorithm produced {len(new_bytes)} bytes, "
                             f"expected {expected_size}")
        pieces[i] = (fs, new_bytes)

    return b"".join(p[1] for p in pieces)


def _resolve_value(fs: FieldSchema, overrides: Mapping[str, Any]) -> Any:
    """Pick the value for `fs`: override > default."""
    if fs.name in overrides:
        v = overrides[fs.name]
        # If user passes a dict but the schema has bit_fields, treat the dict as bit-field overrides
        # and pull the rest from default.
        if isinstance(v, Mapping) and fs.bit_fields:
            return None   # bit-field path handled by caller; signal "use default base"
        if isinstance(v, Mapping):
            return v
        return v
    return fs.default


def _assemble_bit_fields(fs: FieldSchema, base_value: Any, overrides: Mapping[str, Any]) -> Any:
    """Combine top-level field default + bit-field overrides into a final int (or bytes).

    Bit-field overrides arrive in three possible shapes:
    1. Whole-field override (no bit-field detail) — already returned by _resolve_value.
    2. Field-as-dict containing per-bit-field names.
    3. Sub-keys at the top level via dot-paths (already expanded into nested dict by caller).
    """
    # Compute starting integer value from default or whole-override
    if base_value is None:
        # Dict override path was used; fetch the dict
        v = overrides.get(fs.name, {})
        # base integer = default
        seed = _value_as_int(fs.default, fs)
        if isinstance(v, Mapping):
            for bf in fs.bit_fields:
                if bf.name in v:
                    seed = insert_bits(seed, bf.bits, int(v[bf.name]))
        result_int = seed
    else:
        result_int = _value_as_int(base_value, fs)

    if isinstance(fs.length, int) and fs.length > 0:
        # Return as bytes? Or as int? Primitives expect an int for uint8/16 and bytes for bytes-field.
        # We'll return int if the codec is integer-based, else bytes.
        if fs.type.startswith("uint") or fs.type.startswith("int"):
            return result_int
        return result_int.to_bytes(fs.length, "big")
    return result_int


def _value_as_int(v: Any, fs: FieldSchema) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.lower().startswith("0x"):
            return int(s, 16)
        try:
            return int(s, 16)
        except ValueError:
            return int(s)
    if isinstance(v, (bytes, bytearray)):
        return int.from_bytes(bytes(v), "big")
    raise BuildError(f"cannot use {v!r} as integer for bit-field assembly")


def _field_schema_dict(fs: FieldSchema) -> dict:
    return {
        "name": fs.name,
        "type": fs.type,
        "length": fs.length,
        "default": fs.default,
        "bcd_digits": fs.extras.get("bcd_digits"),
        **fs.extras,
    }
