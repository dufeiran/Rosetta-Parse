"""Codec abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParseContext, BuildContext


class Codec(ABC):
    """A codec encodes a Python value to bytes and decodes bytes back.

    All codecs receive the *field schema dict* via `field_schema` so that they
    can read declarative metadata (length, endianness, bcd_digits, etc.) at
    runtime. This avoids one codec subclass per parameter combination.
    """

    name: str = ""

    @abstractmethod
    def encode(self, value: Any, field_schema: dict, ctx: "BuildContext") -> bytes: ...

    @abstractmethod
    def decode(self, buf: memoryview, field_schema: dict, ctx: "ParseContext") -> Tuple[Any, int]:
        """Return (decoded_value, bytes_consumed)."""

    # Some compound codecs self-determine their length on parse; if so they may
    # set this to True (the parser will not require a fixed-length slice).
    self_delimiting: bool = False
