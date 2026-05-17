"""Protocol auto-identification.

We try each registered protocol's identifier rules against the input bytes.
The protocol whose rules ALL pass wins. If multiple win, we use a configured
priority order (`["dlt698", "gw3762"]` by default).
"""
from __future__ import annotations

from typing import List, Optional

from ..errors import IdentifyError
from ..schema.registry import SchemaRegistry


class Identifier:
    def __init__(self, registry: SchemaRegistry, *, priority: Optional[List[str]] = None) -> None:
        self.registry = registry
        self.priority = priority or ["dlt698", "gw3762"]

    def identify(self, data: bytes) -> Optional[str]:
        if not data:
            return None
        candidates: list[str] = []
        for proto in self.registry.protocols():
            if _matches(proto, data):
                candidates.append(proto.name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # tie break by priority
        for p in self.priority:
            if p in candidates:
                return p
        return candidates[0]


def _matches(proto, data: bytes) -> bool:
    spec = proto.identifier
    if spec.start_byte is not None:
        if not data or data[0] != spec.start_byte:
            return False
    for rule in spec.rules:
        if not _eval_rule(rule, data):
            return False
    return True


def _eval_rule(rule, data: bytes) -> bool:
    p = rule.params
    check = rule.check
    if check == "ends_with_byte":
        return bool(data) and data[-1] == int(p.get("value"))
    if check == "byte_at_offset":
        off = int(p["offset"])
        val = int(p["value"])
        return 0 <= off < len(data) and data[off] == val
    if check == "length_field_layout":
        # 376.2 layout: bytes 1..2 == bytes 3..4 (duplicated 16-bit length)
        expect = p.get("expect")
        if expect == "dl_l_dl_l_pattern":
            return len(data) >= 5 and data[1:3] == data[3:5]
        if expect == "binary_le_14bit":
            # bytes 1..2 LE, low 14 bits encode total length
            if len(data) < 3:
                return False
            n = int.from_bytes(data[1:3], "little") & 0x3FFF
            return n > 0
        return False
    if check == "total_length_matches_buffer":
        off = int(p.get("length_field_offset", 1))
        size = int(p.get("length_field_size", 2))
        mask = int(p.get("mask", 0xFFFF))
        if len(data) < off + size:
            return False
        n = int.from_bytes(data[off:off + size], "little") & mask
        # In 698, length covers start..end (inclusive). Total frame == n.
        return n == len(data)
    # Unknown rule → fail (be strict)
    return False
