"""Minimal A-XDR compound codecs.

For v1 we provide a "typed_data" codec that reads one A-XDR tag and decodes a
single value of that type. This handles the common 698 case where a response
carries `octet-string` or `long-unsigned` etc. inline. Fully-recursive
ARRAY/STRUCTURE/CHOICE handling with YAML-declared children is a future
enhancement (the framework already supports them via the `children:` field —
we just don't ship every codec yet).
"""
from __future__ import annotations

from typing import Any, Tuple

from ..errors import CodecError
from .base import Codec
from .dlms import read_axdr_length, write_axdr_length


# A-XDR tag -> (name, fixed_size_or_None, signed)
_PRIMITIVE_TAGS = {
    0x00: ("null", 0, False),
    0x03: ("bool", 1, False),
    0x05: ("double_long", 4, True),
    0x06: ("double_long_unsigned", 4, False),
    0x0F: ("integer", 1, True),
    0x10: ("long", 2, True),
    0x11: ("unsigned", 1, False),
    0x12: ("long_unsigned", 2, False),
    0x14: ("long64", 8, True),
    0x15: ("long64_unsigned", 8, False),
    0x16: ("enum", 1, False),
}


class AxdrTypedDataCodec(Codec):
    """Reads one A-XDR tag, then decodes/encodes its value.

    Encode form: `value` may be either a dict `{"tag": "long_unsigned", "value": 42}`
    or a raw hex string starting with the tag byte.
    """
    name = "axdr_typed_data"
    self_delimiting = True

    def encode(self, value, field_schema, ctx) -> bytes:
        if isinstance(value, str):
            from ..util.hexutil import to_bytes
            return to_bytes(value)
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if isinstance(value, dict):
            tag_name = value.get("tag", "null")
            v = value.get("value")
            tag, size, signed = _find_tag_by_name(tag_name)
            if tag in _PRIMITIVE_TAGS:
                if tag == 0x00:
                    return bytes([0x00])
                if tag == 0x03:
                    return bytes([0x03, 1 if v else 0])
                return bytes([tag]) + int(v).to_bytes(size, "big", signed=signed)
            if tag == 0x09 or tag == 0x0A or tag == 0x0C:
                # octet/visible/utf8 string
                if isinstance(v, str) and tag in (0x0A, 0x0C):
                    data = v.encode("ascii" if tag == 0x0A else "utf-8")
                elif isinstance(v, str):
                    from ..util.hexutil import to_bytes
                    data = to_bytes(v)
                else:
                    data = bytes(v)
                return bytes([tag]) + write_axdr_length(len(data)) + data
            raise CodecError(f"axdr_typed_data: tag {tag_name!r} not implemented for encode")
        raise CodecError(f"axdr_typed_data: bad value {value!r}")

    def decode(self, buf, field_schema, ctx) -> Tuple[Any, int]:
        if len(buf) < 1:
            raise CodecError("axdr_typed_data: empty")
        tag = buf[0]
        if tag in _PRIMITIVE_TAGS:
            name, size, signed = _PRIMITIVE_TAGS[tag]
            if size == 0:
                return {"tag": name, "value": None}, 1
            if len(buf) < 1 + size:
                raise CodecError(f"axdr {name}: need {1 + size} bytes")
            v = int.from_bytes(bytes(buf[1:1 + size]), "big", signed=signed)
            if name == "bool":
                v = bool(v)
            return {"tag": name, "value": v}, 1 + size
        if tag in (0x09, 0x0A, 0x0C):
            length, ln = read_axdr_length(buf[1:])
            start = 1 + ln
            end = start + length
            if len(buf) < end:
                raise CodecError(f"axdr string: need {end} bytes")
            raw = bytes(buf[start:end])
            if tag == 0x0A:
                value: Any = raw.decode("ascii", errors="replace")
            elif tag == 0x0C:
                value = raw.decode("utf-8", errors="replace")
            else:
                value = raw.hex().upper()
            return {"tag": _STRING_TAGS[tag], "value": value}, end
        # Arrays/structures: just consume their A-XDR-counted children as raw bytes
        # so the parser doesn't crash. A future YAML-driven children decoder can
        # take over.
        raise CodecError(f"axdr_typed_data: tag 0x{tag:02X} not implemented")


_STRING_TAGS = {0x09: "octet_string", 0x0A: "visible_string", 0x0C: "utf8_string"}


def _find_tag_by_name(name: str) -> tuple[int, int, bool]:
    for tag, (n, size, signed) in _PRIMITIVE_TAGS.items():
        if n == name:
            return tag, size, signed
    if name == "octet_string":
        return 0x09, 0, False
    if name == "visible_string":
        return 0x0A, 0, False
    if name == "utf8_string":
        return 0x0C, 0, False
    raise CodecError(f"unknown axdr tag name: {name!r}")
