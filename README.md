# protocol — 通用协议解析器/组帧器

一个 **YAML 驱动**、**协议无关**的报文解析与组帧框架。
**写 YAML 即支持新协议**，不需要改一行 Python 代码。

> 作者背景为电力行业，故选取 DL/T 698.45（面向对象、最复杂）与 Q/GDW 376.2 作为内置示例协议。**框架本身与电力无关**——任何带有"起止符 + 长度 + 控制 + 地址 + 数据 + 校验"特征的二进制协议都能用。

---

## ✨ 核心能力

| 能力 | 说明 |
|---|---|
| **报文解析** | 字节流 → 结构化字段树，每个字节明确归属、含义、位域分解 |
| **报文组帧** | 默认值 + 用户覆盖 → 完整字节流，长度/CRC/校验**自动计算** |
| **一码多帧** | 同一个功能码下声明 **4 种帧格式**：组查询、查询响应、组设置、设置响应（按需启用） |
| **多协议共存** | 同时加载多份协议 YAML，**根据首字节及结构特征自动识别** |
| **位域支持** | 任意字段可按位拆解，**支持跨字节位域**（如 12bit 设备号横跨两字节） |
| **变长字段** | 三种变长模式：长度域反推、A-XDR 自描述、自动占满剩余字节 |
| **偷懒解析** | 数据域可只解头几字段，剩余以 `tail` 裸字节返回 |
| **跨语言调用** | 内置 CLI 工具 + HTTP 服务示例，C# / Java / Go / Node.js 都能直接对接 |

---

## 🎯 设计哲学：一个功能码 4 种帧

很多协议（特别是请求-响应模式的协议）**同一个功能码在不同方向 / 不同语义下报文格式不同**。本框架把这种"一码多形态"的常见模式抽象为 4 种帧变体：

| 变体名 | 中文 | 典型场景 |
|---|---|---|
| `get_request` | 组查询帧 | 主站向从站请求数据 |
| `get_response` | 查询结果响应帧 / 主动上报帧 | 从站返回数据，或主动推送 |
| `set_request` | 组设置帧 | 主站向从站写参数 |
| `set_response` | 设置结果响应帧 | 从站返回写入结果 |

一个功能码 YAML 文件**最多声明 4 种变体**——用得到的写出来，用不到的写 `enabled: false` 或直接省略。框架在解析时**根据控制位（DIR/PRM 等）自动选用**对应的变体。

```yaml
# 例：完整 4 变体的功能码
service:
  protocol: gw3762
  service_code: 0x04

variant_selector:
  rules:
    - { when: { dir: 0, prm: 1 }, variant: set_request }
    - { when: { dir: 1, prm: 0 }, variant: set_response }

frames:
  set_request:   { fields: [...] }
  set_response:  { fields: [...] }
  get_request:   { fields: [...] }
  get_response:  { fields: [...] }
```

---

## 🚀 快速开始

```bash
pip install pyyaml
python examples/demo.py
```

### 解析

```python
from protocol import ProtocolEngine

engine = ProtocolEngine().load_schemas("schemas/")

# 自动识别 + 解析
result = engine.parse("68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16")

print(result.format_byte_map())     # 字节归属表（最直观）
print(result["control"].bit_fields) # {'dir': 0, 'prm': 1, 'function': 11, ...}
print(result["apdu.da"].raw_bytes)  # b'\x01\x01'
```

输出（**每个字节的归属和含义一目了然**）：

```
offset  len  bytes              field         value / meaning
0       1    68                 start1        起始符
1-2     2    0C 00              length1       帧长 = 12
3-4     2    0C 00              length2       帧长副本
5       1    68                 start2        第二起始符
6       1    4B                 control       {dir=0, prm=1, function=11}
7-11    5    32 01 00 01 00     address       终端地址
12      1    0C                 afn           功能码 0x0C
13      1    60                 seq           {fir=1, fin=1, ...}
14-15   2    01 01              apdu.da       {da1=1, da2=1}
16-17   2    01 00              apdu.dt       {dt1=1, dt2=0}
18      1    EE                 cs            累加和校验
19      1    16                 end           结束符
```

### 组帧

```python
# 默认值 + 覆盖字段；长度、CRC、累加和全部自动算
frame = engine.build(
    protocol="gw3762",
    function_code=0x04,
    frame_type="set_request",
    fields={
        "address": "3201000100",
        "data.master_ip": "C0A80164",     # dot-path 指定数据域内部字段
        "data.master_port": "0A1A",
    },
)
# → b'\x68\x12\x00\x12\x00\x68\x4B\x32\x01\x00\x01\x00\x04\x60\x00...'
```

