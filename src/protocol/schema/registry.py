"""In-memory registry of loaded schemas."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..errors import SchemaError
from .loader import load_yaml_file, parse_protocol_base, parse_service
from .model import ProtocolBase, ServiceSchema


class SchemaRegistry:
    def __init__(self) -> None:
        self._bases: Dict[str, ProtocolBase] = {}
        self._services: Dict[Tuple[str, int], ServiceSchema] = {}

    # ---- registration ----
    def add_protocol_base(self, base: ProtocolBase) -> None:
        if base.name in self._bases:
            raise SchemaError(f"protocol base already registered: {base.name}")
        self._bases[base.name] = base

    def add_service(self, svc: ServiceSchema) -> None:
        if svc.protocol not in self._bases:
            raise SchemaError(f"service references unknown protocol: {svc.protocol}")
        self._services[(svc.protocol, svc.service_code)] = svc

    def load_from_path(self, root: str | Path) -> None:
        """Recursively load every *.yaml under `root`.

        Loading order: base files first (those with `protocol:` top-level key),
        then service files (those with `service:` top-level key).
        """
        rp = Path(root)
        if not rp.exists():
            raise SchemaError(f"schema path does not exist: {rp}")
        files = sorted(rp.rglob("*.yaml")) + sorted(rp.rglob("*.yml"))
        bases: List[Path] = []
        services: List[Path] = []
        for f in files:
            doc = load_yaml_file(f)
            if "protocol" in doc and "frames" in doc and "base" in (doc["frames"] or {}):
                bases.append(f)
            elif "service" in doc:
                services.append(f)
            else:
                raise SchemaError(f"unrecognized YAML file (no 'protocol' base or 'service'): {f}")
        for f in bases:
            self.add_protocol_base(parse_protocol_base(load_yaml_file(f), source=str(f)))
        for f in services:
            self.add_service(parse_service(load_yaml_file(f), source=str(f)))

    # ---- lookup ----
    def protocols(self) -> List[ProtocolBase]:
        return list(self._bases.values())

    def get_protocol(self, name: str) -> ProtocolBase:
        try:
            return self._bases[name]
        except KeyError as e:
            raise SchemaError(f"protocol not registered: {name!r}") from e

    def get_service(self, protocol: str, code: int) -> Optional[ServiceSchema]:
        return self._services.get((protocol, code))

    def list_services(self, protocol: str) -> List[int]:
        return sorted(code for (p, code) in self._services.keys() if p == protocol)
