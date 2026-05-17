"""Minimal HTTP server exposing the protocol engine.

Standard library only - no Flask/FastAPI needed. Suitable for use as a
local sidecar that C# / Java / other-language clients can call over JSON.

Endpoints
---------
- POST /identify  body: {"hex": "..."}
                  resp: {"protocol": "dlt698"} | {"protocol": null}
- POST /parse     body: {"hex": "...", "protocol": null, "strict": true}
                  resp: full ParseResult dict
- POST /bytemap   body: {"hex": "...", "protocol": null, "strict": true}
                  resp: {"protocol":..., "byte_map":[{offset,length,hex,field,value,...}]}
- POST /build     body: {"protocol": "...", "function_code": 12, "frame_type": "get_request", "fields": {...}}
                  resp: {"hex": "...", "length": 20}
- GET  /list                                  → list of protocols and services
- GET  /list?protocol=dlt698                  → services of one protocol

Run
---
    python examples/http_server.py [--host 127.0.0.1] [--port 8765] [--schemas schemas]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from protocol import ProtocolEngine
from protocol.errors import ProtocolError


# Module-level engine: load once, reuse across requests
_engine: ProtocolEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> ProtocolEngine:
    assert _engine is not None, "engine not initialized"
    return _engine


# ---------------------------------------------------------------------------
def _jsonify(v):
    if isinstance(v, bytes):
        return v.hex().upper()
    if isinstance(v, dict):
        return {k: _jsonify(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonify(x) for x in v]
    return v


def _byte_map(result) -> list[dict]:
    rows: list = []
    result._collect_byte_rows(rows, base_offset=0, prefix="", scope="outer")
    rows.sort(key=lambda r: r[0])
    return [
        {
            "offset": off,
            "length": node.length,
            "hex": node.raw_bytes.hex(" ").upper(),
            "field": full_name,
            "value": _jsonify(node.value),
            "bit_fields": dict(node.bit_fields) if node.bit_fields else None,
            "description": node.description,
        }
        for off, node, full_name, scope in rows
    ]


# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Quieter logging
        sys.stderr.write(f"[{self.address_string()}] {fmt % args}\n")

    # --- response helpers ----------------------------------------------------
    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON body: {e}")

    # --- routes --------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        engine = get_engine()
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/list":
            qs = urllib.parse.parse_qs(parsed.query)
            proto = qs.get("protocol", [None])[0]
            if proto:
                services = [f"0x{c:02X}" for c in engine.list_services(proto)]
                self._send_json(200, {"protocol": proto, "services": services})
            else:
                items = [
                    {"name": p, "services": [f"0x{c:02X}" for c in engine.list_services(p)]}
                    for p in engine.list_protocols()
                ]
                self._send_json(200, {"protocols": items})
            return
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "NotFound", "message": parsed.path})

    def do_POST(self):
        engine = get_engine()
        try:
            body = self._read_body_json()
            if self.path == "/identify":
                proto = engine.identify(body.get("hex", ""))
                self._send_json(200, {"protocol": proto})
                return
            if self.path == "/parse":
                r = engine.parse(
                    body.get("hex", ""),
                    protocol=body.get("protocol"),
                    strict=body.get("strict", True),
                )
                self._send_json(200, r.to_dict(include_raw=True))
                return
            if self.path == "/bytemap":
                r = engine.parse(
                    body.get("hex", ""),
                    protocol=body.get("protocol"),
                    strict=body.get("strict", True),
                )
                self._send_json(200, {
                    "protocol": r.protocol,
                    "function_code": (
                        None if (r.apdu is None or r.apdu.function_code is None)
                        else f"0x{r.apdu.function_code:02X}"
                    ),
                    "frame_type": r.apdu.frame_type if r.apdu is not None else "base",
                    "valid": r.valid,
                    "errors": list(r.errors),
                    "raw": r.raw.hex(" ").upper(),
                    "byte_map": _byte_map(r),
                })
                return
            if self.path == "/build":
                raw = engine.build(
                    protocol=body["protocol"],
                    function_code=body.get("function_code"),
                    frame_type=body.get("frame_type"),
                    fields=body.get("fields") or {},
                )
                self._send_json(200, {"hex": raw.hex(" ").upper(), "length": len(raw)})
                return
            self._send_json(404, {"error": "NotFound", "message": self.path})
        except ProtocolError as e:
            self._send_json(400, {"error": type(e).__name__, "message": str(e)})
        except (KeyError, ValueError, TypeError) as e:
            self._send_json(400, {"error": type(e).__name__, "message": str(e)})


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Protocol engine HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--schemas", default=str(ROOT / "schemas"))
    args = parser.parse_args()

    global _engine
    with _engine_lock:
        _engine = ProtocolEngine()
        _engine.load_schemas(args.schemas)
        print(f"loaded {len(_engine.list_protocols())} protocols from {args.schemas}",
              file=sys.stderr)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"serving on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutdown", file=sys.stderr)


if __name__ == "__main__":
    main()