### 自动识别

```python
engine.identify(frame_bytes)    # 'gw3762' / 'dlt698' / 自定义协议名 / None
```

---

## 📋 添加新协议（YAML 驱动）

支持新协议只需在 `schemas/<你的协议>/` 下写 YAML——**不需要任何 Python 代码改动**。

```
schemas/
└── 你的协议/
    ├── base.yaml              # 外层骨架（起止符、长度、控制、数据、校验）
    ├── func_01.yaml           # 功能码 1 的 4 种帧（按需）
    ├── func_02.yaml           # 功能码 2 的 4 种帧
    └── ...
```

**最小 base.yaml 模板**：

```yaml
protocol:
  name: myproto
identifier:
  start_byte: 0xAB
  rules:
    - { check: ends_with_byte, value: 0xCD }
frames:
  base:
    fields:
      - { name: stx,    type: marker, length: 1, default: "AB", role: marker }
      - { name: cmd,    type: uint8,  length: 1, role: service }
      - name: length
        type: uint8
        length: 1
        role: length
        auto: true
        algorithm: length_le
        range: { start: data, end: data }
      - { name: data,   type: bytes,  length: variable, default: "", role: payload }
      - name: cs
        type: uint8
        length: 1
        role: checksum
        auto: true
        algorithm: sum_mod_256
        range: { start: cmd, end: data }
      - { name: etx,    type: marker, length: 1, default: "CD", role: marker }
```

详细的字段语法、可选属性、最佳实践，见 [`docs/YAML_GUIDE.md`](docs/YAML_GUIDE.md)。

如果你的协议用了**非内置算法**（如 Modbus CRC、CRC-32、XOR），或**非内置字段类型**（TLV、私有结构），通过简单的 Python 注册即可扩展（一次注册，所有 YAML 可用）：

```python
engine.algos.register("crc16_modbus", my_crc_function)
engine.codecs.register(MyCustomCodec())
```

详见 [`docs/PYTHON_USAGE.md`](docs/PYTHON_USAGE.md) §6-§8。

---

## 🧪 内置示例协议

`schemas/` 目录下提供两个完整可工作的协议样例，**主要用作框架功能演示和回归测试**：

| 协议 | 说明 | 用作演示的能力 |
|---|---|---|
| **DL/T 698.45** | 面向对象电表通信协议 | DLMS A-XDR 编码、OAD/OMD 描述符、HCS+FCS 双 CRC、14 位长度域、变长 SA |
| **Q/GDW 376.2** | 主站-采集终端协议 | 双长度域镜像、累加和校验、AFN 路由、4 种帧变体 |

选择 698 作为最复杂的测试基准——若框架能搞定它，简单协议自然不在话下。

---

## 🌐 跨语言调用

### 命令行（任何能调用进程的语言都能用）

```bash
python -m protocol --schemas schemas identify --hex "68 0C 00 ..."
python -m protocol --schemas schemas bytemap  --hex "68 0C 00 ..."
python -m protocol --schemas schemas build    --protocol gw3762 \
    --function-code 0x0C --frame-type get_request \
    --fields '{"data.da":"0101"}'
```

所有输出都是 JSON。

### HTTP 服务（C# / Java / Go 推荐）

```bash
python examples/http_server.py --port 8765 --schemas schemas/
```

```bash
curl -X POST http://127.0.0.1:8765/bytemap \
    -H "Content-Type: application/json" \
    -d '{"hex":"68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16"}'
```

C# 完整客户端封装见 [`docs/CSHARP_USAGE.md`](docs/CSHARP_USAGE.md)（含 `IProtocolClient` 接口 + HTTP 与 CLI 两种实现）。

---

## 🏗️ 架构

```
              ┌──────────────────┐
              │  ProtocolEngine  │  ← 公开门面
              └────────┬─────────┘
        ┌──────────────┼──────────────┐
   ┌────▼────┐    ┌────▼────┐    ┌────▼─────┐
   │ Parser  │    │ Builder │    │Identifier│
   └────┬────┘    └────┬────┘    └────┬─────┘
        └──────────────┼──────────────┘
                       │
   ┌───────────┬───────┴───────┬───────────┐
   │           │               │           │
┌──▼──┐   ┌────▼───┐    ┌──────▼────┐  ┌───▼─────┐
│Codec│   │  Algo  │    │  Schema   │  │  Util   │
│Reg. │   │  Reg.  │    │  Registry │  │         │
└──┬──┘   └────┬───┘    └──────┬────┘  └─────────┘
   │           │               │
 内置：     内置：           YAML
 uint/    sum_mod_256     dlt698/
 bytes/   crc16_x25       gw3762/
 bcd/     length_le       my_proto/
 ascii/   length_bits14   ...
 DLMS     copy_field
 ────     ────            ────
 可扩展    可扩展           动态加载
```

