"""Custom exception hierarchy."""


class ProtocolError(Exception):
    """Base for all protocol package errors."""


class SchemaError(ProtocolError):
    """Raised when a YAML schema is malformed or self-inconsistent."""


class IdentifyError(ProtocolError):
    """Raised when protocol auto-identification fails."""


class ParseError(ProtocolError):
    """Raised when a frame cannot be parsed."""


class BuildError(ProtocolError):
    """Raised when a frame cannot be built."""


class CodecError(ProtocolError):
    """Raised by codec encode/decode on bad input."""
