"""DL/T 698 specific compound codecs.

OAD/OMD/OI are fixed-size descriptors used positionally in 698 service frames.
We also implement A-XDR helpers (length encoding) and a minimal `axdr_typed_data`
dispatcher for the common cases needed by GET-Response-Normal payloads.

Note: full A-XDR support (ARRAY/STRUCTURE/CHOICE with nested children defined
in YAML) is delegated to `dlms_compound.py` (kept simple for v1).
"""
from __future__ import annotations

from typing import Any, Tuple

from ..errors import CodecError
from ..util.hexutil import to_bytes
from .base import Codec


# --------------------------------------------------------------- A-XDR length
def read_axdr_length(buf: memoryview) -> tuple[int, int]:
    if len(buf) == 0:
        raise CodecError("A-XDR length: empty buffer")
    b0 = buf[0]
    if b0 < 0x80:
        return b0, 1
    n = b0 & 0x7F
    if n == 0 or n > 4:
        raise CodecError(f"A-XDR length encoding too large: 0x{b0:02X}")
    if len(buf) < 1 + n:
        raise CodecError(f"A-XDR length: need {1 + n} bytes")
    return int.from_bytes(bytes(buf[1:1 + n]), "big"), 1 + n


def write_axdr_length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    for k in range(1, 5):
        if n < (1 << (8 * k)):
            return bytes([0x80 | k]) + n.to_bytes(k, "big")
    raise CodecError(f"A-XDR length too large: {n}")


# --------------------------------------------------------------- OI / OAD / OMD
class OICodec(Codec):
    """OI: 2 bytes big-endian object identifier."""
    name = "axdr_oi"

    def encode(self, value, field_schema, ctx) -> bytes:
        if isinstance(value, int):
            return value.to_bytes(2, "big")
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
        elif isinstance(value, str):
            data = to_bytes(value)
        else:
            raise CodecError(f"OI: bad value {value!r}")
        if len(data) != 2:
            raise CodecError(f"OI must be exactly 2 bytes, got {len(data)}")
        return data

    def decode(self, buf, field_schema, ctx) -> Tuple[int, int]:
        if len(buf) < 2:
            raise CodecError("OI: need 2 bytes")
        return int.from_bytes(bytes(buf[:2]), "big"), 2


class OADCodec(Codec):
    """OAD: 4-byte struct (OI[2] BE, attr_idx[1], attr_qualifier[1])."""
    name = "axdr_oad"

    def encode(self, value, field_schema, ctx) -> bytes:
        if isinstance(value, str):
            data = to_bytes(value)
            if len(data) != 4:
                raise CodecError(f"OAD must be 4 bytes, got {len(data)}")
            return data
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
            if len(data) != 4:
                raise CodecError(f"OAD must be 4 bytes, got {len(data)}")
            return data
        if isinstance(value, dict):
            oi = value.get("oi", 0)
            attr_idx = value.get("attr_idx", 0)
            attr_q = value.get("attr_qualifier", 0)
            if isinstance(oi, str):
                oi = int(oi, 16) if oi.lower().startswith("0x") or len(oi) <= 4 else int(oi)
            return int(oi).to_bytes(2, "big") + bytes([int(attr_idx) & 0xFF, int(attr_q) & 0xFF])
        raise CodecError(f"OAD: bad value {value!r}")

    def decode(self, buf, field_schema, ctx) -> Tuple[dict, int]:
        if len(buf) < 4:
            raise CodecError("OAD: need 4 bytes")
        oi = int.from_bytes(bytes(buf[:2]), "big")
        return {"oi": oi, "attr_idx": buf[2], "attr_qualifier": buf[3]}, 4


class OMDCodec(Codec):
    """OMD: 4-byte struct (OI[2] BE, method_idx[1], method_qualifier[1])."""
    name = "axdr_omd"

    def encode(self, value, field_schema, ctx) -> bytes:
        if isinstance(value, str):
            data = to_bytes(value)
        elif isinstance(value, (bytes, bytearray)):
            data = bytes(value)
        elif isinstance(value, dict):
            oi = value.get("oi", 0)
            return (int(oi).to_bytes(2, "big") +
                    bytes([int(value.get("method_idx", 0)) & 0xFF,
                           int(value.get("method_qualifier", 0)) & 0xFF]))
        else:
            raise CodecError(f"OMD: bad value {value!r}")
        if len(data) != 4:
            raise CodecError(f"OMD must be 4 bytes, got {len(data)}")
        return data

    def decode(self, buf, field_schema, ctx) -> Tuple[dict, int]:
        if len(buf) < 4:
            raise CodecError("OMD: need 4 bytes")
        oi = int.from_bytes(bytes(buf[:2]), "big")
        return {"oi": oi, "method_idx": buf[2], "method_qualifier": buf[3]}, 4


# --------------------------------------------------------------- date_time_s
class DateTimeSCodec(Codec):
    """A-XDR date_time_s: 7 bytes — YYYY(BE) MM DD hh mm ss."""
    name = "axdr_date_time_s"

    def encode(self, value, field_schema, ctx) -> bytes:
        if isinstance(value, str):
            data = to_bytes(value)
            if len(data) != 7:
                raise CodecError(f"date_time_s must be 7 bytes, got {len(data)}")
            return data
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
            if len(data) != 7:
                raise CodecError(f"date_time_s must be 7 bytes")
            return data
        if isinstance(value, dict):
            return (int(value.get("year", 0)).to_bytes(2, "big") +
                    bytes([int(value.get("month", 0)),
                           int(value.get("day", 0)),
                           int(value.get("hour", 0)),
                           int(value.get("minute", 0)),
                           int(value.get("second", 0))]))
        raise CodecError(f"date_time_s: bad value {value!r}")

    def decode(self, buf, field_schema, ctx) -> Tuple[dict, int]:
        if len(buf) < 7:
            raise CodecError("date_time_s: need 7 bytes")
        b = bytes(buf[:7])
        return {
            "year": int.from_bytes(b[0:2], "big"),
            "month": b[2], "day": b[3],
            "hour": b[4], "minute": b[5], "second": b[6],
        }, 7
