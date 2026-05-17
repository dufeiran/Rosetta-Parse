"""Bit-field helpers.

A bit-field spec is `"high-low"` (e.g. `"7-4"`) or a single bit `"3"`.
Bit numbering: MSB is 7 for a single byte. For multi-byte integers, the
caller decides which byte-ordering interpretation is meant; we operate
on Python ints and require the caller to provide an int already.
"""
from __future__ import annotations

from typing import Tuple


def parse_bits_spec(spec: str) -> Tuple[int, int]:
    """Parse '7-4' or '5' into (high_bit, low_bit). Returns (5, 5) for '5'."""
    s = str(spec).strip()
    if "-" in s:
        a, b = s.split("-", 1)
        hi = int(a.strip())
        lo = int(b.strip())
    else:
        hi = lo = int(s)
    if hi < lo:
        hi, lo = lo, hi
    if lo < 0 or hi > 63:
        raise ValueError(f"bit spec out of range: {spec!r}")
    return hi, lo


def mask_from_bits(hi: int, lo: int) -> int:
    """Inclusive mask covering bits [lo..hi]."""
    width = hi - lo + 1
    return ((1 << width) - 1) << lo


def extract_bits(value: int, spec: str) -> int:
    hi, lo = parse_bits_spec(spec)
    return (value >> lo) & ((1 << (hi - lo + 1)) - 1)


def insert_bits(value: int, spec: str, sub_value: int) -> int:
    """Return a new integer with the [hi..lo] field set to sub_value (masked)."""
    hi, lo = parse_bits_spec(spec)
    width = hi - lo + 1
    field_mask = ((1 << width) - 1) << lo
    sub = (sub_value & ((1 << width) - 1)) << lo
    return (value & ~field_mask) | sub
