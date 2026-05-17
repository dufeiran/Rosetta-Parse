"""Generic YAML-driven protocol parser/builder.

Public API:
    from protocol import ProtocolEngine, ParseResult, FieldNode
    from protocol.errors import ParseError, BuildError, SchemaError, IdentifyError
"""
from .engine import ProtocolEngine
from .result import ParseResult, FieldNode
from . import errors

__all__ = ["ProtocolEngine", "ParseResult", "FieldNode", "errors"]
__version__ = "0.1.0"
