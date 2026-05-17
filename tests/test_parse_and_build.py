"""Tests for parsing externally-sourced frames (not roundtrip)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from protocol import ProtocolEngine


def make_engine() -> ProtocolEngine:
    e = ProtocolEngine()
    e.load_schemas(ROOT / "schemas")
    return e


def test_identify_3762():
    e = make_engine()
    # Known-good 376.2 frame (synthesized from our own build, but treat as opaque hex)
    raw = "68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16"
    assert e.identify(raw) == "gw3762"


def test_identify_698():
    e = make_engine()
    raw = "68 19 00 43 05 00 00 00 00 00 01 00 77 29 05 01 10 40 00 02 00 00 E6 5D 16"
    assert e.identify(raw) == "dlt698"


def test_parse_3762_apdu_descent():
    e = make_engine()
    raw = "68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16"
    r = e.parse(raw)
    assert r.protocol == "gw3762"
    assert r.frame_type == "base"
    assert r.valid is True
    # Outer fields
    assert r["afn"].value == 0x0C
    assert r["cs"].value == 0xEE
    assert r["data"].raw_bytes == bytes.fromhex("0101 0100".replace(" ", ""))
    # APDU descent (function-code yaml matched)
    assert r.apdu is not None
    assert r.apdu.function_code == 0x0C
    assert r.apdu.frame_type == "get_request"
    assert r.apdu["da"].raw_bytes == bytes.fromhex("0101")
    assert r.apdu["dt"].raw_bytes == bytes.fromhex("0100")


def test_parse_698_apdu_descent():
    e = make_engine()
    raw = "68 19 00 43 05 00 00 00 00 00 01 00 77 29 05 01 10 40 00 02 00 00 E6 5D 16"
    r = e.parse(raw)
    assert r.protocol == "dlt698"
    assert r.frame_type == "base"
    assert r.valid is True
    # Outer
    assert r["length"].value == 0x19
    assert r["control"].bit_fields == {"dir": 0, "prm": 1, "division": 0, "sleep": 0,
                                       "function_code": 3}
    assert r["addr_prefix"].bit_fields == {"addr_type": 0, "addr_len_m1": 5}
    # APDU descent
    assert r.apdu is not None
    assert r.apdu.function_code == 0x05
    assert r.apdu.frame_type == "get_request"
    assert r.apdu["service_choice"].value == 0x05
    assert r.apdu["piid"].value == 0x10
    oad = r.apdu["oad"].value
    assert isinstance(oad, dict)
    assert oad["oi"] == 0x4000
    assert oad["attr_idx"] == 0x02
    assert oad["attr_qualifier"] == 0x00


def test_parse_outer_only_when_no_service_yaml():
    """When no function-code yaml is registered, return outer fields only with raw data."""
    e = make_engine()
    # AFN=0xAA is not in our schemas/gw3762/ → only base.yaml applies.
    raw = "68 0C 00 0C 00 68 4B 12 34 56 78 90 AA 60 DE AD BE EF 31 16"
    r = e.parse(raw)
    assert r.protocol == "gw3762"
    assert r.frame_type == "base"
    assert r.valid is True
    assert r["afn"].value == 0xAA
    assert r["data"].raw_bytes == bytes.fromhex("DEADBEEF")
    assert r.apdu is None    # no inner descent


def test_corrupt_frame_strict_raises():
    """Bad checksum should raise in strict mode."""
    from protocol.errors import ParseError
    e = make_engine()
    # Flip the CS byte
    raw = "68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 FF 16"
    try:
        e.parse(raw, strict=True)
    except ParseError as ex:
        assert "cs" in str(ex).lower() or "mismatch" in str(ex).lower()
    else:
        raise AssertionError("expected ParseError on bad checksum")


def test_corrupt_frame_lax_returns_invalid():
    e = make_engine()
    raw = "68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 FF 16"
    r = e.parse(raw, strict=False)
    assert r.valid is False
    assert any("mismatch" in err for err in r.errors)


def test_build_roundtrip():
    """build → parse → same fields."""
    e = make_engine()
    frame = e.build(
        protocol="gw3762",
        function_code=0x04,
        frame_type="set_request",
        fields={
            "address": "AABBCCDDEE",
            "data.master_ip": "C0A80101",
            "data.master_port": "FF0A",
        },
    )
    r = e.parse(frame)
    assert r.valid is True
    assert r["address"].raw_bytes == bytes.fromhex("AABBCCDDEE")
    assert r["afn"].value == 0x04
    assert r.apdu is not None
    assert r.apdu["master_ip"].raw_bytes == bytes.fromhex("C0A80101")


if __name__ == "__main__":
    tests = [
        test_identify_3762,
        test_identify_698,
        test_parse_3762_apdu_descent,
        test_parse_698_apdu_descent,
        test_parse_outer_only_when_no_service_yaml,
        test_corrupt_frame_strict_raises,
        test_corrupt_frame_lax_returns_invalid,
        test_build_roundtrip,
    ]
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
