"""Command-line interface: `python -m protocol <subcommand> ...`.

All output is JSON (UTF-8) for easy consumption from other languages.
Errors go to stderr as JSON with non-zero exit code.

Subcommands
-----------
- identify   : auto-detect the protocol of a frame
- parse      : parse a frame, full per-field tree
- bytemap    : flat byte-by-byte field map
- build      : construct a frame from defaults + overrides
- list       : list registered protocols / services
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from . import ProtocolEngine
from .errors import ProtocolError


# ---------------------------------------------------------------------------
def _read_hex(arg: str | None) -> str:
    """Read hex from arg or stdin."""
    if arg:
        return arg
    if sys.stdin.isatty():
        raise SystemExit("error: no --hex argument and stdin is empty")
    return sys.stdin.read()


def _engine(schemas_path: str) -> ProtocolEngine:
    engine = ProtocolEngine()
    engine.load_schemas(schemas_path)
    return engine


# ---------------------------------------------------------------------------
def cmd_identify(args) -> Dict[str, Any]:
    engine = _engine(args.schemas)
    proto = engine.identify(_read_hex(args.hex))
    return {"protocol": proto}


def cmd_parse(args) -> Dict[str, Any]:
    engine = _engine(args.schemas)
    result = engine.parse(
        _read_hex(args.hex),
        protocol=args.protocol,
        strict=args.strict,
    )
    return result.to_dict(include_raw=True)


def cmd_bytemap(args) -> Dict[str, Any]:
    """Return a flat list of {offset, length, hex, field, value, description, bits}."""
    engine = _engine(args.schemas)
    result = engine.parse(
        _read_hex(args.hex),
        protocol=args.protocol,
        strict=args.strict,
    )
    rows: list[dict] = []
    result._collect_byte_rows(rows_list := [], base_offset=0, prefix="", scope="outer")
    rows_list.sort(key=lambda r: r[0])
    for off, node, full_name, scope in rows_list:
        rows.append({
            "offset": off,
            "length": node.length,
            "hex": node.raw_bytes.hex(" ").upper(),
            "field": full_name,
            "value": _jsonify(node.value),
            "bit_fields": dict(node.bit_fields) if node.bit_fields else None,
            "description": node.description,
        })
    return {
        "protocol": result.protocol,
        "function_code": (
            None if (result.apdu is None or result.apdu.function_code is None)
            else f"0x{result.apdu.function_code:02X}"
        ),
        "frame_type": result.apdu.frame_type if result.apdu is not None else "base",
        "valid": result.valid,
        "errors": list(result.errors),
        "byte_map": rows,
        "raw": result.raw.hex(" ").upper(),
    }


def cmd_build(args) -> Dict[str, Any]:
    engine = _engine(args.schemas)
    fields = json.loads(args.fields) if args.fields else {}
    if args.fields_file:
        fields = json.loads(Path(args.fields_file).read_text(encoding="utf-8"))
    raw = engine.build(
        protocol=args.protocol,
        function_code=args.function_code,
        frame_type=args.frame_type,
        fields=fields,
    )
    return {"hex": raw.hex(" ").upper(), "length": len(raw)}


def cmd_list(args) -> Dict[str, Any]:
    engine = _engine(args.schemas)
    if args.protocol:
        return {
            "protocol": args.protocol,
            "services": [f"0x{code:02X}" for code in engine.list_services(args.protocol)],
        }
    return {
        "protocols": [
            {
                "name": p,
                "services": [f"0x{c:02X}" for c in engine.list_services(p)],
            }
            for p in engine.list_protocols()
        ]
    }


# ---------------------------------------------------------------------------
def _jsonify(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.hex().upper()
    if isinstance(v, dict):
        return {k: _jsonify(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonify(x) for x in v]
    return v


def _int_arg(s: str) -> int:
    return int(s, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m protocol",
        description="Generic protocol parser/builder CLI",
    )
    parser.add_argument("--schemas", default="schemas",
                        help="path to schemas directory (default: ./schemas)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_id = sub.add_parser("identify", help="Auto-identify protocol from a hex frame")
    p_id.add_argument("--hex", help="hex string of the frame (or read from stdin)")

    p_parse = sub.add_parser("parse", help="Parse a frame into a structured tree")
    p_parse.add_argument("--hex", help="hex string of the frame (or read from stdin)")
    p_parse.add_argument("--protocol", help="force protocol name (skip auto-identify)")
    p_parse.add_argument("--no-strict", dest="strict", action="store_false",
                         help="do not raise on checksum mismatch")
    p_parse.set_defaults(strict=True)

    p_bm = sub.add_parser("bytemap", help="Parse and return a flat byte-by-byte map")
    p_bm.add_argument("--hex", help="hex string of the frame (or read from stdin)")
    p_bm.add_argument("--protocol", help="force protocol name")
    p_bm.add_argument("--no-strict", dest="strict", action="store_false")
    p_bm.set_defaults(strict=True)

    p_build = sub.add_parser("build", help="Build a frame from defaults + overrides")
    p_build.add_argument("--protocol", required=True)
    p_build.add_argument("--function-code", type=_int_arg, default=None,
                         help="function code, int or 0xHH form (omit for outer-only)")
    p_build.add_argument("--frame-type",
                         choices=["get_request", "get_response", "set_request", "set_response"])
    p_build.add_argument("--fields", help='JSON dict of overrides, e.g. \'{"data.da":"0101"}\'')
    p_build.add_argument("--fields-file", help="path to a JSON file with field overrides")

    p_list = sub.add_parser("list", help="List registered protocols and services")
    p_list.add_argument("--protocol", help="if given, list services for this protocol only")

    return parser


HANDLERS = {
    "identify": cmd_identify,
    "parse": cmd_parse,
    "bytemap": cmd_bytemap,
    "build": cmd_build,
    "list": cmd_list,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = HANDLERS[args.cmd](args)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0
    except ProtocolError as e:
        sys.stderr.write(json.dumps(
            {"error": type(e).__name__, "message": str(e)},
            ensure_ascii=False,
        ) + "\n")
        return 1
    except Exception as e:                                            # pragma: no cover
        sys.stderr.write(json.dumps(
            {"error": type(e).__name__, "message": str(e)},
            ensure_ascii=False,
        ) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
