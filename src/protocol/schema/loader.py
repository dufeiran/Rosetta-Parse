"""YAML -> typed Schema dataclasses."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

import yaml

from ..errors import SchemaError
from .model import (
    BitFieldSpec,
    FieldSchema,
    FrameSchema,
    IdentifierRule,
    IdentifierSpec,
    ProtocolBase,
    ServiceSchema,
    VariantSelectorRule,
)


# Keys recognized at the field level; anything else lands in extras
_FIELD_KEYS = {
    "name", "type", "length", "default", "description", "role",
    "auto", "algorithm", "range", "transform", "bit_fields",
    "children", "values", "source",
}


def load_yaml_file(path: Union[str, Path]) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise SchemaError(f"YAML parse error in {p}: {e}") from e
    if not isinstance(data, dict):
        raise SchemaError(f"{p}: top-level must be a mapping")
    return data


def parse_protocol_base(doc: Dict[str, Any], *, source: str = "<inline>") -> ProtocolBase:
    if "protocol" not in doc:
        raise SchemaError(f"{source}: missing 'protocol' block")
    proto = doc["protocol"]
    if not isinstance(proto, dict) or "name" not in proto:
        raise SchemaError(f"{source}: 'protocol.name' is required")

    ident_block = doc.get("identifier", {}) or {}
    identifier = IdentifierSpec(
        start_byte=_to_int(ident_block.get("start_byte")) if "start_byte" in ident_block else None,
        rules=[IdentifierRule(check=r["check"], params={k: v for k, v in r.items() if k != "check"})
               for r in (ident_block.get("rules") or [])],
    )

    frames_block = doc.get("frames", {}) or {}
    if "base" not in frames_block:
        raise SchemaError(f"{source}: protocol base YAML must define frames.base")

    base_frame = parse_frame(name="base", raw=frames_block["base"], source=source)

    # Find payload field (role:payload) — that's where APDU goes
    payload_field = next((f.name for f in base_frame.fields if f.role == "payload"), None)
    if payload_field is None:
        raise SchemaError(f"{source}: base frame must have a field with role: payload")

    return ProtocolBase(
        name=proto["name"],
        display_name=proto.get("display_name"),
        description=proto.get("description"),
        identifier=identifier,
        base_frame=base_frame,
        payload_field=payload_field,
    )


def parse_service(doc: Dict[str, Any], *, source: str = "<inline>") -> ServiceSchema:
    if "service" not in doc:
        raise SchemaError(f"{source}: missing 'service' block")
    s = doc["service"]
    if not isinstance(s, dict):
        raise SchemaError(f"{source}: 'service' must be a mapping")
    protocol = s.get("protocol")
    if not protocol:
        raise SchemaError(f"{source}: 'service.protocol' is required")
    code = s.get("service_code")
    if code is None:
        raise SchemaError(f"{source}: 'service.service_code' is required")
    code_int = _to_int(code)
    if code_int is None:
        raise SchemaError(f"{source}: 'service.service_code' must be int/hex")

    frames_block = doc.get("frames", {}) or {}
    frames: Dict[str, FrameSchema] = {}
    for frame_type in ("set_request", "set_response", "get_request", "get_response"):
        if frame_type in frames_block:
            fs_raw = frames_block[frame_type]
            if fs_raw is None:
                continue
            frames[frame_type] = parse_frame(name=frame_type, raw=fs_raw, source=source)

    selector_raw = (doc.get("variant_selector") or {}).get("rules", [])
    selector: List[VariantSelectorRule] = []
    for r in selector_raw:
        if "when" not in r or "variant" not in r:
            raise SchemaError(f"{source}: variant_selector rules need 'when' and 'variant'")
        selector.append(VariantSelectorRule(when=r["when"], variant=r["variant"]))

    return ServiceSchema(
        protocol=protocol,
        service_code=code_int,
        display_name=s.get("display_name"),
        description=s.get("description"),
        frames=frames,
        variant_selector=selector,
    )


def parse_frame(*, name: str, raw: Dict[str, Any], source: str) -> FrameSchema:
    if not isinstance(raw, dict):
        raise SchemaError(f"{source}: frame '{name}' must be a mapping")
    enabled = bool(raw.get("enabled", True))
    fields_raw = raw.get("fields") or []
    if enabled and not isinstance(fields_raw, list):
        raise SchemaError(f"{source}: frame '{name}': 'fields' must be a list")
    fs = [parse_field(f, source=source) for f in fields_raw]
    return FrameSchema(name=name, description=raw.get("description"), fields=fs, enabled=enabled)


def parse_field(raw: Dict[str, Any], *, source: str) -> FieldSchema:
    if not isinstance(raw, dict):
        raise SchemaError(f"{source}: field must be a mapping (got {type(raw).__name__})")
    if "name" not in raw:
        raise SchemaError(f"{source}: field missing 'name'")
    if "type" not in raw:
        raise SchemaError(f"{source}: field {raw['name']!r} missing 'type'")
    length = raw.get("length", 0)
    if isinstance(length, str) and length != "variable":
        # allow hex strings as length? no — must be int or "variable"
        try:
            length = int(length)
        except ValueError:
            raise SchemaError(f"{source}: bad length {length!r}")

    transform = raw.get("transform") or {}
    range_block = raw.get("range") or {}

    bits = []
    for bf in raw.get("bit_fields") or []:
        bits.append(BitFieldSpec(
            name=bf["name"],
            bits=str(bf["bits"]),
            description=bf.get("description"),
            values=bf.get("values"),
        ))

    children = [parse_field(c, source=source) for c in (raw.get("children") or [])]

    extras = {k: v for k, v in raw.items() if k not in _FIELD_KEYS}

    return FieldSchema(
        name=raw["name"],
        type=raw["type"],
        length=length,
        default=raw.get("default"),
        description=raw.get("description"),
        role=raw.get("role"),
        auto=bool(raw.get("auto", False)),
        algorithm=raw.get("algorithm"),
        range_start=range_block.get("start"),
        range_end=range_block.get("end"),
        transform_mask=_to_int(transform.get("mask")) if "mask" in transform else None,
        transform_reserved_bits=_to_int(transform.get("reserved_bits")) or 0,
        bit_fields=bits,
        children=children,
        values=raw.get("values"),
        source_field=raw.get("source"),
        extras=extras,
    )


def _to_int(v: Any) -> Any:
    """Coerce a YAML scalar to int. Accept int, '0x..' string, decimal string."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.lower().startswith("0x"):
            return int(s, 16)
        try:
            return int(s)
        except ValueError:
            try:
                return int(s, 16)
            except ValueError:
                return None
    return None
