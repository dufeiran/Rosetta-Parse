"""Hex string / bytes helpers."""
from __future__ import annotations

from typing import Union

HexLike = Union[bytes, bytearray, memoryview, str]


def to_bytes(data: HexLike) -> bytes:
    """Accept bytes / bytearray / memoryview / hex-string (whitespace-tolerant, case-insensitive)."""
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    if isinstance(data, str):
        cleaned = "".join(data.split())
        if len(cleaned) % 2:
            raise ValueError(f"hex string has odd length: {cleaned!r}")
        return bytes.fromhex(cleaned)
    raise TypeError(f"unsupported type for to_bytes: {type(data).__name__}")


def to_hex(data: bytes, *, sep: str = " ", upper: bool = True) -> str:
    h = data.hex(sep) if sep else data.hex()
    return h.upper() if upper else h


def hex_dump(data: bytes, *, width: int = 16) -> str:
    """Multi-line hex dump (offset | hex | ascii)."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk).ljust(width * 3 - 1)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:04X}  {hex_part}  {ascii_part}")
    return "\n".join(lines)
