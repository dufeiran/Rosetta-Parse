# Python 集成 & 二次开发指南

本文档面向 **Python 开发者**，介绍如何把本项目集成到你的代码中，以及如何通过注册自定义 codec / algorithm / identifier 来扩展支持新协议。

> 如果你**只想用工具解析报文、不打算改代码**，看 [`YAML_GUIDE.md`](YAML_GUIDE.md) 写好 YAML 即可。
> 如果你想用 **C# / Java / 其他语言**调用，看 [`CSHARP_USAGE.md`](CSHARP_USAGE.md)。

---

## 目录

1. [安装](#1-安装)
2. [快速开始](#2-快速开始)
3. [API 完整参考](#3-api-完整参考)
4. [ParseResult / FieldNode 数据模型](#4-parseresult--fieldnode-数据模型)
5. [异常处理](#5-异常处理)
6. [二次开发：注册自定义算法](#6-二次开发注册自定义算法)
7. [二次开发：注册自定义 Codec](#7-二次开发注册自定义-codec)
8. [二次开发：注册自定义识别规则](#8-二次开发注册自定义识别规则)
9. [运行时动态注册 YAML](#9-运行时动态注册-yaml)
10. [典型集成场景](#10-典型集成场景)

---

## 1. 安装

### 1.1 直接源码使用

把 `src/protocol` 拷到你的项目里，或者把 `src/` 加到 `PYTHONPATH`：

```bash
export PYTHONPATH=/path/to/protocol/src:$PYTHONPATH
```

Python 代码里直接 `import protocol`。

### 1.2 用 pip 本地安装（推荐）

项目根目录已经有 `pyproject.toml`：

```bash
cd /path/to/protocol
pip install -e .
```

`-e` 表示"可编辑安装"——后续改源码不用重装。

### 1.3 依赖

唯一运行时依赖是 `PyYAML >= 6.0`。Python ≥ 3.9。

---

## 2. 快速开始

```python
from protocol import ProtocolEngine

# 创建引擎并加载所有 YAML
engine = ProtocolEngine()
engine.load_schemas("schemas/")    # 路径下递归扫描所有 *.yaml

# --- 解析 ---
result = engine.parse("68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16")
print(result.format())              # 树形人类可读输出
print(result.format_byte_map())     # 字节归属表

# 程序读取具体字段
print(result["afn"].value)                  # 12
print(result["control"].bit_fields["prm"])  # 1
print(result["apdu.da"].raw_bytes.hex())    # "0101"

# --- 组帧 ---
frame = engine.build(
    protocol="gw3762",
    function_code=0x0C,
    frame_type="get_request",
    fields={
        "address": "3201000100",
        "data.da": "0101",
        "data.dt": "0100",
    },
)
print(frame.hex(" "))    # 长度、CS 自动算好

# --- 协议识别 ---
print(engine.identify("68 19 00 43 ..."))    # "dlt698" / "gw3762" / None
```

---

## 3. API 完整参考

### 3.1 `ProtocolEngine` 类

公开门面，所有功能从这里访问。

```python
class ProtocolEngine:
    def __init__(self) -> None
```

创建引擎实例。**线程安全说明**：内部维护的 schema/codec/algo 注册表在加载阶段是可变的；加载完成后只读，可多线程共享。**不要在并发解析的同时再调 `load_schemas`**。

---

#### `load_schemas(path) -> ProtocolEngine`

```python
def load_schemas(self, path: str | Path) -> ProtocolEngine
```

递归扫描指定目录下所有 `*.yaml` / `*.yml` 并注册。
- 自动区分 base.yaml（包含 `protocol:` + `frames.base:`）和功能码 yaml（包含 `service:`）
- **返回 self**，可链式调用
- 重复加载同一个协议会抛 `SchemaError`

```python
engine = ProtocolEngine().load_schemas("schemas/")
```

---

#### `identify(data) -> str | None`

```python
def identify(self, data: bytes | str) -> str | None
```

按已注册的所有协议的 `identifier` 规则匹配，返回协议名。
- `data` 可以是 `bytes`、`bytearray`、`memoryview`，或者 hex 字符串（容忍空格和大小写）
- 没匹配返回 `None`
- 多协议都匹配时按内置优先级 `["dlt698", "gw3762"]` 选

```python
engine.identify("68 19 00 ...")     # "dlt698"
engine.identify(b"\x68\x19\x00...")  # 等价
```

---

#### `parse(data, *, protocol=None, strict=True) -> ParseResult`

```python
def parse(self,
          data: bytes | str,
          *,
          protocol: str | None = None,
          strict: bool = True) -> ParseResult
```

解析一条报文。
- `protocol`：传入则跳过自动识别；不传则自动识别
- `strict`：
  - `True`（默认）—— 长度/CRC 校验失败抛 `ParseError`
  - `False` —— 返回 `ParseResult`，但 `valid=False`、`errors=[...]`

```python
# 严格模式
try:
    r = engine.parse(data)
except ParseError as e:
    print(f"bad frame: {e}")

# 宽松模式
r = engine.parse(data, strict=False)
if not r.valid:
    print(f"warnings: {r.errors}")
```

---

#### `build(...) -> bytes`

```python
def build(self,
          protocol: str,
          *,
          function_code: int | None = None,
          frame_type: str | None = None,
          fields: dict | None = None) -> bytes
```

组帧。
- `protocol`：必填，指定协议名
- `function_code`：填写则按功能码 yaml 组装数据域；不填则只组外层（用户须自己提供 `data` / `apdu` 裸字节）
- `frame_type`：填了 `function_code` 时必填，取值 `"get_request" / "get_response" / "set_request" / "set_response"`
- `fields`：字典，支持 **dot-path**（`"data.master_ip": "C0A80164"`）和**嵌套 dict**两种风格

```python
# 完整组帧
engine.build(
    protocol="gw3762",
    function_code=0x04,
    frame_type="set_request",
    fields={
        "address": "3201000100",
        "control": {"dir": 0, "prm": 1, "function": 11},   # 按位域赋值
        "data.master_ip": "C0A80164",
        "data.master_port": "0A1A",
    },
)

# 只组外层（不需要功能码 yaml）
engine.build(
    protocol="gw3762",
    fields={"afn": 0x99, "data": "DEAD BEEF"},
)
```

---

#### `list_protocols() -> list[str]`

返回已注册的所有协议名。

#### `list_services(protocol) -> list[int]`

返回某协议下所有已注册的功能码。

```python
engine.list_protocols()                # ["dlt698", "gw3762"]
engine.list_services("gw3762")         # [4, 12]
```

---

### 3.2 引擎内部组件

普通用户不直接用，但**做扩展时会用到**：

| 属性 | 类型 | 用途 |
|---|---|---|
| `engine.schemas` | `SchemaRegistry` | YAML 注册表 |
| `engine.codecs`  | `CodecRegistry`  | 字段类型注册表 |
| `engine.algos`   | `AlgoRegistry`   | 算法注册表 |
| `engine.identifier` | `Identifier`  | 识别器（含优先级） |

详见 [§6](#6-二次开发注册自定义算法) ~ [§8](#8-二次开发注册自定义识别规则)。

---

## 4. ParseResult / FieldNode 数据模型

### 4.1 `ParseResult`

```python
@dataclass
class ParseResult:
    protocol: str                    # "dlt698" / "gw3762" / ...
    frame_type: str                  # "base" / "get_request" / ...
    function_code: int | None        # 内层 ParseResult 上才有值
    valid: bool                      # 全部校验是否通过
    errors: list[str]                # 失败原因（如 "cs mismatch: ..."）
    fields: dict[str, FieldNode]     # 字段树（按声明顺序）
    apdu: ParseResult | None         # 内层解析结果（如果功能码 yaml 匹配）
    raw: bytes                       # 原始报文
    outer_offset: int                # apdu 时这个值表示其在外层帧的起始偏移
```

#### 常用方法

```python
result["afn"]                        # 返回 FieldNode；找不到抛 KeyError
result["apdu.da"]                    # 嵌套字段用 dot-path
result.get("apdu.unknown", None)     # 安全访问

result.format()                      # 树形人类可读
result.format_byte_map()             # 按字节归属表
result.to_dict()                     # JSON-friendly dict（含 raw 字节的 hex）
```

### 4.2 `FieldNode`

```python
@dataclass
class FieldNode:
    name: str
    value: Any                       # 解析后的 Python 值（int/bytes/str/dict/...）
    raw_bytes: bytes                 # 原始字节切片
    offset: int                      # 在所属帧中的字节偏移（相对外层时绝对，相对内层时由 outer_offset 翻译）
    length: int                      # == len(raw_bytes)
    bit_fields: dict[str, Any] | None    # 位域分解
    children: list[FieldNode] | None     # 复合 codec 的子字段（v1 暂未启用）
    description: str | None              # 来自 YAML 的 description
```

#### 字段值类型对照

| YAML `type` | `node.value` 的 Python 类型 |
|---|---|
| `uint8` / `uint16_le` / `uint16_be` ... | `int` |
| `bytes` / `marker` | `bytes` |
| `ascii` | `str` |
| `bcd` / `bcd_le` | `int`（对应的十进制数） |
| `axdr_oad` | `dict` `{"oi": int, "attr_idx": int, "attr_qualifier": int}` |
| `axdr_omd` | `dict` `{"oi": int, "method_idx": int, "method_qualifier": int}` |
| `axdr_oi` | `int` |
| `axdr_date_time_s` | `dict` `{"year":...,"month":...,...}` |
| `axdr_typed_data` | `dict` `{"tag": "...", "value": ...}` |

---

## 5. 异常处理

所有自定义异常都继承 `protocol.errors.ProtocolError`。

```python
from protocol.errors import (
    ProtocolError,     # 所有异常的基类
    SchemaError,       # YAML 写错了
    IdentifyError,     # 自动识别失败
    ParseError,        # 解析失败（含校验不通过）
    BuildError,        # 组帧失败
    CodecError,        # 字段编解码失败（底层异常）
)

try:
    result = engine.parse(data)
except IdentifyError:
    print("未知协议")
except ParseError as e:
    print(f"报文格式错误: {e}")
except ProtocolError as e:
    # 兜底
    print(f"其他错误: {e}")
```

---

## 6. 二次开发：注册自定义算法

**场景**：你的协议用了非内置算法（如 Modbus CRC、CRC-32、XOR）。

### 6.1 一个完整例子：Modbus CRC-16

```python
from protocol import ProtocolEngine

# 写一个 Modbus CRC-16 算法（poly=0xA001, init=0xFFFF, reflect IO）
def crc16_modbus(range_bytes: bytes, **kw) -> bytes:
    crc = 0xFFFF
    for byte in range_bytes:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc.to_bytes(2, "little")

engine = ProtocolEngine()

# 注册算法 —— 必须在 load_schemas 之前完成
engine.algos.register("crc16_modbus", crc16_modbus)

# YAML 现在可以用 algorithm: crc16_modbus
engine.load_schemas("schemas/")
```

YAML 这边写：

```yaml
- name: crc
  type: uint16_le
  length: 2
  default: "0000"
  role: checksum
  auto: true
  algorithm: crc16_modbus           # ← 你刚注册的名字
  range: { start: address, end: data }
```

### 6.2 算法函数签名

```python
def my_algo(range_bytes: bytes, **kw) -> bytes
```

- `range_bytes`：YAML 中 `range.start..range.end` 覆盖的字节
- `**kw`：YAML 中通过 `transform.*` 等额外参数传过来的 kwargs（一般不用）
- 必须返回 `bytes`，长度要和字段的 `length` 一致

### 6.3 内置算法名清单

|名字|用途|
|---|---|
| `sum_mod_256` | 累加和 |
| `crc16_x25` | CRC16/X.25（FCS-16） |
| `length_le` | 普通小端长度 |
| `length_bits14_le` | 14 位长度 + 2 位保留 |
| `copy_field` | 镜像另一字段 |

**不要覆盖内置名**——注册一个新名字即可。

---

## 7. 二次开发：注册自定义 Codec

**场景**：你的协议有特殊编码（变长地址、TLV、私有结构、ASN.1 等）。

### 7.1 一个完整例子：可变长地址（698 真实 SA）

698 实际 SA 是变长的：首字节 bit 3-0 是"地址长度-1"，后跟 N 字节逻辑地址 + 1 字节服务端口。下面写一个支持变长的 codec：

```python
from typing import Any, Tuple
from protocol.codec.base import Codec
from protocol.errors import CodecError
from protocol import ProtocolEngine

class Address698Codec(Codec):
    """698 变长 SA：1B 前缀 + N 字节地址 + 1B SA。N = (prefix & 0x0F) + 1"""
    name = "address_dlt698"
    self_delimiting = True       # 长度由数据自决，不需要外部 length 信号

    def encode(self, value, field_schema, ctx) -> bytes:
        # value 接受 dict 或 hex string
        if isinstance(value, str):
            return bytes.fromhex(value.replace(" ", ""))
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if isinstance(value, dict):
            addr_type = int(value.get("addr_type", 0)) & 0x03
            body = bytes.fromhex(str(value["body"]).replace(" ", ""))
            sa = int(value.get("sa", 0)) & 0xFF
            prefix = (addr_type << 6) | ((len(body) - 1) & 0x0F)
            return bytes([prefix]) + body + bytes([sa])
        raise CodecError(f"bad value for address_dlt698: {value!r}")

    def decode(self, buf: memoryview, field_schema, ctx) -> Tuple[Any, int]:
        if len(buf) < 2:
            raise CodecError("address_dlt698: too short")
        prefix = buf[0]
        body_len = (prefix & 0x0F) + 1
        total = 1 + body_len + 1
        if len(buf) < total:
            raise CodecError(f"address_dlt698: need {total} bytes")
        body = bytes(buf[1:1 + body_len])
        sa = buf[1 + body_len]
        return {
            "addr_type": (prefix >> 6) & 0x03,
            "addr_len": body_len,
            "body": body.hex().upper(),
            "sa": sa,
        }, total


engine = ProtocolEngine()
engine.codecs.register(Address698Codec())
engine.load_schemas("schemas/")
```

然后 YAML 里就能写：

```yaml
- name: address
  type: address_dlt698       # 你的 codec 名字
  length: variable
  default: "0500000000000100"
```

### 7.2 Codec 基类约定

```python
from protocol.codec.base import Codec

class MyCodec(Codec):
    name = "my_type"                     # 必须，全局唯一
    self_delimiting = False              # True = 长度由数据自决；False = 由 schema length 决定

    def encode(self, value, field_schema: dict, ctx) -> bytes:
        """value → bytes。field_schema 是当前字段的 YAML dict。"""

    def decode(self, buf: memoryview, field_schema: dict, ctx) -> tuple[Any, int]:
        """buf 是从字段起点开始的视图。返回 (解码后的值, 消耗了几字节)。"""
```

#### `field_schema` 字典里有什么

来自 YAML 的字段定义。常用键：

| 键 | 含义 |
|---|---|
| `name` | 字段名 |
| `type` | codec 名 |
| `length` | 长度（int 或 `"variable"`） |
| `default` | 默认值 |
| 其他 YAML 里写的自定义键 | 直接透传，如 `bcd_digits`、自定义参数 |

#### `self_delimiting` 的作用

- `True` —— 解析时 parser 不会预先切片，把整个剩余 buffer 给你，由你决定吃几个字节
- `False` —— parser 用 `length` 给定的字节数切好后传进来

变长且自描述的类型（A-XDR、TLV）应当设 `True`。

### 7.3 提示

- 不要 throw 普通 `Exception` —— 用 `CodecError`，框架会包装好上下文
- 性能敏感场景下 `buf` 用 `memoryview` 避免拷贝
- 测试时建议先单测 codec 本身（直接调 encode/decode），再集成进 engine

---

## 8. 二次开发：注册自定义识别规则

**场景**：内置的 4 种规则（`ends_with_byte` / `byte_at_offset` / `length_field_layout` / `total_length_matches_buffer`）不够用。

### 8.1 添加新规则

识别规则现在硬编码在 `src/protocol/identify/identifier.py` 的 `_eval_rule` 函数里。**当前版本规则不可插件化**——要加新规则，需要：

1. 在 `_eval_rule` 里加 `elif check == "your_rule": ...`
2. 在 YAML 用 `check: your_rule` 引用

如果你的项目频繁需要新规则，可以提 PR 把它做成 register API。

### 8.2 设置识别优先级

多个协议都匹配时按优先级选。可以改：

```python
engine.identifier.priority = ["my_proto", "dlt698", "gw3762"]
```

---

## 9. 运行时动态注册 YAML

**场景**：YAML 不在文件里、动态生成、来自数据库等。

### 9.1 直接传入 dict

```python
from protocol.schema.loader import parse_protocol_base, parse_service

doc = yaml.safe_load(yaml_text)
if "protocol" in doc:
    base = parse_protocol_base(doc, source="<dynamic>")
    engine.schemas.add_protocol_base(base)
elif "service" in doc:
    svc = parse_service(doc, source="<dynamic>")
    engine.schemas.add_service(svc)
```

### 9.2 多个 YAML 字符串

```python
import yaml

for yaml_text in [base_yaml_text, svc1_yaml_text, svc2_yaml_text]:
    doc = yaml.safe_load(yaml_text)
    # ... 同上 ...
```

### 9.3 重新加载（热更新）

```python
# 简单粗暴：重建 engine
engine = ProtocolEngine()
engine.load_schemas("schemas/")
```

> 框架未提供"卸载某个协议"的 API；要切换协议集，重建 engine 是最干净的做法。

---

## 10. 典型集成场景

### 10.1 嵌入到已有 Python 服务

```python
class ProtocolService:
    def __init__(self, schemas_path: str):
        self._engine = ProtocolEngine().load_schemas(schemas_path)
    
    def parse(self, hex_str: str) -> dict:
        try:
            return self._engine.parse(hex_str).to_dict()
        except ProtocolError as e:
            return {"error": str(e)}
    
    def build(self, **kwargs) -> str:
        return self._engine.build(**kwargs).hex(" ").upper()
```

### 10.2 批量解析（性能优化）

```python
engine = ProtocolEngine().load_schemas("schemas/")    # 加载一次

for hex_str in big_list_of_frames:
    try:
        result = engine.parse(hex_str)
        # 处理 result
    except ProtocolError as e:
        log.warning(f"skipped frame: {e}")
```

> 引擎实例**复用**即可，不要每条报文都新建一个。`load_schemas` 是耗时操作。

### 10.3 命令行 / 子进程方式（适合脚本 / shell）

直接调内置 CLI：

```bash
# 自动识别
python -m protocol --schemas schemas identify --hex "68 0C 00 ..."

# 解析并取字节归属表
python -m protocol --schemas schemas bytemap --hex "68 0C 00 ..."

# 组帧
python -m protocol --schemas schemas build \
    --protocol gw3762 \
    --function-code 0x0C \
    --frame-type get_request \
    --fields '{"data.da":"0101"}'

# 列出已注册的协议和功能码
python -m protocol --schemas schemas list
```

所有输出都是 JSON。

### 10.4 跨语言场景（HTTP 服务）

启动 sidecar 服务：

```bash
python examples/http_server.py --host 0.0.0.0 --port 8765 --schemas schemas/
```

其他语言（Go / C# / Java / Node.js）通过 HTTP + JSON 调用。完整 C# 例子见 [`CSHARP_USAGE.md`](CSHARP_USAGE.md)。

### 10.5 单元测试中使用

```python
import pytest
from protocol import ProtocolEngine

@pytest.fixture(scope="session")
def engine():
    return ProtocolEngine().load_schemas("schemas/")

def test_parse_known_frame(engine):
    r = engine.parse("68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16")
    assert r.valid
    assert r["afn"].value == 0x0C
    assert r.apdu is not None
```

使用 `scope="session"` 让所有测试共享一个 engine 实例，避免重复加载。

---

## 附录 A. 项目目录结构（开发者视角）

```
protocol/
├── src/protocol/
│   ├── __init__.py        # 公开 API: ProtocolEngine / ParseResult / FieldNode / errors
│   ├── __main__.py        # CLI 入口（python -m protocol ...）
│   ├── engine.py          # ProtocolEngine 实现
│   ├── result.py          # ParseResult / FieldNode
│   ├── errors.py          # 异常类型
│   ├── context.py         # ParseContext / BuildContext（codec/algo 用）
│   ├── schema/            # YAML 加载与模型
│   ├── identify/          # 协议识别
│   ├── codec/             # 字段编解码（含 DLMS A-XDR）
│   ├── algo/              # 算法（CRC / 累加和 / 长度 / copy_field）
│   ├── parser/            # 报文解析主流程
│   ├── builder/           # 组帧主流程（两阶段 + auto 字段填充）
│   └── util/              # 工具函数
├── schemas/               # 默认 YAML 库（698 + 376.2 示例）
├── examples/              # 可运行示例（demo.py / http_server.py 等）
├── tests/                 # 测试
├── docs/                  # 文档
│   ├── YAML_GUIDE.md      # 协议工程师看这个
│   ├── PYTHON_USAGE.md    # ← 你正在看
│   └── CSHARP_USAGE.md    # C# 集成
└── pyproject.toml
```

## 附录 B. 扩展点速查

| 想做什么 | 在哪里改 |
|---|---|
| 新增协议 | 写 YAML（`schemas/`） |
| 新校验算法（CRC32 / XOR / 自定义） | `engine.algos.register(name, fn)` |
| 新字段类型（TLV / 变长地址 / 私有结构） | 继承 `Codec`，`engine.codecs.register(MyCodec())` |
| 新识别规则 | 改 `identify/identifier.py:_eval_rule` |
| 调整协议优先级 | `engine.identifier.priority = [...]` |
| 改输出格式 | 子类化 `ParseResult` 或自己写 formatter |
| 加运行时 hook（日志/监控） | 包装 `ProtocolEngine` 的 parse/build 方法 |
