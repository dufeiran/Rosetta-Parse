"""Registry mapping algorithm names to (output_size_in_bytes, compute_callable).

Each callable signature: `(range_bytes: bytes, **params) -> bytes`.
"""
from __future__ import annotations

from typing import Callable, Dict, Tuple

from . import checksum, crc, length


# A registered algorithm is a tuple: (default_output_size_or_None, callable).
# If size is None, the schema field itself dictates the output length.
ComputeFn = Callable[..., bytes]


class AlgoRegistry:
    def __init__(self) -> None:
        self._algos: Dict[str, ComputeFn] = {}

    def register(self, name: str, fn: ComputeFn) -> None:
        self._algos[name] = fn

    def get(self, name: str) -> ComputeFn:
        try:
            return self._algos[name]
        except KeyError as e:
            raise KeyError(f"unknown algorithm: {name!r}") from e

    def has(self, name: str) -> bool:
        return name in self._algos


def default_registry() -> AlgoRegistry:
    r = AlgoRegistry()

    def _sum_mod_256(range_bytes: bytes, **_kw) -> bytes:
        return checksum.sum_mod_256_bytes(range_bytes)

    def _crc16_x25(range_bytes: bytes, **_kw) -> bytes:
        return crc.crc16_x25_bytes(range_bytes)

    def _length_le(range_bytes: bytes, *, size: int = 2, mask: int | None = None,
                   reserved_bits: int = 0, **_kw) -> bytes:
        return length.length_le(range_bytes, size=size, mask=mask, reserved_bits=reserved_bits)

    def _length_bits14_le(range_bytes: bytes, *, reserved_bits: int = 0, **_kw) -> bytes:
        return length.length_bits14_le(range_bytes, reserved_bits=reserved_bits)

    # copy_field is handled by the builder directly (it needs sibling access); register a no-op so
    # schema validation passes.
    def _copy_field(range_bytes: bytes, **_kw) -> bytes:
        return range_bytes

    r.register("sum_mod_256", _sum_mod_256)
    r.register("crc16_x25", _crc16_x25)
    r.register("length_le", _length_le)
    r.register("length_bits14_le", _length_bits14_le)
    r.register("copy_field", _copy_field)
    return r
