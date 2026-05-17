"""Frame-walking parser.

Walks a FrameSchema field-by-field, delegating to codecs, computing payload
length from the declared length-range, and verifying auto-fields (checksum,
length) on the fly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..algo.registry import AlgoRegistry
from ..codec.registry import CodecRegistry
from ..context import ParseContext
from ..errors import ParseError
from ..result import FieldNode, ParseResult
from ..schema.model import FieldSchema, FrameSchema, ProtocolBase, ServiceSchema
from ..util.bitops import extract_bits
from ..util.hexutil import to_bytes


def parse_frame(
    *,
    base: ProtocolBase,
    data: bytes,
    codecs: CodecRegistry,
    algos: AlgoRegistry,
    service_lookup,                          # callable: (protocol_name, code) -> Optional[ServiceSchema]
    strict: bool = True,
) -> ParseResult:
    """Top-level: parse an outer frame, then descend into APDU if a service yaml matches."""
    ctx = ParseContext(codecs=codecs, algos=algos, frame_bytes=data, offset=0)
    fields, payload_value, payload_node = _walk_frame(
        frame=base.base_frame,
        payload_field=base.payload_field,
        ctx=ctx,
        outer_data=data,
        outer_length_for_payload=None,
    )
    # outer checksum / length verification happens inside _walk_frame via ctx.errors

    result = ParseResult(
        protocol=base.name,
        frame_type="base",
        function_code=None,
        valid=(len(ctx.errors) == 0),
        errors=list(ctx.errors),
        fields=fields,
        raw=data,
    )

    if strict and not result.valid:
        raise ParseError("; ".join(result.errors))

    if payload_value is None or len(payload_value) == 0:
        return result

    # Figure out the service code in a protocol-specific way.
    code = _peek_service_code(base.name, fields, payload_value)
    if code is None:
        return result

    svc = service_lookup(base.name, code)
    if svc is None:
        return result

    # Choose variant
    variant = _select_variant(base.name, svc, fields, payload_value)
    if variant is None:
        return result
    frame = svc.frames.get(variant)
    if frame is None or not frame.enabled:
        return result

    inner_ctx = ParseContext(codecs=codecs, algos=algos, frame_bytes=payload_value, offset=0)
    inner_fields, _, _ = _walk_frame(
        frame=frame,
        payload_field=None,
        ctx=inner_ctx,
        outer_data=payload_value,
        outer_length_for_payload=None,
    )
    # APDU starts at this byte in the outer frame
    payload_node = fields.get(base.payload_field)
    apdu_outer_offset = payload_node.offset if payload_node is not None else 0
    inner = ParseResult(
        protocol=base.name,
        frame_type=variant,
        function_code=code,
        valid=(len(inner_ctx.errors) == 0),
        errors=list(inner_ctx.errors),
        fields=inner_fields,
        raw=payload_value,
        outer_offset=apdu_outer_offset,
    )
    result.apdu = inner
    if strict and not inner.valid:
        raise ParseError("; ".join(inner.errors))
    return result


# ---------------------------------------------------------------------------
def _walk_frame(
    *,
    frame: FrameSchema,
    payload_field: Optional[str],
    ctx: ParseContext,
    outer_data: bytes,
    outer_length_for_payload: Optional[int],
) -> Tuple[Dict[str, FieldNode], Optional[bytes], Optional[FieldNode]]:
    """Decode one frame's fields in declaration order.

    Returns (fields_dict, payload_bytes_if_any, payload_node_if_any).
    """
    fields: Dict[str, FieldNode] = {}
    payload_value: Optional[bytes] = None
    payload_node: Optional[FieldNode] = None

    # First, build a map name -> FieldSchema and figure out fixed-vs-variable lengths.
    by_name: Dict[str, FieldSchema] = {f.name: f for f in frame.fields}
    # Pre-compute length-field info: which field declares range that ends with the auto length field.
    # The length field's `range` declares the byte range it counts. The payload length will be
    # derived as: length_value - bytes_in_range_outside_payload.
    length_field = next((f for f in frame.fields if f.auto and f.algorithm in
                         ("length_le", "length_bits14_le") and f.role == "length"), None)

    for fs in frame.fields:
        offset_before = ctx.offset
        if payload_field is not None and fs.name == payload_field:
            payload_value, payload_node = _decode_payload_field(
                fs, frame=frame, length_field=length_field, ctx=ctx, fields_so_far=fields,
                outer_data=outer_data,
            )
            fields[fs.name] = payload_node
            ctx.siblings[fs.name] = payload_value
            ctx.sibling_lengths[fs.name] = len(payload_value) if payload_value else 0
            continue

        node = _decode_field(fs, ctx, frame=frame)
        fields[fs.name] = node
        ctx.siblings[fs.name] = node.value
        ctx.sibling_lengths[fs.name] = node.length

    # After all fields are decoded, verify auto-fields (length, CRC, copy_field).
    for fs in frame.fields:
        if not fs.auto:
            continue
        if fs.algorithm not in ("crc16_x25", "sum_mod_256", "length_le",
                                "length_bits14_le", "copy_field"):
            continue
        node = fields.get(fs.name)
        if node is None:
            continue
        _verify_auto_field(fs, node, frame, fields, outer_data, ctx)

    return fields, payload_value, payload_node


def _decode_field(fs: FieldSchema, ctx: ParseContext,
                  *, frame: Optional[FrameSchema] = None) -> FieldNode:
    codec = ctx.codecs.get(fs.type)
    buf = memoryview(ctx.frame_bytes)[ctx.offset:]
    fs_dict = _field_schema_dict(fs)

    # Variable-length non-payload field handling:
    # If the codec is NOT self-delimiting (i.e. doesn't know its own length from data),
    # we derive the available byte count from the buffer:
    #   available = remaining_buffer - sum_of_trailing_fixed_field_lengths
    # This lets users declare a trailing "data" field that auto-consumes the rest, OR
    # a mid-frame variable field as long as everything after it has a known length.
    if fs.length == "variable" and frame is not None \
            and not getattr(codec, "self_delimiting", False):
        trailing = _count_trailing_fixed_bytes_after(frame, fs.name)
        avail = len(ctx.frame_bytes) - ctx.offset - trailing
        if avail < 0:
            raise ParseError(
                f"variable field {fs.name!r}: only {len(ctx.frame_bytes) - ctx.offset} "
                f"bytes left, but {trailing} bytes needed by trailing fixed fields"
            )
        fs_dict = dict(fs_dict)
        fs_dict["length"] = avail
        buf = memoryview(ctx.frame_bytes)[ctx.offset:ctx.offset + avail]

    value, consumed = codec.decode(buf, fs_dict, ctx)
    raw = bytes(ctx.frame_bytes[ctx.offset:ctx.offset + consumed])

    # transform: mask + shift
    if isinstance(value, int) and fs.transform_mask is not None:
        value = value & fs.transform_mask

    bf_dict: Optional[Dict[str, Any]] = None
    if fs.bit_fields:
        if not isinstance(value, int):
            # bit_fields against bytes — convert by big-endian
            if isinstance(value, (bytes, bytearray)):
                int_val = int.from_bytes(value, "big")
            else:
                int_val = 0
        else:
            int_val = value
        bf_dict = {bf.name: extract_bits(int_val, bf.bits) for bf in fs.bit_fields}

    children = None
    if fs.children:
        # Currently we don't recursively decode user-declared children inside a primitive.
        # Compound A-XDR codecs handle their own children.
        children = None

    node = FieldNode(
        name=fs.name,
        value=value,
        raw_bytes=raw,
        offset=ctx.offset,
        length=consumed,
        bit_fields=bf_dict,
        children=children,
        description=fs.description,
    )
    ctx.offset += consumed
    return node


def _decode_payload_field(
    fs: FieldSchema,
    *,
    frame: FrameSchema,
    length_field: Optional[FieldSchema],
    ctx: ParseContext,
    fields_so_far: Dict[str, FieldNode],
    outer_data: bytes,
) -> Tuple[bytes, FieldNode]:
    """Compute payload length from declared length range, then consume that many bytes."""
    if not length_field or not length_field.range_start or not length_field.range_end:
        # No length field — payload runs to end of buffer minus trailing fixed fields
        trailing = _count_trailing_fixed_bytes_after(frame, fs.name)
        end = len(outer_data) - trailing
        if end < ctx.offset:
            raise ParseError("payload: not enough bytes")
        raw = bytes(outer_data[ctx.offset:end])
    else:
        # Find the encoded length value
        length_node = fields_so_far.get(length_field.name)
        if length_node is None:
            raise ParseError(f"length field {length_field.name!r} not parsed before payload")
        length_value = length_node.value
        if isinstance(length_value, int):
            mask = length_field.transform_mask
            length_value = length_value & mask if mask is not None else length_value
        elif isinstance(length_value, (bytes, bytearray)):
            length_value = int.from_bytes(length_value, "little") & 0x3FFF
        else:
            raise ParseError(f"length field {length_field.name!r} value not numeric")

        # The length covers range [range_start..range_end] INCLUSIVE on both ends.
        # Determine how many of those bytes are NOT the payload itself.
        idx_by_name = {f.name: i for i, f in enumerate(frame.fields)}
        i_payload = idx_by_name[fs.name]
        i_start = idx_by_name.get(length_field.range_start, 0)
        i_end_inc = idx_by_name.get(length_field.range_end, len(frame.fields) - 1)

        # Sum the fixed-length fields in [i_start, i_end_inc] excluding the payload itself.
        non_payload_in_range = 0
        for j in range(i_start, i_end_inc + 1):
            if j == i_payload:
                continue
            fld = frame.fields[j]
            if isinstance(fld.length, int) and fld.length > 0:
                non_payload_in_range += fld.length
            elif fld.name in fields_so_far:
                # variable but already parsed
                non_payload_in_range += fields_so_far[fld.name].length
            else:
                # variable and not yet parsed — for our 698/376.2 layouts this shouldn't happen
                raise ParseError(f"cannot infer length of pending variable field {fld.name!r}")
        payload_len = length_value - non_payload_in_range
        if payload_len < 0:
            raise ParseError(f"computed payload length is negative: {payload_len}")
        if ctx.offset + payload_len > len(outer_data):
            raise ParseError(f"payload of {payload_len} bytes exceeds buffer")
        raw = bytes(outer_data[ctx.offset:ctx.offset + payload_len])

    node = FieldNode(
        name=fs.name,
        value=raw,
        raw_bytes=raw,
        offset=ctx.offset,
        length=len(raw),
        description=fs.description,
    )
    ctx.offset += len(raw)
    return raw, node


def _count_trailing_fixed_bytes_after(frame: FrameSchema, field_name: str) -> int:
    """Sum the integer-length fields that come after `field_name`."""
    total = 0
    seen = False
    for f in frame.fields:
        if f.name == field_name:
            seen = True
            continue
        if seen:
            if isinstance(f.length, int) and f.length > 0:
                total += f.length
            else:
                # we can't account for an unknown variable trailing — bail by leaving as 0
                return total
    return total


def _verify_auto_field(
    fs: FieldSchema,
    node: FieldNode,
    frame: FrameSchema,
    fields_so_far: Dict[str, FieldNode],
    outer_data: bytes,
    ctx: ParseContext,
) -> None:
    """Check that an auto-field's encoded value matches a recomputation."""
    if fs.algorithm == "copy_field" and fs.source_field:
        src = fields_so_far.get(fs.source_field)
        if src is None:
            ctx.errors.append(f"{fs.name}: copy_field source {fs.source_field!r} not found")
            return
        if node.raw_bytes != src.raw_bytes:
            ctx.errors.append(
                f"{fs.name}: copy_field mismatch (expected {src.raw_bytes.hex().upper()}, "
                f"got {node.raw_bytes.hex().upper()})"
            )
        return

    if not fs.range_start or not fs.range_end:
        return

    idx_by_name = {f.name: i for i, f in enumerate(frame.fields)}
    i_start = idx_by_name.get(fs.range_start)
    i_end_inc = idx_by_name.get(fs.range_end)
    if i_start is None or i_end_inc is None:
        return
    # Build the range bytes from already-parsed siblings (the field we're about to verify is
    # typically OUTSIDE its own range — checksum range_end points to the field just before it).
    chunks: list[bytes] = []
    for j in range(i_start, i_end_inc + 1):
        f = frame.fields[j]
        n = fields_so_far.get(f.name)
        if n is None:
            # not parsed yet — but for an auto-verify, all preceding fields must be parsed.
            # If we hit this, the algorithm covers a future field — caller error.
            return
        chunks.append(n.raw_bytes)
    range_bytes = b"".join(chunks)

    algo = ctx.algos.get(fs.algorithm)
    params: Dict[str, Any] = {}
    if fs.algorithm == "length_le":
        params["size"] = (fs.length if isinstance(fs.length, int) else 2)
        params["mask"] = fs.transform_mask
        params["reserved_bits"] = fs.transform_reserved_bits
    elif fs.algorithm == "length_bits14_le":
        params["reserved_bits"] = fs.transform_reserved_bits
    expected = algo(range_bytes, **params)

    if expected != node.raw_bytes:
        ctx.errors.append(
            f"{fs.name} mismatch: expected {expected.hex().upper()}, got {node.raw_bytes.hex().upper()}"
        )


