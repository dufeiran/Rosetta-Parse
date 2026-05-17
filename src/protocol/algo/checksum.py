"""Simple checksum algorithms."""
from __future__ import annotations


def sum_mod_256(data: bytes) -> int:
    return sum(data) & 0xFF


def sum_mod_256_bytes(data: bytes) -> bytes:
    return bytes([sum_mod_256(data)])
