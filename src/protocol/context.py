"""Parse / Build contexts.

Carry the cursor (current byte offset), the field-resolution scope (siblings
already decoded, used by codecs that need a length signal), and the registry
references (codecs + algorithms).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .codec.registry import CodecRegistry
    from .algo.registry import AlgoRegistry


@dataclass
class ParseContext:
    codecs: "CodecRegistry"
    algos: "AlgoRegistry"
    frame_bytes: bytes
    offset: int = 0
    siblings: Dict[str, Any] = field(default_factory=dict)         # decoded sibling values by name
    sibling_lengths: Dict[str, int] = field(default_factory=dict)  # raw byte length per sibling
    errors: List[str] = field(default_factory=list)


@dataclass
class BuildContext:
    codecs: "CodecRegistry"
    algos: "AlgoRegistry"
    siblings: Dict[str, Any] = field(default_factory=dict)
