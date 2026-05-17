"""Typed schema model (dataclasses) built from YAML."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class BitFieldSpec:
    name: str
    bits: str                          # "7-4" or "7"
    description: Optional[str] = None
    values: Optional[Dict[Any, str]] = None


@dataclass
class FieldSchema:
    name: str
    type: str                          # codec name
    length: Union[int, str] = 0        # int or "variable"
    default: Any = None
    description: Optional[str] = None
    role: Optional[str] = None
    auto: bool = False
    algorithm: Optional[str] = None
    range_start: Optional[str] = None  # inclusive
    range_end: Optional[str] = None    # exclusive
    transform_mask: Optional[int] = None
    transform_reserved_bits: int = 0
    bit_fields: List[BitFieldSpec] = field(default_factory=list)
    children: List["FieldSchema"] = field(default_factory=list)
    values: Optional[Dict[Any, str]] = None
    # 376.2: length2's source (copy_field)
    source_field: Optional[str] = None
    # extra raw dict kept for codecs that need rare keys (e.g. bcd_digits)
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameSchema:
    name: str                          # "base" | "set_request" | "set_response" | "get_request" | "get_response"
    fields: List[FieldSchema] = field(default_factory=list)
    description: Optional[str] = None
    enabled: bool = True


@dataclass
class IdentifierRule:
    check: str
    params: Dict[str, Any]


@dataclass
class IdentifierSpec:
    start_byte: Optional[int] = None
    rules: List[IdentifierRule] = field(default_factory=list)


@dataclass
class VariantSelectorRule:
    when: Dict[str, Any]               # e.g. {"dir": 0, "prm": 1}
    variant: str


@dataclass
class ProtocolBase:
    name: str
    display_name: Optional[str]
    description: Optional[str]
    identifier: IdentifierSpec
    base_frame: FrameSchema
    payload_field: str                 # which field in base_frame carries the inner APDU


@dataclass
class ServiceSchema:
    protocol: str
    service_code: int                  # AFN (376.2) or service-choice (698)
    display_name: Optional[str]
    description: Optional[str]
    frames: Dict[str, FrameSchema] = field(default_factory=dict)   # keyed by frame_type
    variant_selector: List[VariantSelectorRule] = field(default_factory=list)
