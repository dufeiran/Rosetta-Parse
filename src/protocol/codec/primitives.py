"""Primitive codecs: uint*/int*/bytes/marker/bcd/ascii.

Bit-field decoration is applied by the parser/builder after primitive
encode/decode, not inside these codecs — so the same `uint8` codec is reused
whether or not the field declares bit_fields.
"""
from __future__ import annotations

from typing import Any, Tuple

from ..errors import CodecError
from ..util.hexutil import to_bytes
from .base import Codec


# -------------------------------------------------------------------- unsigned ints
class UIntLE(Codec):
    def __init__(self, name: str, size: int) -> None:
        self.name = name
        self.size = size

    def encode(self, value, field_schema, ctx) -> bytes:
        v = _coerce_int(value, self.size)
        return v.to_bytes(self.size, "little", signed=False)

    def decode(self, buf, field_schema, ctx) -> Tuple[int, int]:
        if len(buf) < self.size:
            raise CodecError(f"{self.name}: need {self.size} bytes, got {len(buf)}")
        return int.from_bytes(bytes(buf[:self.size]), "little", signed=False), self.size


class UIntBE(Codec):
    def __init__(self, name: str, size: int) -> None:
        self.name = name
        self.size = size

    def encode(self, value, field_schema, ctx) -> bytes:
        v = _coerce_int(value, self.size)
        return v.to_bytes(self.size, "big", signed=False)

    def decode(self, buf, field_schema, ctx) -> Tuple[int, int]:
        if len(buf) < self.size:
            raise CodecError(f"{self.name}: need {self.size} bytes, got {len(buf)}")
        return int.from_bytes(bytes(buf[:self.size]), "big", signed=False), self.size


# ----------------------------------------------------------------------- bytes
class BytesCodec(Codec):
    """Raw fixed-length bytes; the schema's `length` decides how many."""
    name = "bytes"

    def encode(self, value, field_schema, ctx) -> bytes:
        n = field_schema.get("length")
        data = _coerce_bytes(value)
        if isinstance(n, int):
            if len(data) > n:
                raise CodecError(f"bytes: value len {len(data)} exceeds field length {n}")
            if len(data) < n:
                data = data + bytes(n - len(data))   # right-pad with zeros
        return data

    def decode(self, buf, field_schema, ctx) -> Tuple[bytes, int]:
        n = field_schema.get("length")
        if not isinstance(n, int):
            raise CodecError(f"bytes: variable-length not allowed without an external length")
        if len(buf) < n:
            raise CodecError(f"bytes: need {n} bytes, got {len(buf)}")
        return bytes(buf[:n]), n


# ----------------------------------------------------------------------- marker
class MarkerCodec(Codec):
    """Fixed-value byte(s)."""
    name = "marker"

    def encode(self, value, field_schema, ctx) -> bytes:
        # Marker always emits its default; user overrides ignored to preserve framing.
        default = field_schema.get("default")
        data = _coerce_bytes(default)
        n = field_schema.get("length")
        if isinstance(n, int) and len(data) != n:
            raise CodecError(f"marker: default length {len(data)} != field length {n}")
        return data

    def decode(self, buf, field_schema, ctx) -> Tuple[bytes, int]:
        n = field_schema.get("length", 1)
        if len(buf) < n:
            raise CodecError(f"marker: need {n} bytes, got {len(buf)}")
        expected = _coerce_bytes(field_schema.get("default"))
        got = bytes(buf[:n])
        if expected and got != expected:
            ctx.errors.append(f"marker mismatch at offset {ctx.offset}: "
                              f"expected {expected.hex().upper()}, got {got.hex().upper()}")
        return got, n


# ----------------------------------------------------------------------- BCD
class BCDCodec(Codec):
    """Packed BCD.

    `bcd_le=True` reverses byte order (376.2 uses little-endian BCD frequently).
    The decoded value is an int.
    """
    def __init__(self, name: str, little_endian: bool) -> None:
        self.name = name
        self.little_endian = little_endian

    def encode(self, value, field_schema, ctx) -> bytes:
        n = field_schema.get("length")
        if not isinstance(n, int):
            raise CodecError(f"{self.name}: length is required")
        if isinstance(value, str):
            digits = value.strip()
            if len(digits) % 2:
                digits = "0" + digits
            if len(digits) // 2 > n:
                raise CodecError(f"{self.name}: too many digits for {n} bytes")
            digits = digits.zfill(n * 2)
            data = bytes.fromhex(digits)
        elif isinstance(value, int):
            digits = str(value).zfill(n * 2)
            if len(digits) > n * 2:
                raise CodecError(f"{self.name}: int {value} overflows {n} bytes")
            data = bytes.fromhex(digits)
        elif isinstance(value, (bytes, bytearray)):
            data = bytes(value)
            if len(data) != n:
                raise CodecError(f"{self.name}: raw bytes length {len(data)} != {n}")
        else:
            raise CodecError(f"{self.name}: unsupported value type {type(value).__name__}")
        return data[::-1] if self.little_endian else data

    def decode(self, buf, field_schema, ctx) -> Tuple[int, int]:
        n = field_schema.get("length")
        if not isinstance(n, int):
            raise CodecError(f"{self.name}: length is required")
        if len(buf) < n:
            raise CodecError(f"{self.name}: need {n} bytes")
        raw = bytes(buf[:n])
        ordered = raw[::-1] if self.little_endian else raw
        digits = ordered.hex()
        try:
            return int(digits), n
        except ValueError as e:
            raise CodecError(f"{self.name}: non-BCD bytes {raw.hex()}") from e


# ----------------------------------------------------------------------- ASCII
class AsciiCodec(Codec):
    name = "ascii"

    def encode(self, value, field_schema, ctx) -> bytes:
        n = field_schema.get("length")
        if isinstance(value, bytes):
            data = value
        else:
            data = str(value).encode("ascii")
        if isinstance(n, int):
            if len(data) > n:
                raise CodecError(f"ascii: value too long for {n} bytes")
            data = data + b" " * (n - len(data))
        return data

    def decode(self, buf, field_schema, ctx) -> Tuple[str, int]:
        n = field_schema.get("length")
        if not isinstance(n, int):
            raise CodecError(f"ascii: length required")
        return bytes(buf[:n]).rstrip(b"\x00 ").decode("ascii", errors="replace"), n


# ----------------------------------------------------------------------- helpers
def _coerce_int(value, size: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        if value < 0 or value >= (1 << (8 * size)):
            raise CodecError(f"int {value} does not fit in {size} byte(s)")
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.lower().startswith("0x"):
            return int(s, 16)
        # plain hex string (no prefix), e.g. "0010"
        try:
            return int(s, 16) if all(c in "0123456789abcdefABCDEF" for c in s) else int(s)
        except ValueError as e:
            raise CodecError(f"cannot parse int from {value!r}") from e
    if isinstance(value, (bytes, bytearray, memoryview)):
        return int.from_bytes(bytes(value), "big")
    raise CodecError(f"cannot coerce {value!r} to int")


def _coerce_bytes(value) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        return to_bytes(value)
    if isinstance(value, int):
        # Smallest big-endian representation (not generally what users want for a primitive,
        # but bytes-fields are usually fed hex strings).
        n = max(1, (value.bit_length() + 7) // 8)
        return value.to_bytes(n, "big")
    raise CodecError(f"cannot coerce {value!r} to bytes")
