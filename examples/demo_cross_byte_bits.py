"""Demo for cross-byte bit_fields.

Shows that a 2-byte data field can split into (bits 0-3) and (bits 4-15)
where the latter spans both bytes.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from protocol import ProtocolEngine


# ---------------------------------------------------------------------------
# A tiny custom protocol just for this demo. 5-byte frame:
#   STX(0xAA) | DEVICE_INFO(2 bytes) | CMD(1 byte) | ETX(0x55)
# DEVICE_INFO splits into:
#   bits 15-4 = device_id (12 bits, cross-byte)
#   bits 3-0  = revision  (4 bits, low nibble of second byte)
# ---------------------------------------------------------------------------

BASE_YAML = """
protocol:
  name: cross_byte_demo
  display_name: "Cross-byte bit_fields demo"

identifier:
  start_byte: 0xAA
  rules:
    - check: ends_with_byte
      value: 0x55

frames:
  base:
    fields:
      - { name: stx, type: marker, length: 1, default: "AA", role: marker }
      - name: device_info
        type: bytes
        length: 2
        default: "0000"
        description: "device_id(高 12 bit) + revision(低 4 bit)"
        bit_fields:
          - { name: device_id, bits: "15-4", description: "设备编号，横跨两字节" }
          - { name: revision,  bits: "3-0",  description: "硬件修订号，低 4 位" }
      - { name: cmd,  type: uint8,  length: 1, default: "00", role: service }
      - { name: payload, type: bytes, length: variable, default: "", role: payload }
      - { name: etx,  type: marker, length: 1, default: "55", role: marker }
"""


def main():
    # 1) 用临时 YAML 注册协议
    with tempfile.TemporaryDirectory() as td:
        proto_dir = Path(td) / "cross_byte_demo"
        proto_dir.mkdir()
        (proto_dir / "base.yaml").write_text(BASE_YAML, encoding="utf-8")

        engine = ProtocolEngine()
        engine.load_schemas(td)

        # 2) 组帧：device_id=0x123, revision=0x4 → device_info 应该是 0x1234 (wire: 12 34)
        frame = engine.build(
            protocol="cross_byte_demo",
            fields={
                "device_info": {"device_id": 0x123, "revision": 0x4},
                "cmd": 0x07,
            },
        )
        print(f"build with device_id=0x123 revision=0x4:")
        print(f"  → {frame.hex(' ').upper()}")
        # 预期：AA 12 34 07 55

        # 3) 解析回来
        r = engine.parse(frame)
        print()
        print(r.format_byte_map())
        print()

        # 4) 直接读位域子值
        info = r["device_info"]
        print(f"device_info.raw      = {info.raw_bytes.hex(' ').upper()}")
        print(f"device_info.value    = 0x{info.value if isinstance(info.value, int) else int.from_bytes(info.value, 'big'):04X}")
        print(f"device_info.bit_fields = {info.bit_fields}")
        print()

        # 5) 反向验证：解析外部已知报文
        external = "AA AB CD 02 55"   # device_info = 0xABCD → device_id=0xABC, revision=0xD
        r2 = engine.parse(external)
        info2 = r2["device_info"]
        print(f"parse external {external!r}:")
        print(f"  device_info.bit_fields = {info2.bit_fields}")
        assert info2.bit_fields["device_id"] == 0xABC
        assert info2.bit_fields["revision"] == 0xD
        print("  断言通过：device_id=0xABC, revision=0xD")


if __name__ == "__main__":
    main()
