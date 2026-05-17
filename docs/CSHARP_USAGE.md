# C# 集成指南

本文档讲如何从 **C# / .NET** 项目中调用本协议解析器。

由于本工具是 Python 实现，C# 集成有两种推荐方式：

| 方式 | 适用场景 | 优点 | 缺点 |
|---|---|---|---|
| **CLI 子进程** | 偶尔调用、命令行工具、批处理 | 零依赖、简单、易调试 | 每次启动 Python 有开销（~100-300ms） |
| **HTTP 服务** | 高频调用、生产环境、服务化 | 性能好（毫秒级）、可远程部署 | 需运行一个 Python 进程 |

第三种方式 `Python.NET` 嵌入 Python 解释器到 .NET 进程，性能最好但部署复杂，**不在本文档推荐**——除非你已经在用 Python.NET 生态。

---

## 目录

1. [准备工作](#1-准备工作)
2. [方式一：CLI 子进程](#2-方式一cli-子进程)
3. [方式二：HTTP 服务（推荐生产环境）](#3-方式二http-服务推荐生产环境)
4. [完整 C# 客户端库](#4-完整-c-客户端库)
5. [接口数据格式参考（与语言无关）](#5-接口数据格式参考与语言无关)
6. [部署建议](#6-部署建议)
7. [性能与故障排查](#7-性能与故障排查)

---

## 1. 准备工作

### 1.1 部署 Python 环境

C# 端要调用 Python，所以 Python 解释器必须可用。

**方案 A：服务器/工作机预装 Python**
```
要求：Python ≥ 3.9，pip install pyyaml
路径：能在命令行执行 `python --version`
```

**方案 B：打包独立 Python**（推荐用于交付给客户）
- 用 PyInstaller 打包：`pyinstaller --onefile src/protocol/__main__.py`
- 产出一个 `protocol.exe`，C# 直接调它，无需客户机器装 Python

```bash
# 打包 CLI
pip install pyinstaller
cd /path/to/protocol
pyinstaller --onefile --name protocol-cli --paths src src/protocol/__main__.py
# 产出 dist/protocol-cli.exe（Windows）或 dist/protocol-cli（Linux）

# 打包 HTTP 服务（如果用 HTTP 方式）
pyinstaller --onefile --name protocol-server --paths src examples/http_server.py
```

打包后 C# 端只需要：
- `protocol-cli.exe`（或 `protocol-server.exe`）
- `schemas/` 目录（YAML 文件）

### 1.2 .NET 版本要求

代码示例基于 **.NET 6 及以上**（用 `System.Text.Json`、`HttpClient`、`record` 等现代特性）。
.NET Framework 4.7+ 也能用，把 `record` 改成 `class`、`System.Text.Json` 换成 `Newtonsoft.Json`。

---

## 2. 方式一：CLI 子进程

### 2.1 工作原理

C# 启动 Python 子进程，通过命令行参数传输入，通过 stdout 读 JSON 输出。

```
C# 程序  ──Process.Start──>  python -m protocol parse --hex "68 0C ..."
   ▲                                          │
   └──────── JSON ─────────  stdout ←─────────┘
```

### 2.2 最小例子

```csharp
using System.Diagnostics;
using System.Text.Json;

string output;
var psi = new ProcessStartInfo
{
    FileName = "python",
    Arguments = "-m protocol --schemas schemas identify --hex \"68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16\"",
    RedirectStandardOutput = true,
    UseShellExecute = false,
    CreateNoWindow = true,
};

using (var p = Process.Start(psi)!)
{
    output = p.StandardOutput.ReadToEnd();
    p.WaitForExit();
}

var json = JsonDocument.Parse(output);
string? protocol = json.RootElement.GetProperty("protocol").GetString();
Console.WriteLine($"识别到协议: {protocol}");
// 输出: 识别到协议: gw3762
```

### 2.3 注意事项

- **`Arguments` 字符串里的引号**要转义：`\"` 或者用 `ArgumentList`（推荐，.NET Core 3+）
- **工作目录** `ProcessStartInfo.WorkingDirectory` 要包含 `schemas/` 目录
- **stderr 也要捕获**，错误时 CLI 把 JSON 错误写到 stderr，退出码非零
- **大报文**慎用，命令行长度有限制（Windows 32K）—— 大报文用 stdin 或 HTTP 方式

### 2.4 更可靠的写法（用 ArgumentList）

```csharp
var psi = new ProcessStartInfo
{
    FileName = "python",
    RedirectStandardOutput = true,
    RedirectStandardError = true,
    UseShellExecute = false,
    CreateNoWindow = true,
    WorkingDirectory = @"D:\path\to\project\root",   // ★ 包含 schemas/ 的目录
};
psi.ArgumentList.Add("-m");
psi.ArgumentList.Add("protocol");
psi.ArgumentList.Add("--schemas");
psi.ArgumentList.Add("schemas");
psi.ArgumentList.Add("parse");
psi.ArgumentList.Add("--hex");
psi.ArgumentList.Add("68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16");

using var proc = Process.Start(psi)!;
string stdout = proc.StandardOutput.ReadToEnd();
string stderr = proc.StandardError.ReadToEnd();
proc.WaitForExit();

if (proc.ExitCode != 0)
    throw new Exception($"protocol CLI failed: {stderr}");
```

---

## 3. 方式二：HTTP 服务（推荐生产环境）

### 3.1 工作原理

后台启动一个 Python HTTP 服务，C# 通过 `HttpClient` 发 JSON 请求。

```
C# 程序  ──POST /parse──>  http://localhost:8765
   ▲                              │
   │       Python 服务进程        │
   └─────── JSON ────────────────┘
```

启动服务：

```bash
# 开发期
python examples/http_server.py --host 127.0.0.1 --port 8765 --schemas schemas/

# 生产期（打包后）
protocol-server.exe --host 127.0.0.1 --port 8765 --schemas schemas/
```

服务启动一次，常驻；C# 多次请求复用同一进程，**单次解析 < 5ms**。

### 3.2 最小例子

```csharp
using System.Net.Http;
using System.Net.Http.Json;

var http = new HttpClient { BaseAddress = new Uri("http://127.0.0.1:8765") };

// 识别协议
var resp = await http.PostAsJsonAsync("/identify", new {
    hex = "68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16"
});
var result = await resp.Content.ReadFromJsonAsync<Dictionary<string, string>>();
Console.WriteLine($"识别到协议: {result!["protocol"]}");

// 组帧
var buildResp = await http.PostAsJsonAsync("/build", new {
    protocol = "gw3762",
    function_code = 0x0C,
    frame_type = "get_request",
    fields = new Dictionary<string, object>
    {
        ["data.da"] = "0101",
        ["data.dt"] = "0100",
    },
});
var built = await buildResp.Content.ReadFromJsonAsync<Dictionary<string, JsonElement>>();
Console.WriteLine($"组帧结果: {built!["hex"].GetString()}");
```

---

## 4. 完整 C# 客户端库

下面是一个**可直接拿来用**的 C# 客户端，包装好两种集成方式，对外提供一致的 API。

### 4.1 数据类型

```csharp
using System.Text.Json.Serialization;

public record ProtocolField(
    int Offset,
    int Length,
    string Hex,
    string Field,
    object? Value,
    Dictionary<string, int>? BitFields,
    string? Description
);

public record ByteMapResult(
    string Protocol,
    string? FunctionCode,
    string FrameType,
    bool Valid,
    List<string> Errors,
    string Raw,
    List<ProtocolField> ByteMap
);

public record BuildResult(string Hex, int Length);
```

### 4.2 客户端接口（统一抽象）

```csharp
public interface IProtocolClient
{
    Task<string?> IdentifyAsync(string hexFrame);
    Task<ByteMapResult> ParseAsync(string hexFrame, string? protocol = null, bool strict = true);
    Task<BuildResult> BuildAsync(string protocol, int? functionCode, string? frameType, object fields);
    Task<List<string>> ListProtocolsAsync();
}
```

### 4.3 HTTP 实现

```csharp
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

public class HttpProtocolClient : IProtocolClient, IDisposable
{
    private readonly HttpClient _http;
    private readonly bool _ownsClient;

    public HttpProtocolClient(string baseUrl = "http://127.0.0.1:8765")
    {
        _http = new HttpClient { BaseAddress = new Uri(baseUrl), Timeout = TimeSpan.FromSeconds(10) };
        _ownsClient = true;
    }

    /// <summary>给已有 HttpClient 用（推荐配合 IHttpClientFactory 使用）</summary>
    public HttpProtocolClient(HttpClient http)
    {
        _http = http;
        _ownsClient = false;
    }

    public async Task<string?> IdentifyAsync(string hexFrame)
    {
        var resp = await PostAsync<Dictionary<string, string?>>("/identify", new { hex = hexFrame });
        return resp!["protocol"];
    }

    public async Task<ByteMapResult> ParseAsync(string hexFrame, string? protocol = null, bool strict = true)
    {
        return await PostAsync<ByteMapResult>("/bytemap", new {
            hex = hexFrame,
            protocol,
            strict,
        });
    }

    public async Task<BuildResult> BuildAsync(string protocol, int? functionCode, string? frameType, object fields)
    {
        return await PostAsync<BuildResult>("/build", new {
            protocol,
            function_code = functionCode,
            frame_type = frameType,
            fields,
        });
    }

    public async Task<List<string>> ListProtocolsAsync()
    {
        using var resp = await _http.GetAsync("/list");
        resp.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await resp.Content.ReadAsStreamAsync());
        var list = new List<string>();
        foreach (var p in doc.RootElement.GetProperty("protocols").EnumerateArray())
            list.Add(p.GetProperty("name").GetString()!);
        return list;
    }

    // ---- helpers ----
    private async Task<T> PostAsync<T>(string path, object payload)
    {
        using var resp = await _http.PostAsJsonAsync(path, payload);
        if (!resp.IsSuccessStatusCode)
        {
            var errBody = await resp.Content.ReadAsStringAsync();
            throw new ProtocolException($"protocol HTTP {(int)resp.StatusCode}: {errBody}");
        }
        var result = await resp.Content.ReadFromJsonAsync<T>(new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            PropertyNameCaseInsensitive = true,
        });
        return result ?? throw new ProtocolException("empty response");
    }

    public void Dispose()
    {
        if (_ownsClient) _http.Dispose();
    }
}

public class ProtocolException : Exception
{
    public ProtocolException(string msg) : base(msg) { }
}
```

### 4.4 CLI 子进程实现

```csharp
using System.Diagnostics;
using System.Text.Json;

public class CliProtocolClient : IProtocolClient
{
    private readonly string _python;
    private readonly string _workDir;
    private readonly string _schemasDir;

    /// <param name="pythonOrExe">python 解释器路径，或打包后的 protocol-cli.exe 路径</param>
    /// <param name="workDir">工作目录（一般是项目根，包含 schemas/）</param>
    /// <param name="schemasDir">schemas 目录的相对/绝对路径</param>
    public CliProtocolClient(string pythonOrExe = "python",
                              string workDir = ".",
                              string schemasDir = "schemas")
    {
        _python = pythonOrExe;
        _workDir = workDir;
        _schemasDir = schemasDir;
    }

    public Task<string?> IdentifyAsync(string hexFrame)
    {
        var json = RunCli("identify", "--hex", hexFrame);
        return Task.FromResult(json.RootElement.GetProperty("protocol").GetString());
    }

    public Task<ByteMapResult> ParseAsync(string hexFrame, string? protocol = null, bool strict = true)
    {
        var args = new List<string> { "bytemap", "--hex", hexFrame };
        if (protocol != null) { args.Add("--protocol"); args.Add(protocol); }
        if (!strict) args.Add("--no-strict");
        var json = RunCli(args.ToArray());
        return Task.FromResult(JsonSerializer.Deserialize<ByteMapResult>(
            json.RootElement.GetRawText(),
            new JsonSerializerOptions {
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
                PropertyNameCaseInsensitive = true,
            })!);
    }

    public Task<BuildResult> BuildAsync(string protocol, int? functionCode, string? frameType, object fields)
    {
        var args = new List<string> { "build", "--protocol", protocol };
        if (functionCode.HasValue) { args.Add("--function-code"); args.Add($"0x{functionCode.Value:X}"); }
        if (frameType != null) { args.Add("--frame-type"); args.Add(frameType); }
        args.Add("--fields");
        args.Add(JsonSerializer.Serialize(fields));
        var json = RunCli(args.ToArray());
        return Task.FromResult(new BuildResult(
            json.RootElement.GetProperty("hex").GetString()!,
            json.RootElement.GetProperty("length").GetInt32()
        ));
    }

    public Task<List<string>> ListProtocolsAsync()
    {
        var json = RunCli("list");
        var list = new List<string>();
        foreach (var p in json.RootElement.GetProperty("protocols").EnumerateArray())
            list.Add(p.GetProperty("name").GetString()!);
        return Task.FromResult(list);
    }

    // ---- helpers ----
    private JsonDocument RunCli(params string[] subArgs)
    {
        var psi = new ProcessStartInfo
        {
            FileName = _python,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = _workDir,
        };
        // 如果用打包后的 exe，不需要 -m 参数
        var isExe = _python.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                    && !_python.EndsWith("python.exe", StringComparison.OrdinalIgnoreCase);
        if (!isExe)
        {
            psi.ArgumentList.Add("-m");
            psi.ArgumentList.Add("protocol");
        }
        psi.ArgumentList.Add("--schemas");
        psi.ArgumentList.Add(_schemasDir);
        foreach (var a in subArgs)
            psi.ArgumentList.Add(a);

        using var p = Process.Start(psi)!;
        string stdout = p.StandardOutput.ReadToEnd();
        string stderr = p.StandardError.ReadToEnd();
        p.WaitForExit();
        if (p.ExitCode != 0)
            throw new ProtocolException($"protocol CLI failed (exit {p.ExitCode}): {stderr}");
        return JsonDocument.Parse(stdout);
    }
}
```

### 4.5 使用示例

```csharp
class Program
{
    static async Task Main()
    {
        // 选择一个客户端实现
        // 方式 A：CLI（无需启动服务，但每次有进程启动开销）
        IProtocolClient client = new CliProtocolClient(
            pythonOrExe: "python",
            workDir: @"D:\YourProject",
            schemasDir: "schemas"
        );

        // 方式 B：HTTP（生产推荐）
        // IProtocolClient client = new HttpProtocolClient("http://127.0.0.1:8765");

        // 1) 列出已支持的协议
        Console.WriteLine("协议列表:");
        foreach (var p in await client.ListProtocolsAsync())
            Console.WriteLine($"  - {p}");

        // 2) 识别一条报文
        string hex = "68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16";
        Console.WriteLine($"\n识别: {await client.IdentifyAsync(hex)}");

        // 3) 解析（拿到字节归属表）
        Console.WriteLine("\n解析结果:");
        var parsed = await client.ParseAsync(hex);
        Console.WriteLine($"  协议: {parsed.Protocol}");
        Console.WriteLine($"  功能码: {parsed.FunctionCode}");
        Console.WriteLine($"  帧类型: {parsed.FrameType}");
        Console.WriteLine($"  校验: {(parsed.Valid ? "通过" : "失败")}");
        foreach (var f in parsed.ByteMap)
        {
            var bits = f.BitFields != null
                ? "  " + string.Join(",", f.BitFields.Select(kv => $"{kv.Key}={kv.Value}"))
                : "";
            Console.WriteLine($"  [{f.Offset,3}] len={f.Length} {f.Hex,-20} {f.Field,-25} = {f.Value}{bits}");
        }

        // 4) 组帧
        var built = await client.BuildAsync(
            protocol: "gw3762",
            functionCode: 0x0C,
            frameType: "get_request",
            fields: new Dictionary<string, object>
            {
                ["address"] = "3201000100",
                ["data.da"] = "0101",
                ["data.dt"] = "0100",
            }
        );
        Console.WriteLine($"\n组帧: {built.Hex}  ({built.Length} 字节)");
    }
}
```

**输出示例**：

```
协议列表:
  - dlt698
  - gw3762

识别: gw3762

解析结果:
  协议: gw3762
  功能码: 0x0C
  帧类型: get_request
  校验: 通过
  [  0] len=1 68                   start1                    = 104
  [  1] len=2 0C 00                length1                   = 12
  [  3] len=2 0C 00                length2                   = 12
  [  5] len=1 68                   start2                    = 104
  [  6] len=1 4B                   control                   = 75  dir=0,prm=1,fcb_acd=0,fcv_dfc=0,function=11
  [  7] len=5 32 01 00 01 00       address                   = 32 01 00 01 00
  [ 12] len=1 0C                   afn                       = 12
  [ 13] len=1 60                   seq                       = 96  tpv=0,fir=1,fin=1,con=0,pseq=0
  [ 14] len=2 01 01                apdu.da                   = 01 01  da2=1,da1=1
  [ 16] len=2 01 00                apdu.dt                   = 01 00  dt2=0,dt1=1
  [ 18] len=1 EE                   cs                        = 238
  [ 19] len=1 16                   end                       = 22

组帧: 68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16  (20 字节)
```

---

## 5. 接口数据格式参考（与语言无关）

如果你用其他语言（Go / Java / Node.js）也能直接照搬。

### 5.1 `/identify`

**请求**:
```json
{ "hex": "68 0C 00 0C 00 68 4B ..." }
```

**响应（200）**:
```json
{ "protocol": "gw3762" }
```

无法识别时 `"protocol": null`。

### 5.2 `/parse`

**请求**:
```json
{
  "hex": "68 0C 00 ...",
  "protocol": null,           // 可选；不填则自动识别
  "strict": true              // 可选；false 时校验失败也返回，valid=false
}
```

**响应（200）**:
```json
{
  "protocol": "gw3762",
  "frame_type": "base",
  "function_code": null,
  "valid": true,
  "errors": [],
  "fields": {
    "start1": { "value": "68", "offset": 0, "length": 1, "raw": "68" },
    "length1": { "value": 12, "offset": 1, "length": 2, "raw": "0C 00" },
    ...
  },
  "apdu": {
    "protocol": "gw3762",
    "frame_type": "get_request",
    "function_code": "0x0C",
    "valid": true,
    "fields": { ... }
  },
  "raw": "68 0C 00 ..."
}
```

### 5.3 `/bytemap`（推荐给 C# 用，输出更整齐）

**请求**: 同 `/parse`

**响应（200）**:
```json
{
  "protocol": "gw3762",
  "function_code": "0x0C",
  "frame_type": "get_request",
  "valid": true,
  "errors": [],
  "raw": "68 0C 00 ...",
  "byte_map": [
    {
      "offset": 0,
      "length": 1,
      "hex": "68",
      "field": "start1",
      "value": "68",
      "bit_fields": null,
      "description": null
    },
    {
      "offset": 6,
      "length": 1,
      "hex": "4B",
      "field": "control",
      "value": 75,
      "bit_fields": { "dir": 0, "prm": 1, "function": 11 },
      "description": "帧控制：DIR/PRM/..."
    },
    ...
  ]
}
```

### 5.4 `/build`

**请求**:
```json
{
  "protocol": "gw3762",
  "function_code": 12,              // 整数或省略
  "frame_type": "get_request",      // get_request|get_response|set_request|set_response
  "fields": {
    "address": "3201000100",
    "data.da": "0101",
    "data.dt": "0100"
  }
}
```

**响应（200）**:
```json
{ "hex": "68 0C 00 0C 00 68 ...", "length": 20 }
```

### 5.5 `/list`

**请求**: GET `/list` 或 GET `/list?protocol=gw3762`

**响应**:
```json
{
  "protocols": [
    { "name": "dlt698", "services": ["0x05", "0x85"] },
    { "name": "gw3762", "services": ["0x04", "0x0C"] }
  ]
}
```

### 5.6 错误响应（4xx）

所有错误都用统一格式：

```json
{ "error": "ParseError", "message": "cs mismatch: expected EE, got FF" }
```

| `error` 字段值 | 含义 |
|---|---|
| `IdentifyError` | 自动识别失败 |
| `ParseError` | 解析失败（含校验不通过） |
| `BuildError` | 组帧失败 |
| `SchemaError` | YAML 加载错误（启动时） |
| `CodecError` | 字段编解码错误 |
| `KeyError` / `ValueError` / `TypeError` | 请求参数错误 |

---

## 6. 部署建议

### 6.1 单机部署（CLI 方式）

```
你的 C# 应用程序/
├── YourApp.exe
├── protocol-cli.exe              ← PyInstaller 打包的 CLI
├── schemas/                      ← YAML 文件
│   ├── dlt698/
│   └── gw3762/
└── ...
```

```csharp
var client = new CliProtocolClient(
    pythonOrExe: Path.Combine(AppContext.BaseDirectory, "protocol-cli.exe"),
    workDir: AppContext.BaseDirectory,
    schemasDir: "schemas"
);
```

**优点**：零运维。安装即用。
**缺点**：每次调用启动进程，单条 ~200ms。**不适合高频调用**。

### 6.2 服务化部署（HTTP 方式）

```
服务器/
├── protocol-server.exe           ← PyInstaller 打包的 HTTP 服务
├── schemas/
└── 用 NSSM / systemd 注册成服务
```

C# 端通过 `HttpClient` 调用。

**推荐做法**（用 `IHttpClientFactory` 复用连接）：

```csharp
// Program.cs (ASP.NET Core / .NET Generic Host)
builder.Services.AddHttpClient<HttpProtocolClient>(c =>
{
    c.BaseAddress = new Uri("http://127.0.0.1:8765");
    c.Timeout = TimeSpan.FromSeconds(5);
});
builder.Services.AddSingleton<IProtocolClient>(sp =>
    sp.GetRequiredService<HttpProtocolClient>());

// 业务代码里注入
public class FrameService(IProtocolClient _proto)
{
    public async Task<ByteMapResult> AnalyzeFrame(string hex)
        => await _proto.ParseAsync(hex);
}
```

### 6.3 Docker 化部署

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY src /app/src
COPY schemas /app/schemas
COPY examples/http_server.py /app/
RUN pip install pyyaml
EXPOSE 8765
CMD ["python", "http_server.py", "--host", "0.0.0.0", "--port", "8765", "--schemas", "schemas"]
```

C# 容器通过容器网络访问。

---

## 7. 性能与故障排查

### 7.1 性能参考

| 操作 | CLI 方式 | HTTP 方式 |
|---|---|---|
| 协议识别 | ~200ms（含进程启动） | ~2ms |
| 解析一条 100 字节报文 | ~250ms | ~3ms |
| 组帧 | ~200ms | ~2ms |

**HTTP 方式约比 CLI 快 100 倍**，因为省了 Python 启动 + YAML 加载开销。

### 7.2 常见问题

#### Q：`python` 命令找不到（CLI 方式）
- 检查 Python 是否在 PATH，或用绝对路径 `C:\Python311\python.exe`
- 用 PyInstaller 打包成独立 exe，彻底解耦

#### Q：`SchemaError` 找不到 schemas 目录
- `WorkingDirectory` 设错了。打印 `Environment.CurrentDirectory` 看下
- 或直接传绝对路径：`schemasDir: @"D:\YourApp\schemas"`

#### Q：HTTP 服务连接被拒
- 端口被占用？换一个：`--port 8766`
- 服务挂了？检查是否还在运行
- 防火墙？本地 127.0.0.1 一般不会拦

#### Q：JSON 反序列化失败
- 检查 .NET 版本是否支持 `JsonNamingPolicy.SnakeCaseLower`（.NET 8+）
- 老版本用：`PropertyNamingPolicy = JsonNamingPolicy.CamelCase` + 手动加 `[JsonPropertyName]`，或者用 Newtonsoft.Json

#### Q：大批量解析时 HTTP 服务变慢
- HTTP 服务默认单进程，并发数取决于 ThreadingHTTPServer 线程池
- 如果 QPS > 100，考虑：
  - 用 `gunicorn` / `uvicorn` 跑多 worker（需要把 server 改成 WSGI/ASGI）
  - 在 C# 端做请求队列 + 多副本服务

#### Q：中文乱码
- HTTP 服务返回的 JSON 都用 UTF-8，`HttpClient` 默认解码 UTF-8，正常情况无乱码
- CLI 方式在 Windows cmd 下显示乱码是终端编码问题，但 C# `StandardOutput.ReadToEnd()` 拿到的 bytes 本身没问题。如果是真乱码：设 `psi.StandardOutputEncoding = Encoding.UTF8`

---

## 附录 A. 完整可运行的 C# 项目骨架

放一个最小的 .NET 6 项目结构：

```
ProtocolDemo/
├── ProtocolDemo.csproj
├── Program.cs
├── IProtocolClient.cs       ← §4.2 的接口
├── HttpProtocolClient.cs    ← §4.3 的实现
├── CliProtocolClient.cs     ← §4.4 的实现
├── Models.cs                ← §4.1 的数据类型
└── schemas/                 ← 拷贝项目根的 schemas/ 过来
    ├── dlt698/
    └── gw3762/
```

`ProtocolDemo.csproj`:
```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
  </PropertyGroup>
</Project>
```

启动顺序：
1. （HTTP 方式）`python examples/http_server.py --port 8765`
2. `dotnet run`

---

## 附录 B. 其他语言

接口都是 HTTP + JSON / CLI + JSON，**任何语言**都能调。下面是其他常用语言的最小示例：

### Go
```go
resp, _ := http.Post("http://127.0.0.1:8765/identify",
    "application/json",
    strings.NewReader(`{"hex":"68 0C 00 ..."}`))
defer resp.Body.Close()
body, _ := io.ReadAll(resp.Body)
fmt.Println(string(body))
```

### Java
```java
HttpClient client = HttpClient.newHttpClient();
HttpRequest req = HttpRequest.newBuilder()
    .uri(URI.create("http://127.0.0.1:8765/identify"))
    .header("Content-Type", "application/json")
    .POST(BodyPublishers.ofString("{\"hex\":\"68 0C 00 ...\"}"))
    .build();
HttpResponse<String> resp = client.send(req, BodyHandlers.ofString());
System.out.println(resp.body());
```

### Node.js
```javascript
const resp = await fetch("http://127.0.0.1:8765/identify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hex: "68 0C 00 ..." }),
});
console.log(await resp.json());
```

### curl（命令行调试）
```bash
curl -X POST http://127.0.0.1:8765/identify \
    -H "Content-Type: application/json" \
    -d '{"hex":"68 0C 00 0C 00 68 4B 32 01 00 01 00 0C 60 01 01 01 00 EE 16"}'
```