def _peek_service_code(protocol: str, base_fields: Dict[str, FieldNode],
                       payload_bytes: bytes) -> Optional[int]:
    """For 698, the service code is the first byte of APDU. For 376.2, it's the 'afn' base field."""
    if protocol == "gw3762":
        afn = base_fields.get("afn")
        if afn is None or not isinstance(afn.value, int):
            return None
        return afn.value
    # default (698 et al.)
    if not payload_bytes:
        return None
    return payload_bytes[0]


def _select_variant(protocol: str, svc: ServiceSchema, base_fields: Dict[str, FieldNode],
                    payload_bytes: bytes) -> Optional[str]:
    # Service-defined selector wins
    if svc.variant_selector:
        # Build a dict of accessible base bit-field values for matching
        flat: Dict[str, Any] = {}
        for fn, node in base_fields.items():
            if node.bit_fields:
                for k, v in node.bit_fields.items():
                    flat[k] = v
            flat[fn] = node.value
        for rule in svc.variant_selector:
            if all(flat.get(k) == v for k, v in rule.when.items()):
                return rule.variant
    # 698 default: pick by service code
    if protocol == "dlt698":
        if not payload_bytes:
            return None
        first = payload_bytes[0]
        # service-choice byte determines request vs response
        if first in (0x05, 0x07, 0x08, 0x09, 0x0A, 0x0B):
            # We map request choices to whichever frame is defined in YAML
            # If the YAML defines 'get_request' or 'set_request' or 'action_request', use it.
            if first in (0x05, 0x06) and "get_request" in svc.frames:
                return "get_request"
            if first in (0x07,) and "set_request" in svc.frames:
                return "set_request"
            # fall back: take the first available request-flavored frame
            for cand in ("get_request", "set_request"):
                if cand in svc.frames:
                    return cand
        else:
            for cand in ("get_response", "set_response"):
                if cand in svc.frames:
                    return cand
    # 376.2 default: pick by (dir,prm) from control bit-fields
    if protocol == "gw3762":
        ctrl = base_fields.get("control")
        if ctrl and ctrl.bit_fields:
            dirv = ctrl.bit_fields.get("dir")
            prmv = ctrl.bit_fields.get("prm")
            # request: PRM=1 (master initiating); response: PRM=0
            if prmv == 1 and "get_request" in svc.frames:
                return "get_request"
            if prmv == 0 and "get_response" in svc.frames:
                return "get_response"
    # Last resort: take first defined frame
    for cand in ("get_request", "get_response", "set_request", "set_response"):
        if cand in svc.frames and svc.frames[cand].enabled:
            return cand
    return None


def _field_schema_dict(fs: FieldSchema) -> dict:
    """Codecs read schema-level params via a plain dict (decoupled from FieldSchema)."""
    return {
        "name": fs.name,
        "type": fs.type,
        "length": fs.length,
        "default": fs.default,
        "bcd_digits": fs.extras.get("bcd_digits"),
        **fs.extras,
    }
