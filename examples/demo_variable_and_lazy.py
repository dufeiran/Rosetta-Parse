"""Demo for variable-length data areas and lazy partial parsing.

Two scenarios:
  A) Variable-length A-XDR data in 698 GET-Response (self-delimiting via tag)
  B) Lazy parse: declare known fields + a trailing `tail` bytes field that swallows the rest
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from protocol import ProtocolEngine


def demo_a_variable_axdr():
    print("=" * 78)
    print("场景 A — 698 GET-Response，data 字段长度由 A-XDR tag 自决")
    print("=" * 78)

    engine = ProtocolEngine()
    engine.load_schemas(ROOT / "schemas")

    # 把 data 改成 octet_string（A-XDR tag=0x09 + 长度前缀 + 数据）
    # tag=09, length=04, value=DEADBEEF → 共 6 字节
    frame = engine.build(
        protocol="dlt698",
        function_code=0x85,
        frame_type="get_response",
        fields={
            "addr_prefix": 0x05,
            "addr_body":   "000000000001",
            "addr_sa":     0x00,
            "data.piid_acd":  0x10,
            "data.oad":       "40000200",
            "data.data_result_choice": 0,
            "data.data":      "09 04 DE AD BE EF",   # axdr_typed_data: 6 字节
            "data.time_tag_choice": 0,
        },
    )
    print(f"build → {frame.hex(' ').upper()}  ({len(frame)} 字节)")
    print()
    r = engine.parse(frame)
    print(r.format_byte_map())
    print()

    # 换一个不同长度的 data 再来一遍，验证长度自适应
    print("换长一点的 data（10 字节）再来一次：")
    frame2 = engine.build(
        protocol="dlt698",
        function_code=0x85,
        frame_type="get_response",
        fields={
            "addr_prefix": 0x05, "addr_body": "000000000001", "addr_sa": 0,
            "data.piid_acd": 0x10, "data.oad": "40000200",
            "data.data_result_choice": 0,
            "data.data": "09 08 01 02 03 04 05 06 07 08",   # tag + len + 8 bytes
            "data.time_tag_choice": 0,
        },
    )
    print(f"build → {frame2.hex(' ').upper()}  ({len(frame2)} 字节)")
    r2 = engine.parse(frame2)
    print(f"data 解析结果：{r2['apdu.data'].value}")
    print(f"frame 总长由 length 字段反推：length={r2['length'].value}  vs 实际 {len(frame2)}")
    print()


# ---------------------------------------------------------------------------
LAZY_AFN_YAML = """
# 偷懒示例：AFN=0xF0（虚构的"私有数据"功能码）
# 只关心头 4 字节，剩下统统塞进 tail 让用户自己处理
service:
  protocol: gw3762
  service_code: 0xF0
  display_name: "私有数据（偷懒解析）"

frames:
  get_response:
    description: "只精确解析前 4 字节，其余直接 dump 成 tail"
    fields:
      - name: da
        type: bytes
        length: 2
        default: "0101"
        bit_fields:
          - { name: da2, bits: "7-0" }
          - { name: da1, bits: "15-8" }
      - name: dt
        type: bytes
        length: 2
        default: "0100"
        bit_fields:
          - { name: dt2, bits: "7-0" }
          - { name: dt1, bits: "15-8" }
      - name: tail
        type: bytes
        length: variable          # 关键：自动占满剩余字节
        default: ""
        description: "未深度解析的剩余字节，用户后续自行处理"
"""


def demo_b_lazy_partial():
    print("=" * 78)
    print("场景 B — 偷懒：前 4 字节按字段解析，剩余全部塞进 tail")
    print("=" * 78)

    with tempfile.TemporaryDirectory() as td:
        # 加载内置 376.2 base + 这个临时 AFN yaml
        proto_dir = Path(td) / "gw3762"
        proto_dir.mkdir()
        # 复制 base.yaml
        (proto_dir / "base.yaml").write_text(
            (ROOT / "schemas" / "gw3762" / "base.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (proto_dir / "afn_f0_lazy.yaml").write_text(LAZY_AFN_YAML, encoding="utf-8")

        engine = ProtocolEngine()
        engine.load_schemas(td)

        # 构造一个数据域 = DA(2) + DT(2) + 12 字节"未知数据" 的帧
        frame = engine.build(
            protocol="gw3762",
            function_code=0xF0,
            frame_type="get_response",
            fields={
                "address": "AABBCCDDEE",
                "control": 0xCB,                          # PRM=1, DIR=1 → 终端响应
                "data.da":   "0102",
                "data.dt":   "0304",
                "data.tail": "11 22 33 44 55 66 77 88 99 AA BB CC",
            },
        )
        print(f"build → {frame.hex(' ').upper()}  ({len(frame)} 字节)")
        print()
        r = engine.parse(frame)
        print(r.format_byte_map())
        print()

        # 程序读取
        print(f"da   = {r['apdu.da'].value.hex().upper()}  bits={r['apdu.da'].bit_fields}")
        print(f"dt   = {r['apdu.dt'].value.hex().upper()}  bits={r['apdu.dt'].bit_fields}")
        print(f"tail = {r['apdu.tail'].value.hex(' ').upper()}  ({r['apdu.tail'].length} 字节)")


# ---------------------------------------------------------------------------
def demo_c_external_unknown():
    """完全不写功能码 yaml，但又想看到数据域被切片显示 —— 走 base.yaml 兜底"""
    print("=" * 78)
    print("场景 C — 完全没有功能码 yaml，最外层兜底（data 整段裸露）")
    print("=" * 78)
    engine = ProtocolEngine()
    engine.load_schemas(ROOT / "schemas")
    # 让 engine 自己造一条 AFN=0x99（没有 yaml）的合法报文
    raw = engine.build(
        protocol="gw3762",
        fields={"address": "3201000100", "afn": 0x99, "data": "DEADBEEF1234"},
    )
    print(f"input: {raw.hex(' ').upper()}")
    r = engine.parse(raw)
    print(r.format_byte_map())


if __name__ == "__main__":
    demo_a_variable_axdr()
    demo_b_lazy_partial()
    demo_c_external_unknown()
