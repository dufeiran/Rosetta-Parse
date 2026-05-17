"""Length-encoding algorithms.

Each algorithm takes the BYTES SPANNING THE COVERED RANGE and produces the
encoded length field as bytes of a declared size.
"""
from __future__ import annotations


def length_le(range_bytes: bytes, *, size: int, mask: int | None = None,
              reserved_bits: int = 0) -> bytes:
    """Plain little-endian length. Used for 376.2 length1/length2 (with 0x3FFF mask)."""
    n = len(range_bytes)
    if mask is not None:
        n = n & mask
    n |= reserved_bits
    return n.to_bytes(size, "little")


def length_bits14_le(range_bytes: bytes, *, reserved_bits: int = 0) -> bytes:
    """16-bit LE length with low 14 bits = length, high 2 bits = reserved.

    Used by DL/T 698.45 length field.
    """
    n = (len(range_bytes) & 0x3FFF) | (reserved_bits & 0xC000)
    return n.to_bytes(2, "little")


def length_field_decoded(value: int, *, mask: int | None = None) -> int:
    """Reverse direction: extract the actual length value from the encoded field."""
    if mask is not None:
        return value & mask
    return value
