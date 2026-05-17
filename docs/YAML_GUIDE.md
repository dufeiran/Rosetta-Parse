# YAML 编写完全指南

> **本文档面向所有需要为这套协议解析器编写 YAML 文件的人员，包括不会编程的协议工程师。**
> 读完这份文档，你只需要一份协议规约文档，就能写出可用的 YAML，用工具解析出实际报文每个字节的含义。

---

## 目录

1. [YAML 是什么 / 怎么读](#1-yaml-是什么--怎么读)
2. [总体设计：两类 YAML 文件](#2-总体设计两类-yaml-文件)
3. [`base.yaml`：协议外层骨架](#3-baseyaml协议外层骨架)
4. [功能码 YAML：数据域细节](#4-功能码-yaml数据域细节)
5. [字段（field）属性详解](#5-字段field属性详解)
6. [字段类型（type）速查表](#6-字段类型type速查表)
7. [内置算法（algorithm）速查表](#7-内置算法algorithm速查表)
8. [位域（bit_fields）专题](#8-位域bit_fields专题)
9. [变长字段（length: variable）专题](#9-变长字段length-variable专题)
10. [从协议文档到 YAML 的完整推导](#10-从协议文档到-yaml-的完整推导)
11. [常用模式速查](#11-常用模式速查)
12. [常见错误与排查](#12-常见错误与排查)
13. [完整示例参考](#13-完整示例参考)

---

## 1. YAML 是什么 / 怎么读

YAML 是一种"用缩进表达层级"的文本格式。文件用记事本就能打开和编辑。**你不需要会编程**——只需要记住以下 5 条规则即可。

### 1.1 缩进表示层级

**用空格缩进**（不要用 Tab）。**同一层级要对齐**。

```yaml
protocol:               # 顶层
  name: dlt698          # protocol 的子项，缩进 2 格
  display_name: "698"   # 同样缩进 2 格 → 跟 name 同一层级
```

`protocol` 下面有 `name` 和 `display_name`，这两个是它的属性。缩进多少格不限（通常 2 格），**但同一层级的项必须缩进相同**。

### 1.2 键值对：`键: 值`

冒号后面要有**一个空格**：

```yaml
name: dlt698          # ✅ 正确
name:dlt698           # ❌ 冒号后没空格，会报错
```

### 1.3 列表：用 `-` 开头

需要写多个同类的项时，每项前加 `- `（短横线 + 空格）：

```yaml
fields:
  - name: start
    type: marker
  - name: length
    type: uint16_le
```

上面 `fields` 是一个列表，里面有两个元素。每个元素是一个 dict（有 `name` 和 `type`）。

### 1.4 注释：用 `#`

`#` 后面到行尾都是注释，被工具忽略，**用来给同事看**。

```yaml
- name: cs
  type: uint8           # 校验和，1 字节
  default: "00"         # 默认值 0
```

### 1.5 引号和数据类型

| 你想写的值 | 怎么写 |
|---|---|
| 数字 `12` | `12`（不加引号） |
| 十六进制 `0x12` | `0x12`（不加引号）或 `"12"`（字节序列时） |
| 字符串 `hello` | `hello` 或 `"hello"` 或 `'hello'` |
| 多字节十六进制 `68 19 00` | `"68 19 00"`（**用引号包起来**，空格可以保留） |
| 包含特殊字符 `: # @` | 一律加引号 |

> **特别提醒**：字节序列必须用**引号包起来**当字符串处理，避免被 YAML 误解为别的东西。
>
> ```yaml
> default: "68"         # ✅ 表示 1 字节的 0x68
> default: 68           # ⚠️ YAML 会理解为十进制整数 68，等同 0x44
> ```

### 1.6 行内简写（节省篇幅）

很短的列表/字典可以写在一行里，用 `{}` 或 `[]` 包起来，元素之间用逗号：

```yaml
# 多行写法
- name: cs
  type: uint8
  length: 1
  default: "00"

# 等价的单行写法
- { name: cs, type: uint8, length: 1, default: "00" }
```

**全文档都允许混用**。复杂字段建议多行写，简单字段单行写省空间。

---

## 2. 总体设计：两类 YAML 文件

工具用**两层**来描述一个协议：

```
                        ┌──────────────────────────────────┐
                        │  schemas/                        │
                        │  ├── 你的协议名/                 │
                        │  │   ├── base.yaml         ◀───  │ ① 外层骨架（必须有）
                        │  │   ├── func_01_xxx.yaml ◀───  │ ② 功能码细节（可选，按需写）
                        │  │   ├── func_02_xxx.yaml       │
                        │  │   └── func_xx_xxx.yaml       │
                        │  └── ...                         │
                        └──────────────────────────────────┘
```

### 2.1 `base.yaml`（每个协议有且只有一份）

描述协议的**外层骨架**：起始符、长度域、控制域、地址、数据域占位、校验、结束符 ——这些**不管什么功能码都一样**的部分。

**它的职责**：
- 让工具能从一堆字节里**识别**出"这是 698 协议还是 376.2 协议"
- 切分出每个外层字段的边界
- 自动校验长度和 CRC
- 取出**数据域**（payload）这块裸字节交给"功能码 YAML"继续解

### 2.2 功能码 YAML（一个功能码一份，可选）

描述**数据域内部**怎么进一步拆分。比如同一个协议下：
- 功能码 0x05 的数据域是 `OAD(4) + 时间标签(1)`
- 功能码 0x07 的数据域是 `OAD(4) + 数据(变长)`

**它的职责**：
- 把数据域按功能码细分
- 区分 4 种帧：组查询、查询响应、组设置、设置响应（不全用也行）
- 解出每个内部字段的字节归属和位域

### 2.3 解析时怎么联动

工具收到一条报文后的处理流程：

```
报文字节
  │
  ├─ 用每个 base.yaml 的 identifier 规则试一遍 → 确定是哪个协议
  │
  ├─ 用该协议的 base.yaml 解外层 → 拿到 afn / 服务码 / 数据域裸字节
  │
  ├─ 查找该协议下 service_code 匹配的功能码 yaml
  │   ├─ 找到 → 按"4 种帧变体"之一继续解数据域
  │   └─ 找不到 → 数据域以裸字节形式返回（兜底）
  │
  └─ 输出每个字段的偏移、字节、值、含义
```

**结论：写 YAML 时你只需要做两件事**：
1. 给每个协议写**一份** `base.yaml`
2. 给关心的功能码各写一份 yaml（不关心的就不写，工具会兜底）

---

## 3. `base.yaml`：协议外层骨架

### 3.1 文件位置

```
schemas/<协议名>/base.yaml
```

例：`schemas/dlt698/base.yaml`、`schemas/myproto/base.yaml`

### 3.2 必须有的 3 个顶层块

```yaml
protocol:    # 块 ①：协议元信息
  name: ...

identifier:  # 块 ②：怎么从字节里认出这是本协议
  ...

frames:      # 块 ③：帧字段定义
  base:
    fields:
      - ...
```

下面逐个讲。

### 3.3 块 ① `protocol`（协议元信息）

```yaml
protocol:
  name: dlt698                          # 协议内部名（英文/数字/下划线），全局唯一
  display_name: "DL/T 698.45"           # 人类可读名称，可选
  description: "..."                    # 协议简介，可选
```

| 字段 | 必须？ | 说明 |
|---|---|---|
| `name` | ✅ 必填 | 工具用它做协议名引用。如 `engine.parse(data, protocol="dlt698")` 里的 `"dlt698"` 就是这个 |
| `display_name` | 可选 | 输出报表时显示的名字 |
| `description` | 可选 | 给文档读者看的描述 |

### 3.4 块 ② `identifier`（识别规则）

这一块**很重要**。工具收到字节时，会遍历所有协议的 `identifier` 规则，谁全通过就用谁。

```yaml
identifier:
  start_byte: 0x68              # 帧首字节（如果协议有固定起始符）
  rules:                        # 一组检查规则，全部通过才算匹配
    - check: ends_with_byte     # 规则一：最后一字节是什么
      value: 0x16
    - check: byte_at_offset     # 规则二：偏移 5 处的字节是什么
      offset: 5
      value: 0x68
    - check: total_length_matches_buffer    # 规则三：长度域反推 = 实际总长
      length_field_offset: 1
      length_field_size: 2
      mask: 0x3FFF
```

#### 3.4.1 `start_byte` 字段

`start_byte: 0x68` —— 工具会先检查 `data[0] == 0x68`，不对直接淘汰这个协议。如果协议没有固定起始字节，可以省略。

#### 3.4.2 `rules` 列表（可写 0 条或多条）

每条规则有一个 `check: <规则名>`，加上规则特有的参数。**内置 4 种检查**：

| `check` 值 | 用途 | 参数 |
|---|---|---|
| `ends_with_byte` | 最后一字节是固定值 | `value: 0xXX` |
| `byte_at_offset` | 偏移 N 处的字节是固定值 | `offset: <数字>`、`value: 0xXX` |
| `length_field_layout` | 长度域结构特征 | `expect: dl_l_dl_l_pattern` 或 `binary_le_14bit` |
| `total_length_matches_buffer` | 长度域反推 = 实际帧长 | `length_field_offset`、`length_field_size`、`mask` |

#### 3.4.3 `length_field_layout` 的 `expect` 取值

- `dl_l_dl_l_pattern`：bytes[1..3] == bytes[3..5]，即"长度域重复两次"（376.2 的特征）
- `binary_le_14bit`：bytes[1..3] 是 LE 16-bit，且低 14 位 > 0（698 的特征）

#### 3.4.4 怎么挑选规则

| 协议特征 | 推荐规则组合 |
|---|---|
| 有固定起止符 | `start_byte:` + `ends_with_byte` |
| 有重复的长度域（如 376.2） | 加 `length_field_layout: dl_l_dl_l_pattern` |
| 有第二个起始符（如 376.2 偏移 5 处） | 加 `byte_at_offset: offset=5 value=0x68` |
| 长度域可以反推总长 | 加 `total_length_matches_buffer` |

**两种协议起始符都是 0x68 时也能区分**——通过长度域结构和第二个 0x68 的位置。

### 3.5 块 ③ `frames.base`（外层字段）

```yaml
frames:
  base:
    description: "外层骨架"        # 可选
    fields:
      - <字段 1>
      - <字段 2>
      - ...
```

**字段顺序必须和报文字节顺序一致**——这是协议规约怎么定的就怎么写。

**必须有的特殊字段**：`fields` 里必须有**至少一个** `role: payload` 字段，作为数据域占位（功能码 yaml 进一步细分时填到这里）。

每个字段怎么写？看下一节。

---

## 4. 功能码 YAML：数据域细节

### 4.1 文件位置

```
schemas/<协议名>/<任意文件名>.yaml
```

文件名你随便起（推荐 `afn_XX_xxx.yaml` 或 `service_XX_xxx.yaml`），工具看的是文件内部的 `service.service_code`。

### 4.2 顶层结构

```yaml
service:                  # 块 ①：服务码元信息
  protocol: dlt698        # 隶属哪个协议（要和 base.yaml 的 name 一致）
  service_code: 0x05      # 功能码值

variant_selector:         # 块 ②：变体选择规则（可选）
  rules:
    - when: { dir: 0, prm: 1 }
      variant: get_request

frames:                   # 块 ③：4 种帧变体
  get_request:
    fields: [ ... ]
  get_response:
    fields: [ ... ]
  set_request:
    enabled: false
  set_response:
    enabled: false
```

### 4.3 块 ① `service`

```yaml
service:
  protocol: gw3762         # 协议名，必须和某个 base.yaml 的 name 完全一致
  service_code: 0x0C       # 功能码（整数或 0x 十六进制）
  display_name: "..."      # 可选
  description: "..."       # 可选
```

> **关键**：`service_code` 必须**唯一**。同一个协议下不能有两个 yaml 用同样的 `service_code`。

### 4.4 块 ② `variant_selector`（变体选择规则）

**问题**：一个功能码下可能有 4 种帧（查询请求/响应/设置请求/响应），工具怎么知道当前报文是哪种？

**答**：从外层 yaml 的位域（如 `dir`、`prm`）来判断。`variant_selector` 就是这个映射表。

```yaml
variant_selector:
  rules:
    - when: { dir: 0, prm: 1 }       # 当外层 control.dir=0 且 control.prm=1
      variant: get_request           # 路由到 get_request 变体
    - when: { dir: 1, prm: 0 }
      variant: get_response
```

`when` 里写的 key（`dir`、`prm`）必须是 **base.yaml 中某个字段的 `bit_fields` 子名**。匹配规则：列出的所有 key 都满足，规则才算命中。

**省略时的默认行为**：
- 698 协议：按 service_code 的高位判断（0x05 → request，0x85 → response）
- 376.2 协议：按外层 `control` 的 `prm` 位判断
- 其他协议：按 yaml 中第一个启用的变体走

### 4.5 块 ③ `frames`（4 种帧变体）

```yaml
frames:
  get_request:         # 组查询帧（主站→终端方向的请求）
    description: "..."
    fields: [ ... ]

  get_response:        # 查询结果响应帧（终端→主站的应答 或 主动上报）
    fields: [ ... ]

  set_request:         # 组设置帧（主站→终端的写操作请求）
    fields: [ ... ]

  set_response:        # 设置结果响应帧（终端→主站的写操作应答）
    fields: [ ... ]
```

**4 种帧不一定都要写**：

| 写法 | 含义 |
|---|---|
| 4 种都写 | 完整支持读写双向 |
| 只写其中 1-2 种 | 工具就只支持这几种 |
| 写但加 `enabled: false` | 明确表示"本功能码不支持此方向"，文档更清晰 |
| 完全省略 | 等同 `enabled: false` |

```yaml
frames:
  get_request:
    fields: [ ... ]
  get_response:
    fields: [ ... ]
  set_request:
    enabled: false              # 明确告诉读者"本功能码不支持设置"
  set_response:
    enabled: false
```

---

## 5. 字段（field）属性详解

无论是 base.yaml 的外层字段，还是功能码 yaml 的数据域字段，**写法完全一样**。一个字段是一个 dict，可能有以下属性：

### 5.1 必填属性（2 个）

| 属性 | 说明 |
|---|---|
| `name` | 字段名，英文/数字/下划线。同一帧内必须**唯一** |
| `type` | 字段类型，见 [§6 字段类型速查表](#6-字段类型type速查表) |

最简单的字段：

```yaml
- name: cmd
  type: uint8
```

### 5.2 推荐属性（4 个）

| 属性 | 说明 | 示例 |
|---|---|---|
| `length` | 字段占多少字节，整数或 `variable` | `length: 2` 或 `length: variable` |
| `default` | 默认值（用户组帧时不传则用这个） | `default: "00"` |
| `description` | 字段含义说明，**会显示在解析输出中** | `description: "帧序号"` |
| `role` | 字段角色标记，框架用来识别特殊字段 | `role: payload` |

```yaml
- name: length
  type: uint16_le
  length: 2
  default: "0000"
  description: "帧总长度（含起止字节）"
  role: length
```

#### 5.2.1 `length` 的取值

| 写法 | 含义 |
|---|---|
| `length: 1` | 1 字节 |
| `length: 8` | 8 字节 |
| `length: variable` | 变长（参见 [§9 变长字段](#9-变长字段length-variable专题)） |

#### 5.2.2 `default` 怎么写

| 字段类型 | default 推荐写法 | 示例 |
|---|---|---|
| `uint8` / `uint16_le` 等整数 | `"XX"` 或数字 | `default: "43"` 或 `default: 0x43` |
| `bytes` | `"XXXXXX..."`（16 进制串，可加空格） | `default: "01 02 03"` |
| `bcd` / `bcd_le` | `"123456"`（数字串） | `default: "20240101"` |
| `ascii` | `"hello"` | `default: "STAT"` |
| `marker`（固定值） | `"XX"` | `default: "68"` |

> **重要**：default 用引号包起来最安全。除非是简单整数。

#### 5.2.3 `role` 的取值

| `role` | 含义 | 工具自动行为 |
|---|---|---|
| `marker` | 固定起止符 | 解析时校验值是否匹配 |
| `length` | 长度域 | 自动反推 payload 长度 |
| `checksum` | 校验域 | 自动校验 / 自动计算 |
| `payload` | 数据域占位 | 解析时切出数据交给功能码 yaml |
| `address` | 地址域 | 仅做语义标注，不改变行为 |
| `control` | 控制域 | 仅做语义标注 |
| `service` | 功能码/服务码 | **base.yaml 的 service 字段**会被用作功能码 yaml 的查找键 |
| `seq` | 帧序号 | 仅做语义标注 |

**一个 base.yaml 必须有 `role: payload` 字段**，否则工具拒绝加载。

**376.2 的 `afn` 字段**就标记成 `role: service`，工具因此知道："数据域要按 `afn` 的值去查功能码 yaml"。698 协议不需要这个标记——它的服务码直接是数据域的第一个字节。

### 5.3 高级属性（按需用）

| 属性 | 用途 | 详见 |
|---|---|---|
| `auto: true` | 由算法自动计算（长度/CRC） | [§7 算法](#7-内置算法algorithm速查表) |
| `algorithm: <名字>` | 配合 `auto: true` 指定哪个算法 | [§7 算法](#7-内置算法algorithm速查表) |
| `range:` | 配合 `auto: true` 指定算法覆盖范围 | 下面 §5.4 |
| `transform:` | 长度域的位掩码和保留位 | 下面 §5.5 |
| `bit_fields:` | 把字段按位拆成多个子字段 | [§8 位域](#8-位域bit_fields专题) |
| `values:` | 枚举值到名称的映射 | 下面 §5.6 |
| `source: <字段名>` | 配合 `algorithm: copy_field` 用 | [§7 算法](#7-内置算法algorithm速查表) |
| `bcd_digits: <数字>` | 配合 `type: bcd` 用，说明位数 | 下面 §5.7 |

### 5.4 `range` 属性

**专门给长度域和校验域用**。告诉工具"这个长度/CRC 覆盖了哪些字段"。

```yaml
- name: cs
  type: uint8
  length: 1
  role: checksum
  auto: true
  algorithm: sum_mod_256
  range:
    start: control       # 从 control 字段开始（含）
    end: data            # 到 data 字段为止（含）
```

> **重要**：`start` 和 `end` 都是**包含**两端的（闭区间）。`start` 写**第一个**要覆盖的字段名，`end` 写**最后一个**要覆盖的字段名。

#### 5.4.1 长度域的 range

**长度域覆盖什么取决于协议**。常见情况：

| 协议 | 长度覆盖范围 | YAML 写法 |
|---|---|---|
| 698 | start 到 end（含起止符） | `range: { start: start, end: end }` |
| 376.2 | control 到 data（不含起止/长度/CS） | `range: { start: control, end: data }` |
| Modbus RTU | 没有长度域 | 不用 |

#### 5.4.2 校验域的 range

| 协议 | 校验覆盖范围 | YAML 写法 |
|---|---|---|
| 698 HCS | length 到 address | `range: { start: length, end: addr_sa }` |
| 698 FCS | length 到 apdu | `range: { start: length, end: apdu }` |
| 376.2 CS | control 到 data | `range: { start: control, end: data }` |

### 5.5 `transform` 属性

长度域可能有"保留位"——比如 698 的长度字段是 16 bit，**只有低 14 位是长度**，高 2 位是保留位（永远为 0）。

```yaml
- name: length
  type: uint16_le
  length: 2
  role: length
  auto: true
  algorithm: length_bits14_le
  range: { start: start, end: end }
  transform:
    mask: 0x3FFF             # 长度只用低 14 位（0x3FFF = 0011_1111_1111_1111）
    reserved_bits: 0x0000    # 高 2 位的固定值
```

| 属性 | 含义 |
|---|---|
| `mask` | 长度值的有效位掩码（与运算） |
| `reserved_bits` | 保留位的固定值（或运算） |

如果协议没保留位（长度字段全是长度），就**不用写 transform**。

### 5.6 `values` 属性（枚举映射）

把数值映射到含义说明，方便阅读：

```yaml
- name: afn
  type: uint8
  length: 1
  values:
    0x00: "确认 / 否认"
    0x01: "复位命令"
    0x04: "设置参数"
    0x0C: "请求实时数据"
```

工具在输出时会顺带显示对应名称（视实现版本而定，至少作为文档增强）。

### 5.7 `bcd_digits` 属性

`bcd` / `bcd_le` 类型可以加 `bcd_digits` 标注实际位数（仅作注释用）：

```yaml
- name: energy
  type: bcd_le
  length: 5
  default: "0000000000"
  bcd_digits: 10               # 表示这个 5 字节 BCD 实际是 10 位数字
```

---

## 6. 字段类型（type）速查表

### 6.1 整数类型

| `type` | 字节数 | 字节序 | 取值范围 | 用途 |
|---|---|---|---|---|
| `uint8` | 1 | — | 0..255 | 通用 1 字节字段，**最常用** |
| `uint16_le` | 2 | 小端 | 0..65535 | 376.2 / 698 长度域 |
| `uint16_be` | 2 | 大端 | 0..65535 | DLMS OI 等 |
| `uint24_le` | 3 | 小端 | 0..16777215 | 少数协议用 |
| `uint24_be` | 3 | 大端 | 0..16777215 | 少数协议用 |
| `uint32_le` | 4 | 小端 | 0..2^32-1 | 时间戳、计数器 |
| `uint32_be` | 4 | 大端 | 0..2^32-1 | 网络字节序数值 |

> **怎么选字节序**：协议文档明说"先发送高字节"或"高字节在前" → `_be`（大端）；明说"低字节在前"或"先发送低字节" → `_le`（小端）。不确定时按 `_le` 试，错了再改。

```yaml
- { name: length, type: uint16_le, length: 2, default: "0000" }
```

### 6.2 字节序列

| `type` | 说明 | 何时用 |
|---|---|---|
| `bytes` | 原始字节，按字段长度截取 | 地址、原始数据、自定义编码 |
| `marker` | 固定值（如起止符），解析时校验 | `0x68`、`0x16` 等魔数 |
| `ascii` | ASCII 字符串 | 终端编号、文本 |

```yaml
- { name: address,  type: bytes,  length: 6, default: "000000000001" }
- { name: stx,      type: marker, length: 1, default: "68" }
- { name: terminal, type: ascii,  length: 16, default: "TERM0001" }
```

### 6.3 BCD（电力协议常用）

BCD = 每 4 位（半字节）表示 1 个十进制数字。常用来编码日期、电能量、电压电流等数值。

| `type` | 字节序 | 用途 |
|---|---|---|
| `bcd` | 高位在前（大端） | 698 多数 BCD 字段 |
| `bcd_le` | 低位在前（小端） | 376.2 多数 BCD 字段 |

```yaml
- name: energy
  type: bcd_le              # 低位在前
  length: 5
  default: "0000000000"     # 10 位数字（5 字节 BCD = 10 位）
  bcd_digits: 10
```

**重点**：default 用**数字串**写，每字节 2 位数字。例如 `"20240115"` = 8 位数字 = 4 字节 BCD。

### 6.4 DLMS / 698 专用类型

| `type` | 字节数 | 说明 |
|---|---|---|
| `axdr_oi` | 2 | 对象标识 OI（大端 16 位整数） |
| `axdr_oad` | 4 | 对象属性描述符 OAD = OI(2) + AttrIdx(1) + AttrQualifier(1) |
| `axdr_omd` | 4 | 对象方法描述符 OMD = OI(2) + MethodIdx(1) + MethodQualifier(1) |
| `axdr_date_time_s` | 7 | 简化日期时间 = YYYY(2) MM DD hh mm ss |
| `axdr_typed_data` | 变长 | A-XDR 自描述数据，按 tag 自决长度 |

```yaml
- name: oad
  type: axdr_oad
  length: 4
  default: "40000200"        # OI=0x4000, AttrIdx=2, AttrQualifier=0
  description: "OAD"
```

> 普通协议**用不到**这些。它们是 698 协议的标准编码方式。

### 6.5 类型选择决策树

```
是固定起止符吗？           → marker
是数值，几个字节？          → uintN_le / uintN_be
是地址 / 原始字节流？        → bytes
是电力 BCD 编码数值？        → bcd / bcd_le
是 ASCII 字符串？            → ascii
是 698 协议的对象描述符？    → axdr_oad / axdr_omd / axdr_oi
是 698 协议的 A-XDR 数据？   → axdr_typed_data
都不是？                     → 大概率是 bytes
```

---

## 7. 内置算法（algorithm）速查表

只有标了 `auto: true` 的字段才用算法。

| `algorithm` | 输出长度 | 含义 | 配合属性 |
|---|---|---|---|
| `length_le` | 由 `length:` 决定 | 把 `range` 内的字节数写成小端整数 | `range:`、`transform.mask`（可选） |
| `length_bits14_le` | 2 字节 | 16 位小端整数，**低 14 位是长度，高 2 位是保留** | `range:`、`transform.reserved_bits`（可选） |
| `sum_mod_256` | 1 字节 | range 内字节累加 & 0xFF（376.2 CS） | `range:` |
| `crc16_x25` | 2 字节小端 | CRC16/X.25 = FCS-16（698 HCS/FCS） | `range:` |
| `copy_field` | 同源字段 | 镜像另一个字段的字节（376.2 length2 复制 length1） | `source:` |

### 7.1 各算法的完整 YAML 范例

#### 7.1.1 普通长度域

```yaml
- name: length
  type: uint16_le
  length: 2
  default: "0000"
  role: length
  auto: true
  algorithm: length_le
  range: { start: control, end: data }     # 长度覆盖范围
```

#### 7.1.2 698 风格的 14 位长度域

```yaml
- name: length
  type: uint16_le
  length: 2
  default: "0000"
  role: length
  auto: true
  algorithm: length_bits14_le
  range: { start: start, end: end }
  transform:
    mask: 0x3FFF
    reserved_bits: 0x0000
```

#### 7.1.3 1 字节累加和校验

```yaml
- name: cs
  type: uint8
  length: 1
  default: "00"
  role: checksum
  auto: true
  algorithm: sum_mod_256
  range: { start: control, end: data }
```

#### 7.1.4 CRC16 校验

```yaml
- name: fcs
  type: uint16_le
  length: 2
  default: "0000"
  role: checksum
  auto: true
  algorithm: crc16_x25
  range: { start: length, end: apdu }
```

#### 7.1.5 镜像另一个字段（376.2 双长度域）

```yaml
- name: length2
  type: uint16_le
  length: 2
  default: "0000"
  role: length
  auto: true
  algorithm: copy_field
  source: length1                    # 复制 length1 的字节
```

### 7.2 协议有特殊算法怎么办？

工具内置了上面 5 种。**如果你的协议要用 Modbus CRC-16、CRC-32、XOR 等其他算法**，需要让工程师**注册一个 Python 算法**（一次性工作）：

```python
# 工程师写这段
def crc16_modbus(data: bytes) -> bytes:
    # ... 算法实现
    return result.to_bytes(2, "little")

engine.algos.register("crc16_modbus", crc16_modbus)
```

之后**所有协议的 YAML** 都能写 `algorithm: crc16_modbus`。

---

## 8. 位域（bit_fields）专题

电力协议有**大量按位定义的字段**——比如 376.2 控制域的 1 字节里塞了 DIR、PRM、FCB、FCV、功能码 5 个子字段。`bit_fields` 就是把这些子字段一次性声明出来。

### 8.1 基本写法

```yaml
- name: control
  type: uint8
  length: 1
  default: "4B"
  bit_fields:
    - { name: dir,      bits: "7"  , description: "传输方向：0=下行,1=上行" }
    - { name: prm,      bits: "6"  , description: "1=启动站发起" }
    - { name: fcb_acd,  bits: "5"  , description: "帧计数位" }
    - { name: fcv_dfc,  bits: "4"  , description: "FCB 有效" }
    - { name: function, bits: "3-0", description: "链路功能码（低 4 位）" }
```

### 8.2 `bits` 的写法

| 写法 | 含义 |
|---|---|
| `"5"` | 单个 bit（第 5 位） |
| `"7-4"` | 位段（第 7 位到第 4 位，共 4 个 bit） |
| `"15-8"` | 位段，可以**跨字节**（多字节字段时） |
| `"23-0"` | 也可以覆盖整个字段（多字节时） |

**位编号规则**：bit 0 = 最低位（LSB），bit 7 = 1 字节字段的最高位（MSB）。

### 8.3 位编号在多字节字段上怎么算

对**多字节**字段，工具把整个字段值看作**一个大整数**来取位：

- 对 `bytes` 类型：按**大端**转整数（先发送的字节 = 高位）
- 对 `uint16_be` / `uint32_be` 类型：解码后的整数值
- 对 `uint16_le` / `uint32_le` 类型：解码后的整数值（注意：这是数值，不是 wire 顺序）

**例 1**：2 字节 `bytes` 字段，wire = `12 34`：
- 大端整数 = 0x1234
- `bits: "15-8"` → 0x12（第一个字节）
- `bits: "7-0"` → 0x34（第二个字节）
- `bits: "11-4"` → 0x23（**横跨两字节**）

**例 2**：`uint16_le` 字段，wire = `12 34`（小端）：
- 解码后的整数值 = 0x3412
- `bits: "15-8"` → 0x34
- `bits: "7-0"` → 0x12

### 8.4 跨字节位域

完全支持。比如某协议 2 字节数据：
- bits 15-4：12 位设备号
- bits 3-0：4 位修订号

直接这么写：

```yaml
- name: device_info
  type: bytes
  length: 2
  default: "0000"
  bit_fields:
    - { name: device_id, bits: "15-4", description: "设备号 12 bit" }
    - { name: revision,  bits: "3-0",  description: "修订号 4 bit" }
```

**位段宽度上限**：`bits` 范围最高位 ≤ 63（即最多覆盖 8 字节字段）。

### 8.5 组帧时按位域赋值

写位域后，**用户可以分别给每个子值赋值**：

```python
engine.build(
    protocol="myproto",
    fields={
        "control": {"dir": 1, "prm": 0, "function": 11},   # 用字典给位域分别赋值
    },
)
```

工具会自动合成最终字节。

### 8.6 解析输出

带位域的字段，输出会自动展开：

```
control  @6  len=1  raw=4B  value=0x4B  {dir=0, prm=1, fcb_acd=0, fcv_dfc=0, function=11}
```

---

## 9. 变长字段（`length: variable`）专题

电力协议有大量变长字段。工具支持 3 种变长场景：

### 9.1 场景 A：外层数据域（payload）

这是**最常见**的——整帧长度由 length 字段告知，数据域占的字节数 = `length - 其他固定字段总长`。

**写法**：

```yaml
- name: data
  type: bytes
  length: variable
  default: ""
  role: payload          # ★ 必须标 role: payload
```

工具看到 `role: payload` 后会**自动反推**长度，**用户什么都不用算**。

### 9.2 场景 B：A-XDR 自描述变长（698 用）

698 协议的响应数据用 A-XDR 编码：第一字节是 tag（0x09=octet_string 等），之后跟长度前缀和值。**长度由 tag 自决**。

**写法**：

```yaml
- name: data
  type: axdr_typed_data
  length: variable
  default: "12 00 00"          # 默认值是一个完整的 A-XDR 编码（tag+value）
  description: "A-XDR 编码的响应数据"
```

无论实际 data 是 3 字节、6 字节还是 100 字节，工具都能按 A-XDR 标准解出。

### 9.3 场景 C：占满剩余字节（偷懒用 / 自定义协议）

某个字段写 `length: variable`，工具会自动算"可用空间" = `当前位置之后所有字节 - 后续固定长度字段的总长`。

**用法 1**：末尾偷懒，剩下全塞进 `tail`：

```yaml
fields:
  - { name: da,   type: bytes, length: 2 }       # 精确解析
  - { name: dt,   type: bytes, length: 2 }       # 精确解析
  - { name: tail, type: bytes, length: variable, description: "剩余数据，未深度解析" }
```

如果数据域共 16 字节，前 4 字节解出 da+dt，剩下 12 字节自动归 tail。

**用法 2**：中间未知段，头尾都已知：

```yaml
fields:
  - { name: header,  type: bytes, length: 4 }
  - { name: unknown, type: bytes, length: variable }      # 自动 = 总长 - 4 - 2
  - { name: footer,  type: uint16_le, length: 2 }
```

### 9.4 变长字段使用限制

- ✅ 一个 frame 里**只能有一个**"占剩余"的变长 bytes 字段
- ✅ 这个变长字段前后可以有任意多个**定长**字段
- ✅ 自描述类型（`axdr_typed_data`）可以多个并存
- ❌ 一个 frame 里**不能有两个**普通变长 bytes 字段——工具算不出谁占多少

---

## 10. 从协议文档到 YAML 的完整推导

下面用一个**虚构协议**演示完整流程。

### 10.1 协议规约（假设）

> **MyTherm V1 协议**
>
> 帧格式：
>
> | 字节 | 内容 |
> |---|---|
> | 0 | 起始符 0xAA |
> | 1 | 设备地址 (1 byte) |
> | 2 | 命令码 CMD (1 byte) |
> | 3 | 数据长度 LEN (1 byte，表示数据域字节数) |
> | 4..N | 数据域 (LEN 字节) |
> | N+1 | 异或校验 (从地址到数据域末尾的 XOR) |
> | N+2 | 结束符 0x55 |
>
> CMD 列表：
> - 0x01：读温度
>   - 请求帧：数据域 = `传感器ID(1B)`
>   - 响应帧：数据域 = `传感器ID(1B) + 温度值(2B 大端，单位 0.1℃)`
> - 0x02：设置阈值
>   - 请求帧：数据域 = `阈值上限(2B 大端)+ 阈值下限(2B 大端)`
>   - 响应帧：数据域 = `0x00=成功 / 其他=失败码`

### 10.2 第 1 步：决定协议名

英文小写 + 数字，唯一：`mytherm`。

```yaml
protocol:
  name: mytherm
  display_name: "MyTherm V1"
  description: "温控设备通信协议"
```

### 10.3 第 2 步：识别规则

我们看到协议有固定起止符 0xAA / 0x55。**异或校验暂时不放进 identifier**（identifier 只用前置的廉价检查）。

```yaml
identifier:
  start_byte: 0xAA
  rules:
    - check: ends_with_byte
      value: 0x55
```

### 10.4 第 3 步：列出外层字段

按报文顺序：

```
0: start (0xAA)         → marker, 1 字节
1: address              → uint8, 1 字节
2: cmd                  → uint8, 1 字节
3: len                  → uint8, 1 字节（数据长度）
4..N: data              → bytes, 变长（占 len 字节）
N+1: xor_cs             → uint8, 1 字节（异或校验）
N+2: end (0x55)         → marker, 1 字节
```

异或校验是工具**没内置**的算法，可以先用 `auto: false` 占位（暂不校验），后续让工程师注册一下 XOR 算法即可。

### 10.5 第 4 步：写 base.yaml

```yaml
protocol:
  name: mytherm
  display_name: "MyTherm V1"

identifier:
  start_byte: 0xAA
  rules:
    - check: ends_with_byte
      value: 0x55

frames:
  base:
    fields:
      - name: start
        type: marker
        length: 1
        default: "AA"
        role: marker

      - name: address
        type: uint8
        length: 1
        default: "01"
        role: address
        description: "设备地址"

      - name: cmd
        type: uint8
        length: 1
        default: "01"
        role: service
        description: "命令码"
        values:
          0x01: "读温度"
          0x02: "设置阈值"

      - name: len
        type: uint8
        length: 1
        default: "00"
        role: length
        auto: true
        algorithm: length_le
        range: { start: data, end: data }     # 只统计 data 字段长度

      - name: data
        type: bytes
        length: variable
        default: ""
        role: payload

      - name: xor_cs
        type: uint8
        length: 1
        default: "00"
        role: checksum
        # auto: true            ← 等工程师注册 xor 算法后启用
        # algorithm: xor_8bit
        # range: { start: address, end: data }
        description: "异或校验（暂不自动校验，需注册 xor 算法）"

      - name: end
        type: marker
        length: 1
        default: "55"
        role: marker
```

放到 `schemas/mytherm/base.yaml`。**到这一步已经可以用了**——任何 mytherm 协议的报文都能解出外层。

### 10.6 第 5 步：写 CMD=0x01 的功能码 yaml

CMD=0x01 有 2 个变体：请求（传感器 ID）和响应（传感器 ID + 温度）。

```yaml
# schemas/mytherm/cmd_01_read_temp.yaml
service:
  protocol: mytherm
  service_code: 0x01
  display_name: "读温度"

frames:
  get_request:
    description: "请求温度：发送传感器 ID"
    fields:
      - name: sensor_id
        type: uint8
        length: 1
        default: "01"
        description: "传感器编号"

  get_response:
    description: "响应温度：传感器 ID + 温度值"
    fields:
      - name: sensor_id
        type: uint8
        length: 1
        default: "01"
        description: "传感器编号"
      - name: temperature
        type: uint16_be
        length: 2
        default: "0000"
        description: "温度值，单位 0.1℃ (例如 235 = 23.5℃)"

  set_request:
    enabled: false                  # 0x01 不支持设置
  set_response:
    enabled: false
```

### 10.7 第 6 步：写 CMD=0x02 的功能码 yaml

CMD=0x02 是设置阈值：

```yaml
# schemas/mytherm/cmd_02_set_threshold.yaml
service:
  protocol: mytherm
  service_code: 0x02
  display_name: "设置阈值"

frames:
  set_request:
    description: "设置阈值：上限 + 下限"
    fields:
      - name: upper
        type: uint16_be
        length: 2
        default: "00C8"          # 默认 200 = 20.0℃
        description: "阈值上限（0.1℃）"
      - name: lower
        type: uint16_be
        length: 2
        default: "0064"          # 默认 100 = 10.0℃
        description: "阈值下限（0.1℃）"

  set_response:
    description: "设置结果"
    fields:
      - name: result
        type: uint8
        length: 1
        default: "00"
        description: "0=成功，其他=失败码"
        values:
          0x00: "成功"
          0x01: "参数越界"
          0x02: "权限不足"

  get_request:
    enabled: false
  get_response:
    enabled: false
```

### 10.8 第 7 步：测试

把 3 个文件放到 `schemas/mytherm/`，运行 demo 或写一行代码：

```python
engine.load_schemas("schemas/")
result = engine.parse("AA 01 01 01 03 02 55")    # 一条请求温度的报文
print(result.format_byte_map())
```

如果输出每个字段都正确，**协议接入完成**。

---

## 11. 常用模式速查

### 11.1 模式：固定起止符

```yaml
- { name: start, type: marker, length: 1, default: "68", role: marker }
# ... 中间字段 ...
- { name: end,   type: marker, length: 1, default: "16", role: marker }
```

### 11.2 模式：长度域（1/2/4 字节，小端）

```yaml
- name: length
  type: uint16_le               # 改成 uint8 / uint32_le 同理
  length: 2
  default: "0000"
  role: length
  auto: true
  algorithm: length_le
  range: { start: <第一个被覆盖的字段>, end: <最后一个被覆盖的字段> }
```

### 11.3 模式：CRC16 校验

```yaml
- name: crc
  type: uint16_le
  length: 2
  default: "0000"
  role: checksum
  auto: true
  algorithm: crc16_x25
  range: { start: ..., end: ... }
```

### 11.4 模式：累加和校验（1 字节）

```yaml
- name: cs
  type: uint8
  length: 1
  default: "00"
  role: checksum
  auto: true
  algorithm: sum_mod_256
  range: { start: ..., end: ... }
```

### 11.5 模式：BCD 编码的日期时间

```yaml
- name: datetime
  type: bcd
  length: 7
  default: "20240101120000"     # YYYYMMDDhhmmss → 7 字节 BCD = 14 位数字
  bcd_digits: 14
  description: "日期时间，BCD 大端"
```

### 11.6 模式：1 字节内多个子字段（位域）

```yaml
- name: status
  type: uint8
  length: 1
  default: "00"
  bit_fields:
    - { name: power_on, bits: "7", description: "0=关 1=开" }
    - { name: alarm,    bits: "6", description: "告警位" }
    - { name: mode,     bits: "5-4", description: "模式 0-3" }
    - { name: priority, bits: "3-0", description: "优先级 0-15" }
```

### 11.7 模式：跨字节位域

```yaml
- name: combo
  type: bytes              # 或 uint16_be
  length: 2
  default: "0000"
  bit_fields:
    - { name: high_part, bits: "15-4" }     # 12 bit，跨字节
    - { name: low_part,  bits: "3-0" }      # 4 bit
```

### 11.8 模式：变长数据域（payload）

```yaml
- name: data
  type: bytes
  length: variable
  default: ""
  role: payload                # ★ 必须有
```

### 11.9 模式：偷懒解析（末尾塞 tail）

```yaml
fields:
  - { name: known_field_1, type: ..., length: ... }
  - { name: known_field_2, type: ..., length: ... }
  - { name: tail, type: bytes, length: variable, description: "未深度解析的剩余字节" }
```

### 11.10 模式：把功能码 yaml 中"不支持的方向"显式禁用

```yaml
frames:
  get_request:
    fields: [ ... ]
  get_response:
    fields: [ ... ]
  set_request:
    enabled: false
  set_response:
    enabled: false
```

---

## 12. 常见错误与排查

### 12.1 YAML 语法错误

**症状**：工具加载时报 `YAML parse error`。

**原因**：

| 错误 | 例子 |
|---|---|
| 缩进不一致 | 一项缩进 2 格，下一项缩进 4 格 |
| 用了 Tab 缩进 | YAML 不接受 Tab，必须用空格 |
| 冒号后没空格 | `name:dlt698` 应写 `name: dlt698` |
| 字节序列没加引号 | `default: 68 19 00` 应写 `default: "68 19 00"` |
| 列表项忘了 `- ` | 列表必须每项前 `- `（短横线 + 空格） |

**排查**：把 YAML 文件粘贴到任意"YAML 在线检查器"，会标出第几行错。

### 12.2 校验不通过 / `valid=false`

**症状**：解析出来 `errors=['cs mismatch: ...']`。

**原因**：
- `range` 写错了——`start` 或 `end` 字段名打错，或者覆盖范围不对
- 算法选错了——比如协议是 Modbus CRC 但你写成了 `crc16_x25`
- 长度域字节序写错——协议是大端但你写了 `uint16_le`

**排查**：
- 检查 `range.start` 和 `range.end` 的字段名是否在 fields 列表里**真实存在**
- 用一个**已知正确的报文**（厂家给的样例）对照解析输出，看哪个字段值不对
- 协议文档明确写"高字节在前" → 用 `_be`；"低字节在前" → 用 `_le`

### 12.3 数据域长度算错

**症状**：解析后 data 字段长度不对，或者 apdu 子结构解析失败。

**原因**：
- length 字段的 `range` 写错了——长度域到底覆盖哪些字段必须和协议规约一致
- payload 字段忘了写 `role: payload`
- 一帧里写了**多个**`length: variable` 的 bytes 字段

**排查**：
- 用最简单的报文先解外层（不写功能码 yaml），看 `data.length` 是否等于协议算出来的值
- 检查 length 字段的 `range.start` 和 `range.end` 是否符合协议描述

### 12.4 功能码不下钻 / `apdu = None`

**症状**：解析出来只有外层，没有 apdu 子结果。

**原因**：
- 功能码 yaml 没放到正确目录
- yaml 里 `service.protocol` 写错（必须和 base 的 `name` 一致）
- `service.service_code` 和实际报文里的值不匹配
- `variant_selector` 规则不命中，且没有变体能匹配
- 选中的变体写了 `enabled: false`

**排查**：
- 确认所有 yaml 都放在 `schemas/<协议名>/` 目录下
- 打印 `engine.list_services("协议名")` 看是否注册成功
- 用调试日志看实际选中的变体名

### 12.5 位域分解不对

**症状**：`bit_fields` 输出的值跟手算的不一样。

**原因**：
- 多字节字段的位编号没搞清楚——`uint16_be` 和 `uint16_le` 的位编号基准不同
- 协议文档里的"bit 7"指什么？有些协议从 MSB 开始数（bit 7=最高位），有些从 LSB 开始数（bit 0=最低位）

**排查**：
- 工具的位编号约定：**bit 0 = 最低位（LSB）**，跟绝大多数协议一致
- 如果协议文档说"bit 0=最高位"，要做反向映射

### 12.6 组帧时报错 `value too large` / `does not fit`

**症状**：`engine.build(...)` 报错。

**原因**：传入的值超出了字段范围。比如把 `uint8` 字段赋值 0x1234。

**排查**：检查字段类型和传入的数值是否匹配。

### 12.7 解析时报 `marker mismatch`

**症状**：错误信息提到某个 marker 字段值不对。

**原因**：协议规约里说起始符是 `0x68`，但报文里实际不是。**通常说明报文本身有问题**，或者协议识别错了（不是这个协议的报文）。

---

## 13. 完整示例参考

`schemas/` 目录下有以下完整可用的样例 yaml，**直接打开看就是最好的参考**：

| 文件 | 用途 |
|---|---|
| `schemas/dlt698/base.yaml` | 698 外层骨架（含 CRC、14-bit 长度域） |
| `schemas/dlt698/service_05_get_request.yaml` | 单变体启用、其余禁用的例子 |
| `schemas/dlt698/service_85_get_response.yaml` | DLMS A-XDR 数据字段的例子 |
| `schemas/gw3762/base.yaml` | 376.2 外层骨架（含双长度域、累加和校验） |
| `schemas/gw3762/afn_0c_query_realtime.yaml` | 简单 AFN 的 yaml（DA + DT + 数据） |
| `schemas/gw3762/afn_04_set_params.yaml` | **4 种帧变体全部启用**的完整示例 |

### 13.1 最小可用模板

如果你要新加一个协议，从下面这个最小模板改起：

```yaml
# schemas/<你的协议>/base.yaml
protocol:
  name: <协议名>
  display_name: "<显示名>"

identifier:
  start_byte: 0xXX           # 改成实际起始符；没有就删掉
  rules:
    - check: ends_with_byte
      value: 0xXX

frames:
  base:
    fields:
      - { name: start,  type: marker, length: 1, default: "XX", role: marker }
      # ... 其他字段按协议规约顺序写 ...
      - { name: data,   type: bytes, length: variable, default: "", role: payload }
      # ... 校验和结束符 ...
      - { name: end,    type: marker, length: 1, default: "XX", role: marker }
```

---

## 附录 A. 字段属性完整参考表

| 属性 | 类型 | 必填？ | 适用范围 | 说明 |
|---|---|---|---|---|
| `name` | str | ✅ | 所有字段 | 字段名，同一帧内唯一 |
| `type` | str | ✅ | 所有字段 | 字段类型（见 §6） |
| `length` | int / `"variable"` | 推荐 | 所有字段 | 字节数 |
| `default` | str / int | 推荐 | 所有字段 | 默认值 |
| `description` | str | 推荐 | 所有字段 | 字段含义（输出会显示） |
| `role` | str | 可选 | 外层骨架 | `marker`/`length`/`checksum`/`payload`/`address`/`control`/`service`/`seq` |
| `bit_fields` | list | 可选 | 任意字段 | 位域分解（见 §8） |
| `auto` | bool | 可选 | length/checksum 字段 | 自动计算开关 |
| `algorithm` | str | 配合 auto | length/checksum 字段 | 算法名（见 §7） |
| `range` | dict | 配合 auto | length/checksum 字段 | `{start: ..., end: ...}` 算法覆盖范围 |
| `transform` | dict | 可选 | length 字段 | `{mask: ..., reserved_bits: ...}` 位掩码 |
| `source` | str | 配合 `copy_field` | length 字段 | 源字段名 |
| `values` | dict | 可选 | 整数字段 | `{值: "名称"}` 枚举映射 |
| `bcd_digits` | int | 可选 | bcd 字段 | BCD 实际位数（仅注释） |

## 附录 B. YAML 编写检查清单

在提交 yaml 之前，逐项检查：

- [ ] 文件放在 `schemas/<协议名>/` 目录下
- [ ] base.yaml 有 `protocol:` + `identifier:` + `frames.base:` 三块
- [ ] base.yaml 的 fields 里至少有一个 `role: payload` 字段
- [ ] 功能码 yaml 的 `service.protocol` 和 base.yaml 的 `protocol.name` 一致
- [ ] 功能码 yaml 的 `service.service_code` 在该协议下唯一
- [ ] 所有 `range.start` / `range.end` 引用的字段名**存在**于 fields 列表里
- [ ] 字节序列的 `default` 用**引号**包起来
- [ ] 缩进**全部用空格**，**没有 Tab**
- [ ] 长度域的字节序和协议文档一致（大端 `_be` / 小端 `_le`）
- [ ] 用一条已知正确的报文测试解析，`valid=True`、所有字段值正确

---

## 附录 C. 写完 YAML 怎么测试

把 yaml 放到 `schemas/<协议名>/`，运行：

```python
from protocol import ProtocolEngine

engine = ProtocolEngine()
engine.load_schemas("schemas/")

# 测试 1：协议识别
print(engine.identify("AA 01 01 01 03 02 55"))     # 应输出协议名

# 测试 2：解析报文
result = engine.parse("AA 01 01 01 03 02 55")
print(result.format_byte_map())                    # 按字节归属看每一位

# 测试 3：组帧
frame = engine.build(
    protocol="<你的协议名>",
    function_code=0x01,
    frame_type="get_request",
    fields={"address": 0x02, "data.sensor_id": 0x03},
)
print(frame.hex(" ").upper())

# 测试 4：build → parse 回环
result2 = engine.parse(frame)
assert result2.valid
print("OK")
```

每加一个 yaml 都跑一遍这 4 步，几分钟就能验证完。

---

> **最后**：如果遇到本文档没覆盖到的情况，参考现有的 `schemas/dlt698/` 和 `schemas/gw3762/` 下的 yaml——它们是经过测试可工作的真实例子，从里头复制贴改是最快的方法。
