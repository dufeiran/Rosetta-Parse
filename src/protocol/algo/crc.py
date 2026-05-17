"""CRC16/X.25 used as 698 HCS/FCS.

Algorithm: polynomial 0x1021, init 0xFFFF, reflect-input, reflect-output,
xorout 0xFFFF. Standard FCS-16 (HDLC).
"""
from __future__ import annotations

# Build table once.
_POLY_REFLECTED = 0x8408   # reflected 0x1021
_TABLE = [0] * 256
for _i in range(256):
    _crc = _i
    for _ in range(8):
        _crc = (_crc >> 1) ^ _POLY_REFLECTED if (_crc & 1) else (_crc >> 1)
    _TABLE[_i] = _crc & 0xFFFF


def crc16_x25(data: bytes) -> int:
    """Return the 16-bit CRC value (not yet packed)."""
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _TABLE[(crc ^ b) & 0xFF]
    return crc ^ 0xFFFF


def crc16_x25_bytes(data: bytes) -> bytes:
    """Return the CRC packed as little-endian 2 bytes (wire order in 698)."""
    return crc16_x25(data).to_bytes(2, "little")
