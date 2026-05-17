"""ParseResult and FieldNode dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FieldNode:
    name: str
    value: Any                       # decoded value (int/bytes/str/dict/list/...)
    raw_bytes: bytes                 # exact byte slice
    offset: int                      # offset within the frame
    length: int                      # = len(raw_bytes)
    bit_fields: Optional[Dict[str, Any]] = None
    children: Optional[List["FieldNode"]] = None
    description: Optional[str] = None

    def to_dict(self, *, include_raw: bool = True) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "value": _jsonify(self.value),
            "offset": self.offset,
            "length": self.length,
        }
        if include_raw:
            d["raw"] = self.raw_bytes.hex().upper()
        if self.bit_fields:
            d["bits"] = dict(self.bit_fields)
        if self.children:
            d["children"] = [c.to_dict(include_raw=include_raw) for c in self.children]
        if self.description:
            d["desc"] = self.description
        return d


@dataclass
class ParseResult:
    protocol: str
    frame_type: str                    # "base" | "get_request" | "get_response" | "set_request" | "set_response"
    function_code: Optional[int]       # service-choice (698) or AFN (376.2); None if base-only
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    fields: Dict[str, FieldNode] = field(default_factory=dict)
    apdu: Optional["ParseResult"] = None   # inner ParseResult if a function-code schema matched
    raw: bytes = b""
    outer_offset: int = 0              # for inner results: starting byte offset within the outer frame

    def __getitem__(self, dot_path: str) -> FieldNode:
        n = self.get(dot_path)
        if n is None:
            raise KeyError(dot_path)
        return n

    def get(self, dot_path: str, default: Any = None) -> Optional[FieldNode]:
        parts = dot_path.split(".")
        cur: Any = self
        for p in parts:
            if isinstance(cur, ParseResult):
                if p == "apdu" and cur.apdu is not None:
                    cur = cur.apdu
                    continue
                if p in cur.fields:
                    cur = cur.fields[p]
                    continue
                return default
            elif isinstance(cur, FieldNode):
                if cur.children is None:
                    return default
                match = next((c for c in cur.children if c.name == p), None)
                if match is None:
                    return default
                cur = match
            else:
                return default
        return cur if isinstance(cur, FieldNode) else default

    def to_dict(self, *, include_raw: bool = True) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "protocol": self.protocol,
            "frame_type": self.frame_type,
            "function_code": (None if self.function_code is None else f"0x{self.function_code:02X}"),
            "valid": self.valid,
            "errors": list(self.errors),
            "fields": {k: v.to_dict(include_raw=include_raw) for k, v in self.fields.items()},
        }
        if self.apdu is not None:
            d["apdu"] = self.apdu.to_dict(include_raw=include_raw)
        if include_raw:
            d["raw"] = self.raw.hex().upper()
        return d

    def format(self, *, indent: int = 0, base_offset: int = 0) -> str:
        pad = "  " * indent
        head = f"{pad}protocol={self.protocol} frame_type={self.frame_type}"
        if self.function_code is not None:
            head += f" function_code=0x{self.function_code:02X}"
        head += f" valid={self.valid}"
        if self.errors:
            head += " errors=" + "; ".join(self.errors)
        lines = [head]
        for n in self.fields.values():
            lines.append(_format_node(n, indent + 1, base_offset=base_offset))
        if self.apdu is not None:
            inner_base = base_offset + self.apdu.outer_offset
            lines.append(f"{pad}  apdu (offsets are absolute within the outer frame):")
            lines.append(self.apdu.format(indent=indent + 2, base_offset=inner_base))
        return "\n".join(lines)

    # ----- byte-map view: every byte's owning field, sorted by absolute offset -----
    def format_byte_map(self) -> str:
        """Render a flat, byte-by-byte table with absolute offsets and descriptions.

        Every field (outer + nested APDU) appears on a single line, sorted by the
        byte where it starts in the original frame. The payload field itself
        (`apdu`/`data`) is omitted when an inner result is available, because its
        sub-fields cover the same bytes more precisely.
        """
        rows: List[Tuple[int, FieldNode, str, str]] = []     # (offset, node, full_name, scope)
        self._collect_byte_rows(rows, base_offset=0, prefix="", scope="outer")
        rows.sort(key=lambda r: r[0])

        # Compute column widths
        name_w = max(8, max((len(r[2]) for r in rows), default=8))
        # render
        out = [
            f"frame raw bytes ({len(self.raw)} bytes): {self.raw.hex(' ').upper()}",
            "",
            f"{'offset':<7} {'len':<3} {'bytes':<24} {'field':<{name_w}}  value / meaning",
            "-" * (7 + 1 + 3 + 1 + 24 + 1 + name_w + 2 + 40),
        ]
        for off, node, name, scope in rows:
            hex_part = node.raw_bytes.hex(" ").upper()
            if len(hex_part) > 23:
                hex_part = hex_part[:20] + "..."
            off_part = f"{off}" if node.length <= 1 else f"{off}-{off + node.length - 1}"
            value_str = _pretty(node.value)
            extras = []
            if node.bit_fields:
                extras.append("{" + ", ".join(f"{k}={v}" for k, v in node.bit_fields.items()) + "}")
            if node.description:
                extras.append(f"// {node.description.splitlines()[0]}")
            extra_str = "  ".join(extras)
            out.append(f"{off_part:<7} {node.length:<3} {hex_part:<24} {name:<{name_w}}  "
                       f"{value_str}{('  ' + extra_str) if extra_str else ''}")
        return "\n".join(out)

    def _collect_byte_rows(self, rows, *, base_offset: int, prefix: str, scope: str) -> None:
        for name, node in self.fields.items():
            if self.apdu is not None and node.name in ("apdu", "data"):
                # The payload field itself is fully explained by the inner ParseResult below
                continue
            full_name = f"{prefix}{node.name}"
            rows.append((node.offset + base_offset, node, full_name, scope))
        if self.apdu is not None:
            inner_base = base_offset + self.apdu.outer_offset
            self.apdu._collect_byte_rows(rows, base_offset=inner_base,
                                         prefix=prefix + "apdu.", scope="apdu")


def _format_node(n: FieldNode, indent: int, base_offset: int = 0) -> str:
    pad = "  " * indent
    abs_off = n.offset + base_offset
    off_part = f"{abs_off}" if n.length <= 1 else f"{abs_off}-{abs_off + n.length - 1}"
    base = (f"{pad}{n.name:<20} @{off_part:<7} len={n.length:<3} "
            f"raw={n.raw_bytes.hex(' ').upper():<32} value={_pretty(n.value)}")
    extras = []
    if n.bit_fields:
        extras.append("bits=" + ",".join(f"{k}={v}" for k, v in n.bit_fields.items()))
    if n.description:
        extras.append("// " + n.description.splitlines()[0])
    if extras:
        base += "  " + "  ".join(extras)
    if n.children:
        for c in n.children:
            base += "\n" + _format_node(c, indent + 1, base_offset=base_offset)
    return base


def _pretty(v: Any) -> str:
    if isinstance(v, bytes):
        return v.hex(" ").upper()
    if isinstance(v, int):
        return f"{v} (0x{v:X})"
    if isinstance(v, dict):
        items = ", ".join(f"{k}={_pretty(val)}" for k, val in v.items())
        return "{" + items + "}"
    return repr(v)


def _jsonify(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.hex().upper()
    if isinstance(v, dict):
        return {k: _jsonify(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonify(x) for x in v]
    return v
