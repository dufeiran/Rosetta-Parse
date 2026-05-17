"""End-to-end demo for the protocol parser/builder.

Run from project root:
    python examples/demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `src/` importable when running this file directly
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from protocol import ProtocolEngine

SCHEMAS = ROOT / "schemas"


def demo_build_and_parse_3762():
    print("=" * 78)
    print("Demo 1 — 376.2 AFN=0x0C 组查询帧（主站请求实时数据 p1/F1）")
    print("=" * 78)

    engine = ProtocolEngine()
    engine.load_schemas(SCHEMAS)

    frame = engine.build(
        protocol="gw3762",
        function_code=0x0C,
        frame_type="get_request",
        fields={
            "address": "3201000100",        # 终端地址
            "control": 0x4B,                # 主站→终端，PRM=1
            "seq": 0x60,
            "data.da": "0101",              # Pn = p1, DA1=01 DA2=01
            "data.dt": "0100",              # Fn = F1, DT1=01 DT2=00
        },
    )
    print(f"build → {frame.hex(' ').upper()}  ({len(frame)} bytes)")

    parsed = engine.parse(frame)
    print("--- 树形视图（每个字段含绝对偏移、字节、值、含义）---")
    print(parsed.format())
    print()
    print("--- 字节归属表（按整帧偏移排序，每个字节都能找到对应字段）---")
    print(parsed.format_byte_map())
    print()


def demo_build_and_parse_3762_set():
    print("=" * 78)
    print("Demo 2 — 376.2 AFN=0x04 组设置帧（设置主站 IP=192.168.1.100, port=2404）")
    print("=" * 78)

    engine = ProtocolEngine()
    engine.load_schemas(SCHEMAS)

    frame = engine.build(
        protocol="gw3762",
        function_code=0x04,
        frame_type="set_request",
        fields={
            "address": "3201000100",
            "data.master_ip": "C0A80164",
            "data.master_port": "6409",      # 2404 -> 0x0964; LE bytes are 64 09
        },
    )
    print(f"build → {frame.hex(' ').upper()}  ({len(frame)} bytes)")

    parsed = engine.parse(frame)
    print(parsed.format())
    print()


def demo_build_and_parse_698():
    print("=" * 78)
    print("Demo 3 — 698 GET-Request-Normal（读取 OAD=0x4000-2-0 电能量当前值）")
    print("=" * 78)

    engine = ProtocolEngine()
    engine.load_schemas(SCHEMAS)

    frame = engine.build(
        protocol="dlt698",
        function_code=0x05,
        frame_type="get_request",
        fields={
            "control": 0x43,                 # client→server, PRM=1, function=3
            "addr_prefix": 0x05,             # 单点 + 6 字节逻辑地址
            "addr_body": "000000000001",     # 6 字节 BCD 逻辑地址
            "addr_sa": 0x00,
            "data.piid": 0x10,
            "data.oad": "40000200",
        },
    )
    print(f"build → {frame.hex(' ').upper()}  ({len(frame)} bytes)")

    parsed = engine.parse(frame)
    print("--- 树形视图 ---")
    print(parsed.format())
    print()
    print("--- 字节归属表 ---")
    print(parsed.format_byte_map())
    print()


def demo_outer_only_fallback():
    print("=" * 78)
    print("Demo 4 — 仅 base.yaml 解析（功能码 yaml 不存在时的兜底）")
    print("=" * 78)

    engine = ProtocolEngine()
    engine.load_schemas(SCHEMAS)

    # 构造一个 AFN=0xAA 的 376.2 帧，没有 yaml 对应，只能解出外层
    frame = engine.build(
        protocol="gw3762",
        function_code=None,
        fields={
            "address": "1234567890",
            "afn": 0xAA,
            "seq": 0x60,
            "data": "DEADBEEF",
        },
    )
    print(f"build → {frame.hex(' ').upper()}  ({len(frame)} bytes)")

    parsed = engine.parse(frame)
    print(parsed.format())
    print()


def demo_identify():
    print("=" * 78)
    print("Demo 5 — 自动识别协议（两种协议都以 0x68 开头）")
    print("=" * 78)

    engine = ProtocolEngine()
    engine.load_schemas(SCHEMAS)

    # 构造两条帧
    f3762 = engine.build(protocol="gw3762", fields={"afn": 0x0C, "data": "0101 0100"})
    f698 = engine.build(protocol="dlt698", fields={"data": "05 01 00 40 00 02 00 00"})

    print(f"3762 frame: {f3762.hex(' ').upper()}")
    print(f"  identified as: {engine.identify(f3762)}")
    print(f" 698 frame: {f698.hex(' ').upper()}")
    print(f"  identified as: {engine.identify(f698)}")
    print()


if __name__ == "__main__":
    demo_build_and_parse_3762()
    demo_build_and_parse_3762_set()
    demo_build_and_parse_698()
    demo_outer_only_fallback()
    demo_identify()
