"""Codec registry — maps a string type name to a Codec instance."""
from __future__ import annotations

from typing import Dict

from .base import Codec
from .primitives import (
    AsciiCodec,
    BCDCodec,
    BytesCodec,
    MarkerCodec,
    UIntBE,
    UIntLE,
)
from .dlms import (
    DateTimeSCodec,
    OADCodec,
    OICodec,
    OMDCodec,
)
from .dlms_compound import AxdrTypedDataCodec


class CodecRegistry:
    def __init__(self) -> None:
        self._codecs: Dict[str, Codec] = {}

    def register(self, codec: Codec) -> None:
        if not codec.name:
            raise ValueError("codec must have a name")
        self._codecs[codec.name] = codec

    def get(self, name: str) -> Codec:
        try:
            return self._codecs[name]
        except KeyError as e:
            raise KeyError(f"unknown codec: {name!r}") from e

    def has(self, name: str) -> bool:
        return name in self._codecs


def default_registry() -> CodecRegistry:
    r = CodecRegistry()
    # primitives
    r.register(UIntLE("uint8", 1))
    r.register(UIntLE("uint16_le", 2))
    r.register(UIntLE("uint24_le", 3))
    r.register(UIntLE("uint32_le", 4))
    r.register(UIntBE("uint8_be", 1))
    r.register(UIntBE("uint16_be", 2))
    r.register(UIntBE("uint24_be", 3))
    r.register(UIntBE("uint32_be", 4))
    r.register(BytesCodec())
    r.register(MarkerCodec())
    r.register(BCDCodec("bcd", little_endian=False))
    r.register(BCDCodec("bcd_le", little_endian=True))
    r.register(AsciiCodec())
    # DLMS / 698-specific
    r.register(OICodec())
    r.register(OADCodec())
    r.register(OMDCodec())
    r.register(DateTimeSCodec())
    r.register(AxdrTypedDataCodec())
    return r
