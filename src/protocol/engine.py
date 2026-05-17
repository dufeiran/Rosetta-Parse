"""Public engine facade."""
from __future__ import annotations

from pathlib import Path
from typing import List, Mapping, Optional, Union

from .algo.registry import default_registry as _default_algos
from .builder.frame_builder import build_frame
from .codec.registry import default_registry as _default_codecs
from .errors import BuildError, IdentifyError, ParseError
from .identify.identifier import Identifier
from .parser.frame_parser import parse_frame
from .result import ParseResult
from .schema.registry import SchemaRegistry
from .util.hexutil import HexLike, to_bytes


class ProtocolEngine:
    def __init__(self) -> None:
        self.schemas = SchemaRegistry()
        self.codecs = _default_codecs()
        self.algos = _default_algos()
        self.identifier = Identifier(self.schemas)

    # ---- Schema loading ----
    def load_schemas(self, path: Union[str, Path]) -> "ProtocolEngine":
        self.schemas.load_from_path(path)
        return self

    # ---- Listing ----
    def list_protocols(self) -> List[str]:
        return [p.name for p in self.schemas.protocols()]

    def list_services(self, protocol: str) -> List[int]:
        return self.schemas.list_services(protocol)

    # ---- Identification ----
    def identify(self, data: HexLike) -> Optional[str]:
        return self.identifier.identify(to_bytes(data))

    # ---- Parsing ----
    def parse(self,
              data: HexLike,
              *,
              protocol: Optional[str] = None,
              strict: bool = True) -> ParseResult:
        raw = to_bytes(data)
        if protocol is None:
            protocol = self.identifier.identify(raw)
            if protocol is None:
                raise IdentifyError(f"could not identify protocol for frame {raw.hex().upper()}")
        base = self.schemas.get_protocol(protocol)
        return parse_frame(
            base=base,
            data=raw,
            codecs=self.codecs,
            algos=self.algos,
            service_lookup=self.schemas.get_service,
            strict=strict,
        )

    # ---- Building ----
    def build(self,
              protocol: str,
              *,
              function_code: Optional[int] = None,
              frame_type: Optional[str] = None,
              fields: Optional[Mapping[str, object]] = None) -> bytes:
        base = self.schemas.get_protocol(protocol)
        service = None
        if function_code is not None:
            service = self.schemas.get_service(protocol, function_code)
            if service is None:
                raise BuildError(f"no service yaml registered for {protocol} "
                                 f"function_code=0x{function_code:02X}")
            if frame_type is None:
                raise BuildError("frame_type is required when function_code is given")
        return build_frame(
            base=base,
            service=service,
            frame_type=frame_type,
            fields=fields,
            codecs=self.codecs,
            algos=self.algos,
        )