| 模块 | 职责 |
|---|---|
| `engine` | 公开门面，对外只暴露这一个类 |
| `schema/` | YAML → 类型化 Schema 对象 |
| `identify/` | 协议自动识别（首字节 + 启发式规则） |
| `codec/` | 字段编解码（uint/bytes/bcd/ascii/DLMS 等） |
| `algo/` | 动态字段算法（长度、校验、镜像） |
| `parser/` | 报文解析主流程 |
| `builder/` | 组帧主流程（两阶段 + auto 字段填充） |
| `result.py` | `ParseResult` / `FieldNode` 输出模型 |

---

## 📚 文档导航

| 你的角色 | 读这个 |
|---|---|
| **协议工程师**（只需写 YAML） | [`docs/YAML_GUIDE.md`](docs/YAML_GUIDE.md) |
| **Python 开发**（集成 / 二开） | [`docs/PYTHON_USAGE.md`](docs/PYTHON_USAGE.md) |
| **C# / 其他语言开发** | [`docs/CSHARP_USAGE.md`](docs/CSHARP_USAGE.md) |

---

## 📦 项目结构

```
protocol/
├── src/protocol/
│   ├── engine.py            # 公开门面 ProtocolEngine
│   ├── __main__.py          # CLI 入口（python -m protocol ...）
│   ├── result.py            # ParseResult / FieldNode
│   ├── errors.py            # 异常类型
│   ├── schema/              # YAML → Schema 对象
│   ├── identify/            # 协议自动识别
│   ├── codec/               # 字段编解码（含 DLMS A-XDR）
│   ├── algo/                # 动态字段算法
│   ├── parser/              # 解析主流程
│   ├── builder/             # 组帧主流程
│   └── util/                # hex/bitops/dotpath 工具
│
├── schemas/                 # 协议 YAML（示例）
│   ├── dlt698/              # 698 协议样例
│   └── gw3762/              # 376.2 协议样例
│
├── examples/
│   ├── demo.py                       # 5 个基础示例
│   ├── demo_variable_and_lazy.py     # 变长 + 偷懒解析
│   ├── demo_cross_byte_bits.py       # 跨字节位域
│   └── http_server.py                # HTTP sidecar 服务
│
├── tests/                   # 端到端测试
├── docs/                    # 三份指南
├── pyproject.toml
└── README.md                # 你正在看的这份
```

---

## ⚙️ 内置算法与类型

### 算法（auto 字段用）

| 名称 | 输出 | 典型用途 |
|---|---|---|
| `sum_mod_256` | 1 B | 累加和校验 |
| `crc16_x25` | 2 B LE | CRC16/X.25（FCS-16） |
| `length_le` | N B LE | 普通小端长度 |
| `length_bits14_le` | 2 B LE | 14 位长度 + 2 位保留 |
| `copy_field` | 同源 | 镜像另一字段 |

非内置算法？一行注册：`engine.algos.register("xxx", fn)`

### 字段类型（type）

| 类别 | 类型 |
|---|---|
| 整数 | `uint8` / `uint16_le` / `uint16_be` / `uint24_le` / `uint24_be` / `uint32_le` / `uint32_be` |
| 字节 | `bytes` / `marker` / `ascii` |
| 电力 BCD | `bcd` / `bcd_le` |
| DLMS / 698 | `axdr_oi` / `axdr_oad` / `axdr_omd` / `axdr_date_time_s` / `axdr_typed_data` |

非内置类型？继承 `Codec` 写一个 codec 类后 `engine.codecs.register(MyCodec())`

---

## 📝 限制与扩展点

- **DLMS A-XDR**：v1 实现了 OAD/OMD/OI、date_time_s、`axdr_typed_data`（基础原语）。完整的 ARRAY/STRUCTURE/CHOICE 递归复合类型框架已预留 `children:` 字段，但 codec 实现可作为后续扩展
- **变长字段限制**：一个 frame 内**只能有一个**"占剩余"的变长 bytes 字段（自描述类型如 `axdr_typed_data` 不受限）
- **多协议优先级**：当多个协议同时匹配，可通过 `engine.identifier.priority = [...]` 配置
- **识别规则可插件化**：当前 4 种内置 check（`ends_with_byte` / `byte_at_offset` / `length_field_layout` / `total_length_matches_buffer`）若不够用，可在 `identify/identifier.py` 中扩展

---

## 📄 License

MIT
