# BenchVCR 零基础学习笔记与完整项目走读

> 这份文档假设你没有学过程控仪器，也不熟悉 Python 测试、打包和硬件通信。
> 每个概念都先解释“它是什么、为什么需要它”，再说明 BenchVCR 怎样使用它。
> 文中的“全部知识点”指本项目涉及的知识，不试图替代完整的 Python 或电子学教材。

## 0. 怎样使用这份笔记

不建议第一遍就从 `session.py` 开始啃源码。可以分三遍阅读：

1. **第一遍：建立直觉。** 读第 1～5 章，运行一次 demo，知道项目解决什么问题。
2. **第二遍：理解实现。** 读第 6～15 章，沿着具体命令追踪 record、replay 和 fault。
3. **第三遍：独立修改。** 读第 16～24 章，学会看测试、调试源码并完成练习。

遇到不懂的缩写，可以先查第 23 章术语表，再回来继续，不必一次记住所有名词。

### 0.1 章节地图

| 想解决的问题 | 直接阅读 |
| --- | --- |
| 这个项目到底有什么用？ | 第 1～2 章 |
| 不懂电源、SCPI、串口、VISA | 第 3 章 |
| 不懂 Python 的 Protocol、异常、with | 第 4 章 |
| 想知道文件和模块怎么组织 | 第 5、17 章 |
| 想理解 record 和 cassette | 第 6～7 章 |
| 想理解 replay 和故障注入 | 第 8～9 章 |
| 想理解虚拟电源、adapter、插件和 CLI | 第 10～13 章 |
| 想理解测试、打包、调试和未来路线 | 第 15～21 章 |
| 想快速查错误或术语 | 第 14、22～23 章 |

### 0.2 先记住四个边界

- 本项目操作的是**文本请求—响应协议**，不是任意二进制数据。
- 当前是**同步、单连接、一次一个未完成请求**，不是并发框架。
- demo 使用的是**虚拟电源**，不需要硬件，也不能证明真实仪器兼容。
- BenchVCR 记录的是**通信过程**，不是完整仪器状态，更不是电气物理仿真。

### 0.3 当前版本已经验证什么

本次交付在本机 Python 3.12.16 下完成了 143 项测试，核心分支覆盖率为 94%，
并完成静态检查、构建和 wheel 隔离安装。没有运行远端 GitHub Actions，也没有
连接真实串口或 VISA 仪器。后文提到“测试通过”时，指的都是这个本地范围。

---

## 1. 一句话理解 BenchVCR

### 1.1 它解决什么问题

假设测试一台电源时，程序需要执行下面的对话：

```text
程序：你是谁？             *IDN?
电源：我是某型号电源。     BenchVCR,VirtualPSU,...

程序：把电压设为 5 V。     VOLT 5
电源：好的，没有文本响应。

程序：打开输出。           OUTP ON
电源：好的，没有文本响应。

程序：现在实际电压是多少？ MEAS:VOLT?
电源：5.000000
```

真实设备可能不在手边，或者某些故障很难重复，例如“第 4 条命令刚好超时”。
BenchVCR 提供三种能力：

1. **record（录制）**：真实调用 transport，同时把每次请求和结果写进 cassette。
2. **replay（回放）**：不访问设备，按照 cassette 中的顺序返回相同结果。
3. **fault injection（故障注入）**：回放时有意识地延迟、超时、断连或修改响应。

它有点像录像机：先录下对话，再播放对话。但它不是“随便问什么都回答”的模拟器。
回放时你必须按照原来的顺序说原来的台词，否则它会明确报错。

### 1.2 一个最重要的认识

BenchVCR **不理解你的业务测试是否正确**。它只保证：

- 录制下来的交互具有明确格式；
- 回放严格遵循原来的 `kind` 和原始 `command`；
- 成功、空响应和通信错误都能重放；
- 配置的故障按照确定规则触发；
- 文件破坏、少调用、多调用和顺序错误不会被悄悄忽略。

至于“电压应该是 5 V 还是 12 V”，仍由你的测试断言负责。

### 1.3 四个核心角色

| 角色 | 人话解释 | 项目中的实现 |
| --- | --- | --- |
| transport | 真正负责发命令、收响应的对象 | `TextTransport` Protocol、虚拟电源、两个 adapter |
| session | 在 record/replay 中管理当前进度的对象 | `RecordSession`、`ReplaySession` |
| cassette | 保存交互的“录像带” | 一个 JSONL 文本文件 |
| fault plan | 描述在哪一次交互注入什么故障 | 一个 JSON 文件 |

可以把它们想成：transport 是电话，session 是录像/播放控制器，cassette 是录像带，
fault plan 是“播放时在指定位置制造故障”的剧本。

---

## 2. 先运行一次，再学习原理

以下命令默认你已经进入项目根目录：

```bash
cd /Users/rickychan/GoCode/src/claude-code-test/benchvcr
```

### 2.1 运行硬件无关 demo

```bash
.venv/bin/benchvcr demo --output-dir demo-output --seed 42
```

你会看到类似输出：

```text
PASS record (13 exchanges)
PASS clean replay
PASS fault: delay
PASS fault: timeout
PASS fault: disconnect
PASS fault: truncate
PASS fault: response_replace
PASS cassette hash unchanged (...)
Cassette: .../demo-output/virtual-psu.jsonl
```

这些行分别表示：

1. 用虚拟电源录下 13 次交互；
2. 没有故障时完整回放成功；
3. 分别用五份 fault plan 回放成功；
4. 回放前后 cassette 的 SHA-256 没变，证明回放没有改写录像带。

`seed = 42` 是故障概率算法使用的固定种子。当前 demo 省略 `probability`，等效于使用
默认值 1，所以规则必然触发；seed 仍写入生成的计划，演示相同配置可以重复使用。

### 2.2 查看生成的文件

```text
demo-output/
├── virtual-psu.jsonl
├── fault-delay.json
├── fault-timeout.json
├── fault-disconnect.json
├── fault-truncate.json
└── fault-response_replace.json
```

验证 cassette：

```bash
.venv/bin/benchvcr cassette validate demo-output/virtual-psu.jsonl
```

成功输出：

```text
OK demo-output/virtual-psu.jsonl (13 exchanges)
```

### 2.3 demo 没有证明什么

它没有证明：

- 某台真实电源能识别这些命令；
- 真实测量值有六位小数精度；
- pyserial 或 PyVISA 与你电脑上的驱动兼容；
- Windows、Ubuntu 远端 CI 已经通过；
- 高电压、大电流操作是安全的。

它证明的是：**这套录制、校验、回放、故障选择、CLI 和虚拟协议可以串联工作。**

---

## 3. 硬件和通信基础

### 3.1 程控电源是什么

普通可调电源可能需要人旋旋钮；程控电源允许程序通过命令设置和读取状态。
本项目虚拟电源只有三个重要状态：

- `voltage_set`：希望输出多少电压，单位 V（伏特）；
- `current_limit`：允许的最大电流，单位 A（安培）；
- `output_enabled`：输出开关是否打开。

还有一个固定负载 `load_ohms`，默认 10 Ω（欧姆）。负载可以简单理解为接在输出端
的电阻。根据欧姆定律：

```text
电流 I = 电压 V / 电阻 R
功率 P = 电压 V × 电流 I
```

“设定值”和“测量值”不是一回事。例如设定 12 V，但限流导致实际只能输出 5 V，
那么 `VOLT?` 查询的是设定值，`MEAS:VOLT?` 查询的是模型中的实际测量值。

真实电源还有噪声、校准误差、温度影响和动态响应；本虚拟模型一概不模拟。

### 3.2 SCPI 是什么

SCPI 是一种常见仪器命令文本约定。你不需要先背标准，本项目只使用这些命令：

| 命令 | 类型 | 含义 |
| --- | --- | --- |
| `*IDN?` | query | 查询身份字符串 |
| `*RST` | write | 复位到默认状态 |
| `VOLT 5` | write | 设置电压为 5 V |
| `VOLT?` | query | 查询电压设定值 |
| `CURR 0.5` | write | 设置限流为 0.5 A |
| `CURR?` | query | 查询限流设定值 |
| `OUTP ON` / `OUTP OFF` | write | 打开/关闭输出 |
| `OUTP?` | query | 查询输出开关，`1` 为开、`0` 为关 |
| `MEAS:VOLT?` | query | 查询模型测量电压 |
| `MEAS:CURR?` | query | 查询模型测量电流 |

问号通常表示查询，但它只是命令文本的一部分，不是 Python 运算符。

`write()` 和 `query()` 的区别是：

```python
transport.write("VOLT 5")  # 成功返回 None，不期待响应文本
response = transport.query("VOLT?")  # 成功返回字符串，例如 "5.000000"
```

把 `VOLT?` 交给 `write()`，或把 `VOLT 5` 交给 `query()`，虚拟电源都会抛
`ProtocolError`，因为使用方式不符合协议。

### 3.3 协议到底是什么

“协议”就是通信双方对消息格式和顺序的约定。例如：

- 命令是文本还是二进制；
- 一条命令在哪里结束；
- 查询是否有响应；
- 数字采用什么格式；
- 出错时如何表示。

本项目有两种容易混淆的“Protocol”：

1. **硬件协议**：`VOLT 5`、termination、响应格式等通信约定。
2. **Python 的 `typing.Protocol`**：描述对象应该具有哪些方法的结构化类型约定。

`TextTransport` 属于第二种。它要求对象有 `write()`、`query()`、`close()`，不关心
对象内部真正使用串口、VISA 还是内存变量。

### 3.4 字节、字符串和编码

计算机链路传输的是 bytes（字节），Python 文本是 `str`（字符串）。两者不是一回事：

```python
text = "VOLT 5"
data = text.encode("utf-8")  # b"VOLT 5"
restored = data.decode("utf-8")  # "VOLT 5"
```

编码就是把字符变成字节的规则。ASCII 能表示常见英文命令；UTF-8 能表示中文、
希腊字母等更多字符。发送和接收使用不同编码可能产生乱码或解码错误。

Python 中前缀 `b` 表示 bytes：

```python
"5.0"  # str

b"5.0"  # bytes
```

cassette 的 `command` 和 `response` 是 JSON 字符串；serial adapter 在边界上负责
`str ↔ bytes` 转换。

### 3.5 CR、LF 和 termination

文本命令不会自动告诉接收方“这条消息结束了”。常见终止符是：

- LF：`\n`，换行，字节值 10；
- CR：`\r`，回车，字节值 13；
- CRLF：`\r\n`，两个字节。

项目里的 termination 就是“消息终止符”。假设：

```python
write_termination = "\r\n"
read_termination = "\n"
```

执行 `write("VOLT 5")` 时，serial adapter 实际写入：

```python
b"VOLT 5\r\n"
```

收到 `b" 5.0 \r\n"` 时，read termination 是 `\n`，adapter 只移除这个终止符，返回：

```python
response = " 5.0 \r"
```

它不会调用 `.strip()`。因为 `.strip()` 会继续删掉首尾空格和 `\r`，改变原始响应。

注意单位：session 中的原始 `command` 不含 CR/LF，也不允许包含它们；termination
属于 adapter 的配置，不属于 cassette 的命令匹配内容。

### 3.6 串口、波特率和 pyserial

串口是一种逐字节传输的接口。常见配置包括：

- **baudrate（波特率）**：链路符号传输速率，常见值如 9600、115200；
- **data bits（数据位）**：每个数据帧携带几位数据；
- **stop bits（停止位）**：标志一个串口帧结束；
- **parity（校验位）**：用于简单传输错误检查。

这些参数必须与设备匹配，但它们和 SCPI 是不同层次。即使串口参数正确，也仍要约定
命令文本、编码和 termination。

pyserial 是 Python 串口库。`SerialTextAdapter` 不替你猜测端口或参数，而是接收一个
已经创建好的 connection，再补上 BenchVCR 需要的文本行为。

### 3.7 VISA、PyVISA 和 PyVISA-sim

VISA 是仪器 I/O 的统一抽象。message-based VISA resource 以“消息”为单位读写，
常见于 USB、TCP/IP、GPIB 等仪器连接。

一个 VISA resource 字符串可能类似：

```text
TCPIP::192.0.2.10::INSTR
```

它描述资源地址，不是网页 URL。实际工具通常通过 ResourceManager 创建资源：

```python
import pyvisa

manager = pyvisa.ResourceManager()
resource = manager.open_resource("TCPIP::192.0.2.10::INSTR")
```

几个名字的区别：

- **VISA**：接口规范/实现层；
- **PyVISA**：Python 调用 VISA 的库；
- **PyVISA-sim**：模拟 VISA 资源的后端，仍不是实机；
- **`PyVISAAdapter`**：本项目对 message-based text resource 的薄封装。

当前项目只通过 fake 验证 adapter 契约，没有声明上述示例地址可连接，也没有验证
任何真实 VISA 后端。

### 3.8 同步、单连接、单 outstanding

**同步**表示调用 `query()` 后，当前线程等待结果或异常，然后才返回。

**单连接**表示一个 session 只包装一个 transport，不管理设备池。

**单 outstanding** 表示同一时刻最多一个“已经发出、尚未完成”的请求。下面的顺序
是允许的：

```text
发 query A → 等 A 完成 → 发 query B → 等 B 完成
```

当前版本不处理：

- A、B 同时发出后再区分两个响应；
- 设备不请求就主动发送的状态上报；
- 一条请求对应多条响应；
- async/await 或多线程并发。

这些情况需要请求 ID、缓冲队列或更复杂的消息关联机制，不能靠当前严格顺序模型
安全地“顺手支持”。

### 3.9 timeout、disconnect、protocol、transport

| 错误类别 | 含义 | 示例 |
| --- | --- | --- |
| `timeout` | 在规定时间内没完成 | 一直没收到完整响应 |
| `disconnect` | 当前连接不可用 | 对端关闭连接 |
| `protocol` | 数据或使用方式不符合协议 | query 返回 bytes、响应不能按编码解码 |
| `transport` | 其他底层传输错误 | 串口写失败、非 timeout 的 VISA 错误 |

partial-read timeout 是“收到一部分后超时”。例如已经收到 `b"5."`，之后一直收不到
剩余内容和 termination。它不能当作成功的空响应，也不能把 `b"5."` 当完整结果返回。

`delay` 与 `timeout` 不同：delay 是等待后仍返回原结果；timeout 是本次操作失败。

---

## 4. 阅读源码前需要的 Python 基础

### 4.1 对象、方法和 adapter

对象把数据和方法放在一起。例如：

```python
supply = VirtualPowerSupply()
supply.write("VOLT 5")
value = supply.query("VOLT?")
```

`supply` 是对象，`write` 和 `query` 是它的方法。

adapter（适配器）的作用是让不同对象以同一方式被使用。真实串口对象的读写方法是
bytes 形式，虚拟电源的方法直接接收 str；通过共同约定，session 不需要知道底层差别。

### 4.2 `TextTransport` 是类型约定，不是具体实现

`src/benchvcr/transport.py` 定义：

```python
class TextTransport(Protocol):
    def write(self, command: str) -> None: ...
    def query(self, command: str) -> str: ...
    def close(self) -> None: ...
```

这表示“只要对象提供这些方法，就可以被当成 TextTransport 使用”。不要求它继承
某个基类，这种风格常叫结构化类型或鸭子类型：走路像鸭子、叫声像鸭子，就按鸭子
的接口使用。

`@runtime_checkable` 允许运行时在有限范围内做 Protocol 检查；本项目主要把它用于
类型表达，并不依赖它验证所有真实驱动行为。

### 4.3 类型标注、联合类型和 Literal

示例：

```python
def query(self, command: str) -> str: ...
```

表示参数应是 str，返回值应是 str。类型标注主要帮助 mypy 和阅读者，不会自动把
所有运行时错误变成类型错误，所以代码仍有显式校验。

常见记号：

- `str | None`：可以是 str，也可以是 None；
- `Path | str`：两种类型都接受；
- `Literal["write", "query"]`：只允许这两个字面值；
- `tuple[Exchange, ...]`：由 Exchange 组成的任意长度元组；
- `Callable[[float], None]`：接收 float、返回 None 的函数。

### 4.4 dataclass 和 frozen

`@dataclass` 自动为数据类生成初始化、 repr 等常见代码。`frozen=True` 表示创建后
不应再修改字段。

项目中的 `Exchange` 就是一条交互的数据对象：

```python
Exchange(
    seq=0,
    kind="query",
    command="*IDN?",
    at_ms=0.0,
    duration_ms=0.2,
    ok=True,
    response="device",
    error=None,
)
```

使用数据对象比在很多函数之间传九个独立变量更不容易把参数顺序弄错。

不过 `error` 指向的异常对象本身仍有 Python 异常行为；“不可变数据模型”不表示
程序里所有引用对象都绝对不可变。

### 4.5 None、空字符串和 False 不一样

这是本项目很重要的基础：

```python
None  # 没有值
""  # 有字符串值，长度是 0
False  # 布尔假
0  # 数字零
```

所以成功 query 可以返回 `""`，不能返回 None；成功 write 的 response 是 None；
失败交互的 response 也是 None，但必须有 error。

不要写下面这种会混淆空响应的判断：

```python
if response:  # "" 会被当成 False
    ...
```

本项目在关键边界检查 `is None` 或 `isinstance(response, str)`。

### 4.6 异常、抛出和捕获

程序用异常表示无法按正常路径继续：

```python
try:
    result = transport.query("MEAS:VOLT?")
except TransportTimeoutError:
    result = "本次按超时处理"
finally:
    transport.close()
```

- `raise`：抛出异常；
- `try/except`：捕获指定异常；
- `finally`：无论正常或异常都执行，适合释放资源；
- `raise ... from ...`：保留异常原因链。

BenchVCR 不把所有异常都伪装成硬件错误。配置错误、cassette 格式错误、断言错误和
通信错误有不同类型，调用方才可以选择正确处理。

### 4.7 context manager 和 `with`

`with` 用来管理进入和退出动作：

```python
with use_cassette(path, transport=supply) as io:
    io.query("*IDN?")
```

它大致对应：

1. 调用 session 的 `__enter__()`；
2. 把返回值赋给 `io`；
3. 执行缩进中的测试体；
4. 无论正常还是异常，都调用 `__exit__(...)`。

`__exit__` 能知道测试体是否带异常退出。BenchVCR 利用这一点决定：

- 正常退出：record 发布临时 recording；replay 检查是否全部消费；
- 异常退出：record 删除临时半成品；replay 不追加 unplayed，也绝不删除或修改 cassette。
  两者都不让清理动作覆盖原来的测试异常。

session 的 `close()` 是 no-op（不执行底层关闭），因为 cassette 生命周期由 `with`
管理，外部 transport 的生命周期由创建者管理。不要在 `with` 中途用 `close()` 期待
“提前发布 cassette”。

### 4.8 资源所有权

“谁创建，谁负责关闭”是最容易理解的所有权规则：

```python
supply = VirtualPowerSupply()
try:
    with use_cassette(path, transport=supply) as io:
        io.query("*IDN?")
finally:
    supply.close()
```

session 没有创建 supply，所以不关闭它。这样同一个 transport 可以在多个明确阶段
中使用，避免录制结束后被库悄悄关掉。

### 4.9 pathlib 和路径

`Path` 用来表达文件路径：

```python
path = Path("cassettes") / "basic.jsonl"
```

比手工拼接 `"/"` 更适合跨平台。项目约定：

- record 的目标父目录必须已经存在；
- 临时文件与目标在同一目录；
- pytest fixture 的相对 cassette 名从“当前测试文件旁的 cassettes/”解析；
- replay 不创建 transport，也不修改 cassette。

---

## 5. 项目结构和整体架构

### 5.1 目录树逐文件说明

```text
benchvcr/
├── pyproject.toml              # 打包、依赖、entry point、pytest/Ruff/mypy/覆盖率配置
├── README.md                  # 英文使用说明
├── TODO.md                    # 中文版本路线和本地验收记录
├── LICENSE                    # MIT 许可证
├── .gitignore                 # 忽略本地工具、环境和构建产物
├── .github/workflows/ci.yml   # 三平台 CI 配置，不等于远端已运行
├── docs/
│   └── learning-notes.zh-CN.md # 本文
├── src/benchvcr/
│   ├── __init__.py            # 公共 API 汇总和库版本
│   ├── __main__.py            # 支持 python -m benchvcr
│   ├── errors.py              # 异常层级和稳定通信错误映射
│   ├── transport.py           # TextTransport Protocol
│   ├── cassette.py            # JSONL 数据类、序列化、完整 schema 校验
│   ├── session.py             # record/replay 状态机和 use_cassette
│   ├── faults.py              # fault plan 校验、规则选择、SHA-256、故障执行
│   ├── virtual.py             # 确定性虚拟程控电源
│   ├── demo.py                # 13 条脚本、五类故障 demo、hash 检查
│   ├── cli.py                 # 参数解析、stdout/stderr、退出码
│   ├── pytest_plugin.py       # benchvcr_replay fixture
│   ├── py.typed               # 告诉类型检查器：包内包含类型信息
│   └── adapters/
│       ├── __init__.py        # 导出两个 adapter
│       ├── serial.py          # pyserial-compatible bytes 边界适配
│       └── pyvisa.py          # message-based VISA resource 适配
└── tests/
    ├── conftest.py            # 启用 pytester
    ├── fakes.py               # FakeTransport 和测试文件构造辅助函数
    ├── cassettes/plugin.jsonl # 静态插件集成样例
    ├── test_cassette.py       # 好/坏 cassette 与行号
    ├── test_session.py        # 原子性、匹配、异常、消费、所有权
    ├── test_faults.py         # 五类故障、顺序、概率、坏计划
    ├── test_virtual.py        # 虚拟设备状态与测量模型
    ├── test_serial_adapter.py # bytes、termination、partial timeout 等
    ├── test_pyvisa_adapter.py # VISA 配置、timeout 状态和异常
    ├── test_pytest_plugin.py  # fixture 路径和 teardown 行为
    ├── test_cli.py            # main、退出码和 python -m
    └── test_demo.py           # 全链路 PASS 和重复运行
```

`src/` 布局表示源码不直接放在项目根目录的 import 路径上。测试前需要安装包或配置
import 路径，这能更早发现“忘记把文件打进 wheel”的问题。

### 5.2 架构图

```text
你的测试/应用
      │
      ▼
use_cassette()
      │
      ├── RecordSession ───────▶ 外部 transport
      │         │                     │
      │         ▼                     ├── VirtualPowerSupply
      │      临时 JSONL               ├── SerialTextAdapter ──▶ serial connection
      │         │                     └── PyVISAAdapter ─────▶ VISA resource
      │         ▼
      │    正常退出后原子发布 cassette
      │
      └── ReplaySession
                │
                ├── validate_cassette()
                ├── 可选 load_fault_plan()
                └── 顺序返回 response 或抛稳定通信错误

cassette.py 负责“文件是否合法”
session.py  负责“当前该消费哪条交互”
faults.py   负责“这条交互是否注入故障、注入什么”
errors.py   负责“错误属于哪一类”
```

### 5.3 为什么依赖方向重要

- `cassette.py` 不调用 session，否则文件格式和播放状态会缠在一起；
- `faults.py` 根据已经验证的 Exchange 做选择，不自己偷偷读硬件；
- `session.py` 组合 cassette、fault 和 transport，是核心协调者；
- CLI、demo 和 pytest 插件只调用核心，不复制一套匹配算法；
- 核心只依赖标准库；真实驱动是可选边界。

这样做的好处是：不安装 PyVISA 也能运行 demo，修改 CLI 不会意外改变回放匹配，
测试 faults 时也不需要真实设备。

### 5.4 公共 API 和内部实现

常见公共入口从 `benchvcr` 直接导入：

```python
from benchvcr import (
    CommunicationError,
    TextTransport,
    load_fault_plan,
    use_cassette,
    validate_cassette,
)
```

`__init__.py` 的 `__all__` 列出愿意公开的名称。以下划线开头的函数，例如
`_parse_exchange()`，是内部实现细节；学习源码可以读，但业务代码不应依赖它们稳定。

---

## 6. record：一次录制到底发生了什么

### 6.1 一个完整但最小的例子

```python
from pathlib import Path

from benchvcr import use_cassette
from benchvcr.virtual import VirtualPowerSupply

output = Path("demo-output/manual")
output.mkdir(parents=True, exist_ok=True)
path = output / "basic.jsonl"

supply = VirtualPowerSupply()
try:
    with use_cassette(path, mode="record", transport=supply, overwrite=True) as io:
        print(io.query("*IDN?"))
        io.write("VOLT 5")
        io.write("CURR 1")
        io.write("OUTP ON")
        print(io.query("MEAS:VOLT?"))
        print(io.query("MEAS:CURR?"))
finally:
    supply.close()
```

示例显式使用 `overwrite=True`，所以可以在学习时重复运行；业务测试若不希望替换旧
基线，应保持默认 False。

默认负载为 10 Ω，限流 1 A 不限制 5 V 输出，因此最后两个值分别是 `5.000000`
和 `0.500000`，不是 1 A。只有电压达到 `CURR × R = 10 V` 时才到限流边界。

### 6.2 `use_cassette` 参数

| 参数 | record | replay |
| --- | --- | --- |
| `path` | 必填，目标 cassette | 必填，已有 cassette |
| `mode` | `"record"`，也是默认值 | 必须显式写 `"replay"` |
| `transport` | 必须显式传入 | 禁止传入 |
| `fault_plan` | 禁止，录制阶段不注入 | 可选 JSON 路径或 FaultPlan |
| `overwrite` | 默认 False；True 才允许替换 | 不改变文件，无实际用途 |

没有 `auto` 模式。库不会根据 cassette 是否存在猜你想录制还是回放，也不会自动
打开串口。这些决定都必须由测试作者明确表达。

### 6.3 正常 record 的调用链

```text
with use_cassette(...)
  → RecordSession.__enter__
    1. 检查是否重复进入 session
    2. 如果目标已存在且 overwrite=False，拒绝
    3. 在目标目录创建隐藏临时文件
    4. 写 header，flush
    5. 记录 monotonic 起点

每次 io.write/query
  → RecordSession._run
    1. 确认 session 处于活动状态
    2. 检查 command 非空、是 str、无 CR/LF
    3. 读取开始时间
    4. 调用 transport.write/query
    5. query 若不是 str，转为 ProtocolError
    6. 把成功或稳定通信错误追加到临时文件
    7. flush，seq 加一
    8. 返回响应，或重新抛出通信错误

测试体正常结束
  → RecordSession.__exit__
    1. 关闭临时文件
    2. 再次检查默认不覆盖约束
    3. os.replace(临时文件, 目标文件)
    4. 标记 session 非活动
```

### 6.4 flush、临时文件和原子替换

**flush** 是把 Python 文件缓冲写给操作系统。逐条 flush 可以减少异常时仍留在用户态
缓冲里的数据，但它不等于 `fsync`，不承诺突然断电时数据已经持久化到物理磁盘。

**临时文件**类似草稿。如果测试中断，草稿可以删除，不影响旧 cassette。

**原子替换**使用 `os.replace(temp, target)`。临时文件与目标放在同一目录，避免跨文件
系统移动。对同一文件系统上的读者而言，目标从旧版本切换到新版本，而不是暴露一个
只写了一半的正式目标。

这仍不是“任何断电场景都绝对不丢数据”的数据库事务保证；本项目只承诺当前设计的
正常/异常退出和原子发布语义。

### 6.5 默认拒绝覆盖

```python
with use_cassette(path, transport=supply):
    ...
```

如果 `path` 已存在，进入 context 时就抛 `ConfigurationError`。要替换必须明确：

```python
with use_cassette(path, transport=supply, overwrite=True):
    ...
```

如果 overwrite=True 的录制体异常，旧目标仍保留，临时新文件删除。demo 为了方便
重复运行，明确使用 overwrite=True，只覆盖 demo 自己的产物。

### 6.6 通信错误怎样被录下来

假设某 transport 的 query 会超时，下面只演示捕获形式；正常虚拟电源不会自行产生
这次超时，测试里通常用 fake 精确制造：

```python
from benchvcr import CommunicationError

with use_cassette(path, transport=supply, overwrite=True) as io:
    try:
        io.query("MEAS:VOLT?")
    except CommunicationError:
        pass  # 明确告诉录制器：错误已处理，测试体可以正常结束
```

第一条会以 `ok=false`、稳定 error 写入；然后异常重新抛给调用方。因为调用方捕获了
它，context 最终正常退出，cassette 会发布。

如果没有捕获，异常逃出 `with` 测试体，录制器会删除临时文件。原因是：库无法判断
这个异常是否意味着整个测试失败，不能擅自把“失败测试的半成品”发布成可靠基线。

### 6.7 为什么不记录任意 Python 异常

`AssertionError` 可能表示测试断言失败，`TypeError` 可能表示代码写错。把它们伪装成
设备错误会误导诊断。

RecordSession 处理已知 `CommunicationError`，并把常见内置 `TimeoutError`、`OSError`
归一化。两个 adapter 负责把驱动异常转换成稳定类型。其他编程错误按测试体异常处理，
不应进入通信 cassette。

### 6.8 录制过程中资源不会被偷偷关闭

record 正常或异常退出都不会调用 `transport.close()`。session.close() 也不关闭它。
这让你可以在录制后继续显式使用设备，同时要求你记得在 finally 中关闭。

---

## 7. cassette JSONL：逐字段读懂录像带

### 7.1 JSON 和 JSONL

JSON 是常见数据格式，支持对象、数组、字符串、数字、布尔值和 null。
JSONL 是“每行一个完整 JSON 值”的文本格式。

本项目第一行是 header，后续每行是一条 exchange。好处是：

- 每行容易阅读和版本比较；
- 录制时可以逐条追加；
- 出错能指出具体行号；
- 不需要自定义二进制编辑器。

### 7.2 一个覆盖多种情况的手写示例

下面只是格式示例，不是虚拟电源支持的完整命令集：

```jsonl
{"format":"benchvcr","schema_version":1,"protocol":"text","library_version":"0.1.0","created_at":"2026-01-02T03:04:05Z"}
{"seq":0,"kind":"query","command":"*IDN?","at_ms":0.0,"duration_ms":0.2,"ok":true,"response":"example-device","error":null}
{"seq":1,"kind":"write","command":"*RST","at_ms":1.0,"duration_ms":0.1,"ok":true,"response":null,"error":null}
{"seq":2,"kind":"query","command":"EMPTY?","at_ms":2.0,"duration_ms":0.1,"ok":true,"response":"","error":null}
{"seq":3,"kind":"query","command":"LATE?","at_ms":3.0,"duration_ms":100.0,"ok":false,"response":null,"error":{"type":"timeout","message":"too slow"}}
```

JSON 类型与 Python 的大致对应：

| JSON | Python | 示例 |
| --- | --- | --- |
| object | dict | `{"type":"timeout"}` |
| array | list | `[1, 2]` |
| string | str | `"VOLT 5"` |
| number | int/float | `1`、`0.2` |
| true/false | bool | `true` |
| null | None | `null` |

### 7.3 header 字段

| 字段 | 当前值/类型 | 用途 |
| --- | --- | --- |
| `format` | `"benchvcr"` | 判断这是不是 BenchVCR cassette |
| `schema_version` | 整数 `1` | 判断字段规则版本 |
| `protocol` | `"text"` | 表示文本协议，不是将来的 binary |
| `library_version` | 非空字符串 | 记录写入库版本，例如 0.1.0 |
| `created_at` | UTC ISO-8601 字符串 | 记录文件创建的 wall-clock 时间 |

`Z` 表示 UTC。header 的时间用于审计，不参与 replay 匹配，也不能用来计算每条命令
的精确 monotonic 间隔。

### 7.4 exchange 字段

| 字段 | 人话解释 | 约束 |
| --- | --- | --- |
| `seq` | 第几条交互 | 从 0 开始连续递增 |
| `kind` | write 还是 query | 参与严格匹配 |
| `command` | 原始命令 | 非空、无 CR/LF、参与严格匹配 |
| `at_ms` | 相对录制起点的时间 | 有限、非负、不倒退 |
| `duration_ms` | 本次操作耗时 | 有限、非负 |
| `ok` | 是否成功 | 必须是 JSON true/false |
| `response` | 响应文本 | 见下面的组合矩阵 |
| `error` | 稳定错误对象 | 成功为 null，失败必须有 |

`at_ms` 和 `duration_ms` 的单位都是毫秒。1 秒 = 1000 毫秒。

### 7.5 合法字段组合矩阵

| 情况 | ok | response | error |
| --- | --- | --- | --- |
| 成功 write | true | 必须 null | 必须 null |
| 成功 query，普通响应 | true | 字符串 | 必须 null |
| 成功 query，空响应 | true | `""`，合法 | 必须 null |
| 失败 write/query | false | 必须 null | 必须有 type/message |

失败的 error 只有四种 type：timeout、disconnect、protocol、transport。error 对象必须
且只能包含：

```json
{"type": "timeout", "message": "too slow"}
```

不保存完整 traceback、异常模块路径或本机堆栈，这样文件更稳定，也减少敏感信息。

### 7.6 seq、文件行号、fault 的 at 是三个概念

以上述文件为例：

| 交互 | seq | 文件行号 | fault 中定位方式 |
| --- | ---: | ---: | ---: |
| `*IDN?` | 0 | 2 | `at: 0` |
| `*RST` | 1 | 3 | `at: 1` |
| `EMPTY?` | 2 | 4 | `at: 2` |
| `LATE?` | 3 | 5 | `at: 3` |

行号从 1 开始且包含 header；seq 从 0 开始且只计算 exchange。调试时不要把行号当 at。

### 7.7 校验器会拒绝什么

`validate_cassette(path)` 会在 replay 开始前完整读取并检查文件，包括：

- 文件为空、不是合法 UTF-8、JSON 语法错误；
- 顶层不是对象、重复 JSON key、重复 header；
- 不支持的 format、schema_version、protocol；
- 缺少字段或出现未知字段；
- seq 不连续、为负数或 bool；
- command 为空、含换行或不是字符串；
- 时间为负、非有限值或 at_ms 倒退；
- 上表中的 ok/response/error 组合不合法；
- error 类型未知、message 为空；
- NaN、Infinity 和额外空白行。

错误包含路径、行号和原因，例如：

```text
path/to/basic.jsonl:3: non-contiguous seq: expected 1, got 2
```

Python 的 bool 是 int 的子类，所以校验器显式排除 `true` 冒充整数 1。对于超大 JSON
整数，也会避免让内部 OverflowError 直接泄漏成难以理解的用户错误。

### 7.8 为什么一次性验证整个文件

如果只验证正在消费的那一行，测试可能执行到一半才发现末尾损坏，导致诊断顺序
混乱。当前实现先验证全部内容，再允许 replay 操作，让“文件不合法”和“调用不匹配”
保持清晰边界。

### 7.9 wall clock 和 monotonic 是两种不同的时钟

**wall clock（墙上时钟）**回答“现实世界中现在是什么日期和时间”。电脑校时、用户改
时间或时区配置都可能影响它。本项目的 `created_at` 使用 UTC wall clock，只表示文件
什么时候创建。

**monotonic clock（单调时钟）**回答“从某个内部起点经过了多少时间”。它适合测操作
间隔，不会因为系统日期被回拨而让 duration 突然变成负数。它不表示某年某月某日，
不同进程或机器上的原始数值也不能直接比较。

| 用途 | 使用什么 | 原因 |
| --- | --- | --- |
| 记录 cassette 创建时间 | `datetime.now(timezone.utc)` | 需要可阅读的 UTC 时间 |
| 计算 at_ms | `time.monotonic()` 与 session 起点之差 | 需要稳定相对间隔 |
| 计算 duration_ms | 操作前后 monotonic 之差 | 需要稳定耗时 |
| replay 是否等待/匹配 | 不使用上述时间 | 保持回放快速且确定 |

例如系统时间从 12:00 被校准回 11:59，不应该让一次通信耗时变成负数；单调时钟正是
为了避免这类问题。另一方面，monotonic 数值本身没有审计意义上的日期，所以不能
替代 created_at。

---

## 8. replay：严格顺序和消费语义

### 8.1 最小回放示例

replay 不创建 supply，也不需要安装任何硬件驱动：

```python
from benchvcr import use_cassette

with use_cassette("demo-output/manual/basic.jsonl", mode="replay") as io:
    print(io.query("*IDN?"))
    io.write("VOLT 5")
    io.write("CURR 1")
    io.write("OUTP ON")
    print(io.query("MEAS:VOLT?"))
    print(io.query("MEAS:CURR?"))
```

它依次检查第 6 章录制的命令，并返回录制响应。不能调换 `VOLT 5` 和 `CURR 1` 的
顺序，即使真实设备可能允许调换。

### 8.2 index 是什么

ReplaySession 内部有一个从 0 开始的 `_index`，表示“下一条应该消费哪个 exchange”。

```text
初始：index = 0
第 1 条匹配后：index = 1
第 2 条匹配后：index = 2
...
```

这里的“消费”不是删除文件内容，只是内存里的 index 向前走。cassette 文件完全不变。
session 还有活动/非活动生命周期：只有在 `with` 内才能 write/query，进入前或退出后
调用会抛 `SessionStateError`；同一个 session 也不能重复进入。

### 8.3 每次调用的精确步骤

```text
ReplaySession._run(kind, command)
  1. 检查 session 活动、command 合法
  2. 如果 index 已越过末尾：报 end-of-cassette mismatch
  3. 取 exchanges[index]
  4. 比较 kind 和原始 command
       不一致：CassetteMismatchError，index 不变
       一致：index += 1
  5. 检查并应用一条实际触发的 fault
  6. 如果原 exchange 是失败且未被 timeout/disconnect 替换：抛原稳定错误
  7. 否则返回原始或修改后的 response
```

先消费再抛通信错误，是为了让调用方捕获错误后继续下一条。匹配失败不消费，是为了
允许你修正错误后重试当前条。

### 8.4 mismatch 示例

假设下一条应为：

```text
seq=0, kind=query, command="*IDN?"
```

你却调用：

```python
io.write("*IDN?")
```

kind 不同，抛 `CassetteMismatchError`。调用下面命令也不匹配：

```python
io.query("*idn?")  # 大小写不同
io.query(" *IDN?")  # 多了前导空格
io.query("VOLT?")  # 完全不是当前命令
```

异常对象包含：

- `seq`；
- `expected_kind`、`expected_command`；
- `actual_kind`、`actual_command`。

因为 mismatch 没有消费，可以在修正后重试：

```python
from benchvcr import CassetteMismatchError

with use_cassette(path, mode="replay") as io:
    try:
        io.query("WRONG?")
    except CassetteMismatchError:
        pass
    print(io.query("*IDN?"))  # 仍可消费 seq 0
```

这个重试示例用于解释状态机，不建议业务测试随便吞掉 mismatch；多数情况下 mismatch
应该让测试失败，暴露脚本与基线不一致。

### 8.5 少调用和多调用

**少调用**：context 正常退出时仍有剩余 exchange，抛
`UnplayedInteractionsError`，其中 `remaining` 是剩余数量，`next_seq` 是下一条序号。

**多调用**：所有 exchange 已消费后又调用，抛 `CassetteMismatchError`，expected 显示
end of cassette。

如果测试体已经抛 AssertionError 等异常，退出时不会再追加 unplayed。这样你看到的是
真正的断言失败，而不是一个次生 teardown 错误。

### 8.6 录制的错误也可以继续消费

假设 cassette 有：

```text
seq 0：query A? → timeout
seq 1：query B? → "ok"
```

回放可以写：

```python
from benchvcr import TransportTimeoutError

with use_cassette(path, mode="replay") as io:
    try:
        io.query("A?")
    except TransportTimeoutError:
        pass
    assert io.query("B?") == "ok"
```

A? 已匹配，所以即使抛出 timeout 也已消费。若测试体不捕获并直接退出，则遵循“已有
异常不追加 unplayed”的规则。

### 8.7 时间不参与匹配

普通 replay 不会因为 `at_ms=1000` 就等待 1 秒，也不会要求实际执行耗时等于
`duration_ms`。匹配只看当前位置的 kind 和原始 command。

这样测试不会无意义地复制录制耗时；时间字段留给统计和将来的时间线展示。

---

## 9. fault plan：故障注入完整解释

### 9.1 fault plan 是什么

它回答三个问题：

1. 在哪个 exchange 上操作？—— `at` 和可选 `match`；
2. 做什么？—— `operation` 及其参数；
3. 一定触发还是按确定概率触发？—— `probability`。

基本格式：

```json
{
  "format": "benchvcr-fault-plan",
  "schema_version": 1,
  "seed": 42,
  "rules": [
    {
      "at": 0,
      "match": {"kind": "query", "command": "*IDN?"},
      "operation": "truncate",
      "length": 4,
      "probability": 1.0
    }
  ]
}
```

加载并回放：

```python
from benchvcr import load_fault_plan, use_cassette

plan = load_fault_plan("demo-output/fault-truncate.json")
with use_cassette(path, mode="replay", fault_plan=plan) as io:
    # 按原 cassette 顺序调用
    ...
```

`load_fault_plan` 主要做结构校验；规则是否在某条 exchange 上实际触发，要等 replay
到该条时才能确定。

### 9.2 plan 顶层字段

| 字段 | 含义 |
| --- | --- |
| `format` | 固定为 `benchvcr-fault-plan` |
| `schema_version` | 当前为 1 |
| `seed` | 整数种子，参与概率摘要 |
| `rules` | 有序规则数组，顺序会影响第一条实际触发规则 |

每条 rule 的 `at` 是 cassette 的零起始 seq，不是毫秒时间，也不是文件行号。
`rule_index` 是规则在 rules 数组中的零起始位置，只用于概率计算。

### 9.3 match 是额外精确过滤

下面两个字段都可省略：

```json
"match": {"kind": "query", "command": "MEAS:VOLT?"}
```

- 整个 match 省略：只看 at 和其他条件；
- 只写 kind：要求当前 exchange 类型相同；
- 只写 command：要求原始命令完全相同；
- 两者都写：两者都要满足。

当前没有正则、大小写忽略、空格规范化或乱序匹配。

### 9.4 规则选择算法

对当前 exchange，按 rules 数组顺序逐条检查：

1. `rule.at == exchange.seq`；
2. match.kind（若有）相等；
3. match.command（若有）完全相等；
4. 对 truncate/response_replace，当前必须是成功 query；
5. probability 抽样通过。

第一条全部满足的规则生效，后面的规则不再检查。每个 exchange 最多一个故障。

“第一条实际触发”很重要：前面的规则可能 at 不同、match 不同、操作不适用于 write，
或 probability 没通过，这时仍会继续检查后面的规则。

### 9.5 delay

```json
{"at": 8, "operation": "delay", "delay_ms": 25}
```

表示等待 25 ms，然后返回或抛出原本的结果。delay 可以作用于成功或失败 exchange。
例如原结果是 recorded timeout，那么先 sleep，再抛 recorded timeout。

测试不希望真的等待，所以 ReplaySession 接受内部可注入的 `sleep` 函数：

```python
from benchvcr import ReplaySession

sleeps = []
with ReplaySession(path, fault_plan=plan, sleep=sleeps.append) as io:
    ...

assert sleeps == [0.025]  # 对外 sleep 使用秒，plan 使用毫秒
```

普通 `use_cassette()` 回放使用 `time.sleep`。

### 9.6 timeout

```json
{"at": 5, "operation": "timeout"}
```

匹配并消费当前 exchange 后立即抛 `TransportTimeoutError("injected timeout")`，不会
先等待 duration_ms，也不会继续返回原响应。

### 9.7 disconnect

```json
{"at": 10, "operation": "disconnect"}
```

当前 exchange 抛 `DisconnectError("injected disconnect")`。它不模拟永久断线：调用方
捕获后，下一条仍可按 cassette 继续。

永久断线需要额外连接状态模型，当前明确不做。

### 9.8 truncate

```json
{"at": 0, "operation": "truncate", "length": 4}
```

只对成功 query 生效，按 Python 文本切片保留前 4 个字符：

```text
"BenchVCR" → "Benc"
"abc"      → "abc"（长度不足时保持原样）
""         → ""
```

它不是按 UTF-8 字节截断。Python 切片按 Unicode 代码点工作，也不保证等于人类肉眼
看到的“字素簇”数量；当前目标是简单、确定的文本故障。

如果 at 指向 write 或失败 query，这条规则不具备触发资格，不会硬改字段，也不会
伪装成硬件故障。

### 9.9 response_replace

```json
{"at": 9, "operation": "response_replace", "response": ""}
```

只对成功 query 生效，用给定字符串替换完整响应。空字符串合法，因此可以测试“设备
返回空文本”这一边界，而不是把它误当 null 或通信错误。

### 9.10 probability：确定的概率，不是随便随机

如果 probability 省略，默认 1，必然触发。0 表示永不触发，0.5 表示摘要样本小于
0.5 时触发。

当前算法输入是：

```text
benchvcr:v1:{seed}:{seq}:{rule_index}
```

步骤：

1. 对上述 ASCII 文本计算 SHA-256；
2. 取摘要前 8 字节；
3. 按无符号大端整数解释；
4. 除以 `2**64`，得到 `[0, 1)` 范围内的 sample；
5. `sample < probability` 时触发。

“8 字节”就是 64 bit。“无符号”表示不把它解释为负数；“大端”表示第一个字节放在
整数的最高位权重。SHA-256 在这里用于取得稳定摘要，不是在声明这条故障通道具有
加密或认证能力。

固定测试向量之一：

```text
seed=42, seq=0, rule_index=0
sample=0.7021687785852937
```

所以这条规则 probability=0.7 不触发，0.703 会触发。

为什么不用 Python `random`？因为无状态 SHA-256 更容易保证：不同进程、机器和 Python
版本上，只要 seed、seq、rule_index 相同，结果就相同。它不会受之前调用过多少次
random 的影响。

这里的“概率”不是保证少量样本中恰好有固定比例触发，而是定义了一个确定阈值。
同 seed 可复现也不表示 cassette 的 created_at 或录制耗时相同。

### 9.11 配置错误不是硬件错误

下面这些是 `ConfigurationError`：

- operation 未支持；
- at 为负或不是整数；
- delay_ms 为负；
- truncate.length 为负或不是整数；
- response_replace.response 不是字符串；
- probability 超出 `[0, 1]`；
- match 含未知字段；
- JSON/UTF-8 非法。

这类错误应在测试配置阶段暴露，不能转成 timeout 让使用者误以为设备坏了。

record 模式传 fault_plan 也会被拒绝：当前先录制真实结果，再在 replay 注入，避免
把“录制时故障”和“回放时故障”混为一谈。

---

## 10. 虚拟电源：逐条理解 virtual.py

### 10.1 默认状态

```python
supply = VirtualPowerSupply()
```

等价于：

```text
load_ohms = 10.0       # 固定负载，可构造时改为其他正有限值
voltage_set = 0.0
current_limit = 0.1
output_enabled = False
_closed = False
```

`*RST` 会恢复电压、限流和输出开关，但不会改变构造时给定的 load_ohms。

### 10.2 测量模型

输出关闭时：

```text
测量电压 = 0
测量电流 = 0
```

输出开启时：

```text
测量电压 = min(voltage_set, current_limit × load_ohms)
测量电流 = 测量电压 / load_ohms
```

例 1：电压受限流影响。

```text
VOLT 12
CURR 0.5
OUTP ON
R = 10 Ω
限流对应电压 = 0.5 × 10 = 5 V
MEAS:VOLT? → 5.000000
MEAS:CURR? → 0.500000
```

例 2：未达到限流边界。

```text
VOLT 5
CURR 1
OUTP ON
限流对应电压 = 1 × 10 = 10 V
MEAS:VOLT? → 5.000000
MEAS:CURR? → 0.500000
```

所有数值查询固定六位小数，没有随机噪声，重复查询结果一致。

### 10.3 非法命令为什么不改状态

实现先解析和验证，再赋值。例如 `VOLT nope` 不能转 float，`VOLT -1` 和 `VOLT 31`
超出 `[0, 30]`，`CURR` 允许 `[0, 5]`，`OUTP MAYBE` 不在 ON/OFF/1/0 中。

这些情况抛 `ProtocolError`，不会先把状态改一半再发现错误。测试会先保存
`(voltage_set, current_limit, output_enabled)`，再确认失败后完全相同。

### 10.4 close 的含义

`close()` 只把虚拟设备标记为关闭，重复 close 安全。之后 write/query 都抛
`DisconnectError`。这用于验证所有权和断连错误，不模拟真实设备的永久硬件损坏。

---

## 11. 两个 adapter：连接真实驱动世界的薄边界

### 11.1 为什么 adapter 要“薄”

adapter 应该只做：

- 编码/解码；
- termination；
- write/query 调用；
- timeout 和底层异常归一化；
- close 委托。

它不负责 cassette 顺序、fault 选择或业务断言。逻辑越薄，越容易用 fake 验证，也越少
把某个驱动差异带进核心。

### 11.2 SerialTextAdapter 的 write

典型使用：

```python
import serial

from benchvcr.adapters import SerialTextAdapter

connection = serial.Serial("/dev/ttyUSB0", baudrate=9600, timeout=0.2)
io = SerialTextAdapter(
    connection,
    encoding="utf-8",
    write_termination="\n",
    read_termination="\n",
)
```

`write("VOLT 1")` 的步骤：

1. 用指定 encoding 把 command 编成 bytes；
2. 追加 write_termination 的 bytes；
3. 调用 connection.write(payload)；
4. 如果返回写入数量且小于 payload 长度，抛 TransportError（short write）。

`/dev/ttyUSB0` 只是示例路径，实际端口依操作系统和设备而定；本项目没有自动访问它。

### 11.3 SerialTextAdapter 的 query

query 先 write，再循环 read：

```text
buffer = 空
反复 connection.read(read_chunk_size)
  → 返回空 bytes？
       是：buffer 为空 → 普通 timeout
           buffer 非空 → partial-response timeout
  → 返回非 bytes → ProtocolError
  → 追加到 buffer
  → 找到 read_termination？
       否：继续读
       是：如果终止符后还有多余 bytes，报 ProtocolError
           否则去掉终止符并 decode，返回 str
```

默认 read_chunk_size=1，简单且不会一次多读很多字节。若配置更大的块，adapter 不会
把“完整响应后的额外数据”悄悄丢掉，因为当前没有多响应/下一次读取缓冲模型。

### 11.4 PyVISAAdapter

典型形式：

```python
import pyvisa

from benchvcr.adapters import PyVISAAdapter

manager = pyvisa.ResourceManager()
resource = manager.open_resource("你的 resource 字符串")
io = PyVISAAdapter(resource, timeout_ms=500)
```

构造器可设置：

- `resource.timeout`，单位 ms；
- `write_termination`；
- `read_termination`；
- `encoding`。

对应参数传 None 时不覆盖原 resource 配置。query 使用 resource.query(command)，write
使用 resource.write(command)。

明确的 VISA `VI_ERROR_TMO = -1073807339` 映射为 TransportTimeoutError；其他异常通常
映射为 TransportError，query 返回非 str 则是 ProtocolError。

### 11.5 可选依赖为什么不隐式导入

核心环境和 demo 不要求安装 pyserial/PyVISA。adapter 模块只接收兼容对象，不执行
`import serial` 或 `import pyvisa`。应用自己创建对象时才导入所选驱动。

这带来三个好处：

1. demo/validate 在无驱动环境可运行；
2. fake 可以遵守同一对象契约；
3. 不会因为你只查看 cassette 就尝试加载本机 VISA 库。

可选安装入口是 `benchvcr[serial]` 和 `benchvcr[pyvisa]`。

### 11.6 fake、虚拟设备和真实设备不是一回事

| 类型 | 目的 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| fake | 按测试脚本返回数据或抛异常 | wrapper 对契约的处理 | 驱动/硬件真实行为 |
| VirtualPowerSupply | 有固定状态的协议模型 | 端到端工具和协议逻辑 | 真实电气/固件行为 |
| PyVISA-sim | 模拟 VISA 后端 | VISA 调用集成的一部分 | 真实仪器兼容性 |
| 真实设备 | 实际硬件和链路 | 指定型号、环境下的真实验证 | 其他未测型号普遍兼容 |

测试报告必须说明用了哪一种，不能混用“仿真通过”和“实机通过”。

---

## 12. pytest 插件：fixture、entry point 和 finalizer

### 12.1 pytest 基础

一个简单测试：

```python
def test_addition():
    assert 1 + 1 == 2
```

pytest 发现 `test_*.py` 文件和 `test_*` 函数，执行其中的 assert。失败时抛
AssertionError 并报告。

**fixture** 是 pytest 注入测试函数的共享辅助对象。测试函数参数名与 fixture 名相同
即可获得它：

```python
def test_identity(benchvcr_replay): ...
```

**插件**可以向 pytest 注册 fixture。BenchVCR 通过 pyproject 的 `pytest11` entry point
声明插件；安装包后，pytest 能发现 `benchvcr.pytest_plugin`。

### 12.2 fixture 怎样定位 cassette

目录示例：

```text
tests/
├── test_example.py
└── cassettes/
    └── identity.jsonl
```

测试写法：

```python
def test_identity(benchvcr_replay):
    with benchvcr_replay("identity.jsonl") as io:
        assert io.query("*IDN?") == "expected identity"
```

`benchvcr_replay` 本身是一个 fixture，它返回一个 factory（小工厂函数）。调用 factory
时，将相对名字拼到“当前测试文件所在目录/cassettes/”下，返回 ReplaySession。

它不是相对于你启动 shell 的当前目录，因此从不同目录运行 pytest 仍能找到同一文件。
绝对路径会被拒绝。

### 12.3 为什么必须显式 `with`

下面的代码只是创建 session，不进入 replay：

```python
benchvcr_replay("identity.jsonl")
```

正确写法是：

```python
with benchvcr_replay("identity.jsonl") as io:
    ...
```

消费检查由 ReplaySession 的 context exit 完成。fixture 自己不在 finalizer 再检查一次。

### 12.4 finalizer 是什么，为什么这里不做消费检查

finalizer 是 fixture 在测试结束后执行的清理逻辑。如果 fixture 在 finalizer 再检查
unplayed，可能产生两个问题：

1. 测试体已有 AssertionError，又被 finalizer 的新异常掩盖；
2. context exit 已检查过，teardown 再报一次造成重复和混乱。

所以当前插件没有 yield 式清理，也没有全局 record 开关、自动命名或隐式硬件创建。
录制必须回到公共 API，显式传 transport。

---

## 13. CLI 和 demo：组合层怎样工作

### 13.1 CLI 是什么

CLI 是命令行接口。本项目支持：

```bash
benchvcr demo --output-dir demo-output --seed 42
benchvcr cassette validate path/to/file.jsonl
python -m benchvcr cassette validate path/to/file.jsonl
```

`cli.py` 使用标准库 argparse 解析子命令。`__main__.py` 把 `python -m benchvcr`
转交给同一个 `main()`，避免维护两套逻辑。

### 13.2 stdout、stderr 和退出码

- **stdout**：正常结果，例如 PASS、OK；
- **stderr**：用户错误，例如文件不存在或 cassette 非法；
- **退出码 0**：成功；
- **退出码 2**：参数或预期用户错误。

预期用户错误只打印一行简短信息，不输出长 traceback。未被识别为预期用户错误的
编程缺陷不会被 CLI 随便伪装成设备故障。

### 13.3 demo 的 13 条交互

| seq | kind | command | 原预期结果 |
| ---: | --- | --- | --- |
| 0 | query | `*IDN?` | 固定身份字符串 |
| 1 | write | `*RST` | None |
| 2 | write | `VOLT 12` | None |
| 3 | write | `CURR 0.5` | None |
| 4 | write | `OUTP ON` | None |
| 5 | query | `VOLT?` | `12.000000` |
| 6 | query | `CURR?` | `0.500000` |
| 7 | query | `OUTP?` | `1` |
| 8 | query | `MEAS:VOLT?` | `5.000000` |
| 9 | query | `MEAS:CURR?` | `0.500000` |
| 10 | write | `OUTP OFF` | None |
| 11 | query | `MEAS:VOLT?` | `0.000000` |
| 12 | query | `MEAS:CURR?` | `0.000000` |

因为 0.5 A × 10 Ω = 5 V，所以 seq 8/9 展示限流模型。

五份 fault plan 分别位于：

| fault | at | 预期 |
| --- | ---: | --- |
| delay | 8 | 等待 1 ms 后仍得到 `5.000000` |
| timeout | 5 | 捕获注入 timeout，然后继续后续交互 |
| disconnect | 10 | 在 write 上捕获断连，然后继续 |
| truncate | 0 | 身份响应截成 `Benc` |
| response_replace | 9 | 响应替换为空字符串 |

每个 fault 都单独完整回放，确保它实际触发，同时其他 exchange 仍满足原结果。
最后重新计算 cassette SHA-256，确认所有 replay 都没改文件。

重复运行 demo 会重新 record，因此新文件的 created_at 可能不同，文件 hash 也可能
不同。“hash 不变”指同一次 demo 中各次 replay 前后不变，不是不同录制之间 hash
永远相同。

---

## 14. 异常体系：看到错误时先判断是哪一层

### 14.1 层级图

```text
Exception
└── BenchVCRError
    ├── ConfigurationError
    ├── SessionStateError
    ├── CassetteError
    │   ├── CassetteValidationError
    │   ├── CassetteMismatchError
    │   └── UnplayedInteractionsError
    └── CommunicationError
        ├── TransportTimeoutError
        ├── DisconnectError
        ├── ProtocolError
        └── TransportError
```

### 14.2 每类错误应该怎样理解

| 异常 | 谁在违反什么 | 常见处理 |
| --- | --- | --- |
| ConfigurationError | API 参数或 fault plan 配置错误 | 修正配置，不要当设备故障 |
| SessionStateError | 在 context 外使用 session，或重复进入 | 修正 with 生命周期 |
| CassetteValidationError | 文件不符合 schema | 看路径、行号、reason |
| CassetteMismatchError | 当前调用不是下一条录制交互 | 对照 expected/actual，检查顺序和原始命令 |
| UnplayedInteractionsError | 正常退出时少调用了 | 补齐脚本或更新有意的基线 |
| CommunicationError | 通信结果或其稳定回放 | 根据测试目的捕获或让测试失败 |

普通 `ValueError` 也可能用于非法 command 或 adapter 构造参数，因为那是直接编程
输入错误，不属于 cassette schema。

### 14.3 稳定错误对象

`CommunicationError.as_dict()` 产生：

```python
{"type": "timeout", "message": "..."}
```

`error_from_dict()` 再把已经验证的 JSON 对象转回对应异常类。回放因此不需要原来的
驱动、异常模块或 traceback。

`ProtocolError` 在这里是通信数据/使用方式错误，不是 Python Protocol 类型定义错误；
要结合上下文区分。

---

## 15. 测试体系：为什么需要这么多测试文件

### 15.1 测试金字塔中的不同问题

- **单元测试**：一个函数/状态机分支是否正确；
- **契约测试**：fake 驱动对象与 adapter 之间的约定是否被遵守；
- **静态集成测试**：真实插件读取固定 cassette 是否正确；
- **端到端测试**：record → replay → fault → CLI 能否串起来；
- **打包验收**：wheel 安装后是否仍能 import 和执行 entry point。

“端到端”在这里仍只到虚拟设备，不是实机端到端。

### 15.2 FakeTransport 怎样工作

`tests/fakes.py` 中的 FakeTransport 预先接收 Step 列表：

```python
Step("query", "A?", "a")
Step("query", "B?", error=TransportTimeoutError("late"))
```

每次调用时它检查 kind 和 command，再返回预定 response 或抛 error。它还能记录 calls
和 closed 状态，因此可以验证：

- 命令有没有原样传递；
- 错误有没有被录制并重新抛出；
- session 有没有错误地关闭外部 transport；
- 调用次数是否超出预期。

fake 不需要模拟欧姆定律，它只是脚本化合作者。

### 15.3 为什么坏文件要直接构造

正常录制器不应该生成 seq 断裂、负时间或非法 response，所以要测试 validator 的拒绝
能力，必须直接写字节或 JSON 文本。

参数化测试把多组“输入 + 预期错误原因”放在同一测试函数中，覆盖正常、异常和边界：
空文件、非法 UTF-8、重复 key/header、未知字段、空响应、超大整数等。

### 15.4 每个测试文件重点

| 文件 | 重点回答的问题 |
| --- | --- |
| test_cassette.py | 每种合法/非法字段组合是否被正确识别，行号是否准确 |
| test_session.py | 原子性、覆盖、严格匹配、消费、异常优先级和所有权是否正确 |
| test_faults.py | 五类故障、资格、顺序、概率向量和坏配置是否确定 |
| test_virtual.py | 设置、复位、测量、非法命令和 close 是否正确 |
| test_serial_adapter.py | termination、非 strip、短写、partial timeout、异常映射是否正确 |
| test_pyvisa_adapter.py | resource 配置、明确 VISA timeout 和非文本响应是否正确 |
| test_pytest_plugin.py | 相对路径、显式 with、无 finalizer 掩盖是否正确 |
| test_cli.py | 成功输出、用户错误、退出码和模块入口是否正确 |
| test_demo.py | 所有 PASS 阶段和重复运行是否正确 |

### 15.5 pytester 和 subprocess

**pytester** 用来在测试中再运行一套临时 pytest 测试，适合验证插件行为。例如：
测试体断言失败时，输出中不应出现额外的 UnplayedInteractionsError。

**subprocess** 是启动新的 Python 进程。`python -m benchvcr` 必须这样验证才更接近
真实命令行使用，同时能检查 returncode、stdout 和 stderr。

### 15.6 覆盖率是什么

语句覆盖率表示多少语句执行过；分支覆盖率还关心 if 的 True/False 两条路是否都走。
100% 覆盖率也不等于没有 bug，它只说明代码被执行，不证明所有业务场景都正确。

本项目覆盖率命令使用：

```bash
coverage run --source=src/benchvcr --branch -m pytest -q
coverage report -m
```

从解释器启动时开始收集，可以避免 pytest entry point 提前 import 包导致 import 语句
被误算为未覆盖。当前门槛是 90%，本地实际为 94%。

### 15.7 本地、CI 和实机验证的区别

- 本地：开发者机器实际执行，当前是 macOS + Python 3.12.16；
- CI 配置：声明 Ubuntu/Windows/macOS 与 Python 3.10/3.13 应执行什么；
- 远端 CI 通过：必须有真实远端运行记录，当前没有；
- 实机通过：必须记录设备、驱动、termination、timeout 和环境，当前没有。

跨平台 CI 主要防止路径、换行、文件替换、Python 版本和标准库差异，不能替代硬件
兼容性测试。

---

## 16. 打包、开发工具和隔离环境

### 16.1 uv、pip、venv 分别做什么

- **venv**：创建独立 Python 环境，避免包装到系统 Python；
- **pip**：常见 Python 包安装工具；
- **uv**：可管理 Python、虚拟环境和依赖的工具，本项目用它准备本地环境；
- **项目隔离**：uv 本身、Python、缓存、`.venv`、wheel 验收环境都放项目目录内。

项目当前相关目录：

```text
.tools/       # 本地 uv 等工具
.python/      # uv 管理的 Python 3.12
.cache/       # uv 缓存
.venv/        # 开发环境
.wheel-venv/  # 隔离安装 wheel 的验收环境
```

它们都被 `.gitignore` 忽略，不应该打进源码包。

### 16.2 pyproject.toml 的各部分

- `[build-system]`：使用 hatchling 构建；
- `[project]`：包名、版本、Python 要求、MIT、核心依赖；
- `[project.optional-dependencies]`：serial、pyvisa、dev extras；
- `[project.scripts]`：注册 `benchvcr` 命令；
- `[project.entry-points.pytest11]`：注册 pytest 插件；
- `[tool.pytest.ini_options]`：测试目录和严格配置；
- `[tool.coverage.*]`：source、branch 和覆盖率门槛；
- `[tool.ruff*]`：lint、格式和本地目录排除；
- `[tool.mypy]`：严格类型检查；
- `[tool.uv]`：项目内缓存和 Python 安装位置。

“extra” 是可选依赖组，例如：

```bash
python -m pip install -e ".[dev]"
```

核心 `dependencies = []` 表示运行 record/replay/fault 不需要第三方运行时依赖。

### 16.3 entry point 是什么

entry point 是包向环境公开的可发现入口。

console script：

```toml
benchvcr = "benchvcr.cli:main"
```

安装后生成 `benchvcr` 命令。

pytest 插件：

```toml
[project.entry-points.pytest11]
benchvcr = "benchvcr.pytest_plugin"
```

pytest 通过 `pytest11` 组发现插件。只有源码存在但未正确安装时，这些入口可能不生效，
所以要做 wheel 隔离安装验收。

### 16.4 editable install 和普通安装

```bash
python -m pip install -e ".[dev]"
```

editable install 让源码修改直接反映到环境中，适合开发。普通 wheel 安装把构建后的
文件复制到 site-packages，更接近用户实际使用。

只做 editable 测试可能掩盖漏打包文件，所以项目还构建 wheel，并在 `.wheel-venv`
中安装后运行 CLI。

### 16.5 wheel、sdist 和 site-packages

- **wheel**：构建分发格式（常叫 binary distribution），本项目是纯 Python 的
  `py3-none-any` wheel，不包含机器码；
- **sdist**：源码分发包；
- **site-packages**：虚拟环境中第三方包安装位置。

wheel 文件名中的 `py3-none-any` 表示 Python 3、无特定 ABI、平台无关，不表示所有
Python 版本都支持；`requires-python >=3.10` 仍有限制。

`py.typed` 是 PEP 561 标记，告诉 mypy 等工具可以使用包内类型标注。

### 16.6 Ruff、mypy 和 build 的分工

- `ruff check .`：静态 lint，发现 import 顺序、可疑写法等；
- `ruff format --check .`：检查格式，不检查业务正确性；
- `mypy src/benchvcr`：根据类型标注检查类型一致性；
- `python -m build`：生成 sdist/wheel；
- `pip check`：检查当前环境已安装包的依赖是否冲突或缺失。

它们都不能替代 pytest，更不能替代真实硬件验证。

### 16.7 常用验收命令

在项目根目录运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m coverage run --source=src/benchvcr --branch -m pytest -q
.venv/bin/python -m coverage report -m
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/benchvcr
.venv/bin/python -m build
.venv/bin/python -m pip check
```

上面的可执行文件路径适用于 macOS/Linux；Windows venv 通常使用
`.venv\\Scripts\\python.exe`，Ruff/mypy 也位于 `.venv\\Scripts\\`。

uv 创建的 venv 默认可能没有 pip，可以用项目环境内的：

```bash
.venv/bin/python -m ensurepip --upgrade
```

---

## 17. 逐文件源码阅读地图

这一章用于真正打开代码，不再只讲概念。

### 17.1 `errors.py`

先看 BenchVCRError，再看三组错误：配置/session、cassette、通信。重点观察：

- CassetteValidationError 保存 path、line、reason；
- CassetteMismatchError 保存 expected/actual 结构化字段；
- CommunicationError 子类用 class variable `kind` 对应 JSON type；
- `_ERROR_TYPES` 把稳定文本类型映射回异常类。

调试建议：不要只看异常字符串，打印异常类型和字段。

### 17.2 `transport.py`

文件很短，却是依赖倒置的关键：session 依赖抽象方法，不依赖 pyserial/PyVISA 类。

### 17.3 `cassette.py`

建议顺序：

1. CassetteHeader、Exchange、Cassette 三个 dataclass；
2. `Exchange.as_dict()` 的 JSON 字段；
3. `_parse_json_object()` 如何处理 duplicate key 和非标准数字；
4. `_parse_header()` 和 `_parse_exchange()`；
5. `validate_cassette()` 如何维护 expected_seq 和 previous_at；
6. `json_line()` 如何序列化。

关键断点：`_parse_exchange`。准备一份坏文件，观察它在哪个字段检查失败。

### 17.4 `session.py`

先看 `use_cassette()` 的参数分流，再看两个 session。

RecordSession：

- `__enter__`：默认覆盖、临时文件、header；
- `_run`：transport 调用和异常归一化；
- `_append`：seq、时间、成功/错误字段和 flush；
- `_discard`：异常清理；
- `__exit__`：正常发布与异常删除。

ReplaySession：

- `__enter__`：完整 cassette 校验和 fault plan 加载；
- `_run`：mismatch、index 前进、fault 和 recorded error；
- `__exit__`：正常退出 unplayed，异常退出不追加错误。

关键观察变量：`_active`、`_seq`、`_index`、`_temp_path`。

### 17.5 `faults.py`

先看 FaultMatch、FaultRule、FaultPlan 数据结构，再看：

1. `FaultPlan.rule_for()` 的资格过滤；
2. `probability_sample()` 的输入字符串和 digest；
3. `apply_fault()` 的五类操作；
4. `load_fault_plan()` 和各 `_parse_*` 的结构校验。

注意“结构合法”与“对当前 exchange 有资格”是不同阶段。

### 17.6 `virtual.py`

按 write/query 两条路径读。重点看：

- 先验证后赋值；
- `_measurements()` 的限流公式；
- query 固定分支和格式化；
- close 后的 DisconnectError。

### 17.7 `adapters/serial.py`

沿 write 和 query 读。重点看 buffer、termination、空 read、partial timeout、short write
和 `_normalize()`。注意所有 close 都由 adapter 显式委托，而不是 session 隐式触发。

### 17.8 `adapters/pyvisa.py`

看构造器设置 resource 属性，再看 query/write 的异常映射。重点理解为什么用
status_code 判断 VISA timeout，而不是搜索错误消息里有没有“timeout”。

### 17.9 `demo.py` 和 `cli.py`

先看 OPERATIONS，再看 `_exercise()` 如何验证正常和故障预期。`_fault_cases()` 给出五类
故障的位置。`run_demo()` 是完整编排。

`cli.py` 只负责解析、调用和把预期用户错误变成 stderr/退出码，不复制业务逻辑。

### 17.10 `pytest_plugin.py` 和 `__main__.py`

前者只有相对路径 factory；后者只把模块执行转交 cli.main。小文件往往体现了边界：
简单组合层不应该藏核心状态。

---

## 18. 调试方法：从现象定位到模块

### 18.1 常用命令

```bash
.venv/bin/python -m pytest tests/test_session.py -x --pdb
.venv/bin/python -m pytest tests/test_faults.py::test_fixed_probability_vectors -vv
.venv/bin/python -m benchvcr cassette validate path/to/file.jsonl
.venv/bin/python -m benchvcr demo --output-dir demo-output/debug --seed 42
```

`-x` 表示第一个失败后停止，`--pdb` 在失败处进入调试器，`-vv` 显示更详细参数。

### 18.2 现象到断点

| 现象 | 优先断点/检查 |
| --- | --- |
| 文件被拒绝 | `_parse_header`、`_parse_exchange`，看 line/reason |
| 录制后目标不存在 | RecordSession `__exit__`，测试体是否异常逃出 |
| 旧文件被保留 | overwrite 是否为 False，或录制体是否异常 |
| mismatch | ReplaySession `_run`，比较 index、expected、actual |
| timeout 后下一条错位 | 确认匹配项已消费，检查脚本是否重复调用 |
| fault 不触发 | FaultPlan.rule_for，逐条看 at、match、资格、probability |
| delay 后仍 timeout | 检查原 exchange 是否是 recorded error |
| serial 一直 timeout | 看 read bytes、termination 和 buffer，不要先改 session |
| unplayed 覆盖断言 | 当前实现不应如此，检查是否另有 fixture finalizer |
| wheel 命令不存在 | 检查 project.scripts、安装环境和 entry point |

### 18.3 用 hash 检查文件是否变化

在 replay 前后对原始 bytes 算 SHA-256：

```python
import hashlib
from pathlib import Path

before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
# replay
# ...
after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
assert before == after
```

不要只比较重新 dumps 的 JSON，因为格式化和键顺序变化可能掩盖原始文件变化。

---

## 19. 设计取舍：为什么有些事故意不做

### 19.1 为什么严格匹配，而不是“尽量猜”

测试工具如果悄悄忽略顺序或空格差异，可能让过时测试假通过。v1 选择简单、可解释的
严格规则。将来增加匹配能力也必须显式 opt-in，并处理 schema 兼容。

### 19.2 为什么不自动录制/自动连接硬件

auto 模式容易让测试在本该 replay 时意外访问设备，既不确定也不安全。显式 transport
和 mode 能让 reviewer 一眼看出硬件边界。

### 19.3 为什么不自动等待录制耗时

测试目标是验证交互逻辑，不是复制一次人工操作的时间。时间保留为观测元数据，
只有 delay fault 明确等待。

### 19.4 为什么不永久断线、不组合故障

当前规则是一条 exchange 一个故障，disconnect 也只影响当前项。永久连接状态和组合
故障需要定义后续交互、恢复和优先级，贸然加入会让语义含糊。

### 19.5 为什么核心只使用标准库

这样 cassette validate、demo 和核心回放可以在最小环境运行。驱动集成通过 adapter
隔离，pytest 通过插件入口隔离。

### 19.6 为什么实机是 v1.0 门槛

文本协议 fake 做得再多，也无法覆盖真实 termination 差异、驱动 timeout、线缆、固件
和电气环境。稳定发布必须知道哪些声明有实测依据。

---

## 20. TODO 中未来概念预告

这些功能当前没有实现，但学习笔记解释它们的目的是避免只背功能名。

- **离线 HTML 时间线**：把 seq、at_ms、duration_ms 画成单个 HTML。cassette 文本必须
  安全转义，否则 `</script>` 等内容可能造成 HTML/JavaScript 注入。
- **cassette stats/diff**：stats 统计交互，diff 比较两个基线。默认不应把时间差当作
  协议不匹配。
- **OpenHTF**：硬件测试框架，包含 phase（测试阶段）和 plug（可插拔资源）等概念。
  集成应是 optional extra，不能污染核心依赖。
- **正则匹配**：更灵活，但可能带来歧义和 catastrophic backtracking（恶意输入导致
  极长匹配时间），必须明确限制。
- **长度前缀二进制帧**：消息开头用固定宽度整数表示 body 长度。要定义字节序、最大
  长度，并测试短读、非法长度和多余字节。
- **CRC**：循环冗余校验，用于发现部分传输错误，不等于安全加密。
- **CAN/Modbus/I²C/SPI**：不同总线或协议，各有帧和事务语义，当前都不支持。
- **schema migration/deprecation**：文件格式迁移和 API 弃用策略。不能悄悄改变 v1
  字段类型后仍声称完全兼容。
- **语义化版本**：通过主版本、次版本、修订号表达兼容含义，但版本号本身不替代
  明确策略和测试。

---

## 21. 循序渐进练习

### 练习 0：手工制造一次 mismatch

目的：理解 index 不消费和错误字段。

1. 运行第 6 章录制例子。
2. 在 replay 中把第二条改成 `VOLT 6`，观察 CassetteMismatchError。
3. 打印 seq、expected_command、actual_command。
4. 捕获错误后改回 `VOLT 5`，确认当前条仍能消费。
5. 思考：为什么这种“捕获后继续”适合学习状态机，却不一定是好业务测试？

### 练习 1：新增 `MEAS:POW?`

任务：返回测量功率，六位小数；输出关闭时为零。

前置知识：第 3.1、10 章。

参考思路：

1. 先在 test_virtual.py 写“限流状态”和“输出关闭”测试。
2. 复用 `_measurements()` 得到测量 V/I，再计算 `V * I`。
3. 不要用 voltage_set × current_limit，否则限流时错误。
4. 不需要改 cassette schema，因为仍是一条成功 query 字符串。
5. 如果加入 demo，注意新增 seq 会改变后续 fault 的 at。

验收：`VOLT 12`、`CURR 0.5`、10 Ω 时测量值为 5 V、0.5 A，所以功率为
`2.500000` W；关闭输出后为 `0.000000`。

### 练习 2：新增 `cassette stats`

任务：输出 exchange 数、write/query 数、成功/失败分类和耗时统计。

参考思路：

1. 先定义空 cassette 输出和文本/JSON 格式。
2. 新函数接收已验证的 Cassette，不要再次自行解析 JSON。
3. CLI 只负责 validate、调用统计函数和打印。
4. duration 合计/最大值与 at_ms 首末值要区分；空集合不要除零。
5. 非法文件继续走统一 stderr 和退出码 2。

验收：空文件、混合错误、空响应、非 ASCII、坏时间文件都有测试；同文件重复输出
逐字一致；不要把统计时间称为 wall-clock 测试耗时。

### 练习 3：扩展 fault 序号匹配

任务：希望一个规则命中多个 seq 或区间。

先回答兼容问题：

- 旧 reader 看到数组形式的 at 会怎样？
- 新增 at_any/at_range 是否会被旧 reader 的未知字段检查拒绝？
- 概率输入是否仍使用实际 exchange.seq？
- rules 顺序和“最多一个故障”是否保持？

参考思路：不要悄悄让 v1 at 同时接受整数和数组。可以设计 schema v2 和迁移策略，
或在有正式 feature 协商后增加可选字段。每个实际 exchange 仍以自己的 seq 参与
SHA-256。

验收：重复序号、空列表、倒序区间、超大整数、规则顺序、旧 v1 文件和固定概率向量
都有测试。

### 练习 4：安全的离线 HTML 时间线

任务：生成无 CDN、无网络请求的单个 HTML。

参考思路：

1. 先写恶意输入测试：`</script><script>alert(1)</script>`、引号、`&`、`<`、`>`、
   U+2028/U+2029。
2. HTML 文本节点使用 html.escape；属性还要处理引号。
3. 最简单方案是生成静态文本/DOM，不把原始字段放进可执行 script。
4. 若嵌入 JSON，至少处理 `<`、`>`、`&` 和 Unicode 行分隔符，不能用 innerHTML
   渲染原始值。
5. 时间轴使用 seq、at_ms、duration_ms，不从 created_at 推每条 monotonic 时间。

验收：恶意字符串只显示为文本；空文件、长响应、错误项、非 ASCII 和 Windows 路径
测试通过；没有外部资源请求。

### 练习 5：OpenHTF 薄集成

任务：让 OpenHTF phase 显式使用 BenchVCR transport。

参考思路：

1. 先确认目标 OpenHTF 版本的 phase/plug 生命周期，不凭猜声明兼容。
2. 集成放独立模块和 optional extra，只在用户导入集成模块时导入 OpenHTF。
3. transport、cassette 路径由调用方显式提供，不增加隐式硬件或全局 record。
4. 用 fake phase/plug 覆盖成功、断言失败、通信错误和清理。
5. 保留“session 不关闭外部 transport”的所有权。

验收：无 OpenHTF 的核心环境仍通过；集成依赖有版本约束和可选 CI；fake 结果不被
描述成全版本 OpenHTF 或实机兼容。

---

## 22. 初学者常见 FAQ

### Q1：我没有任何硬件，能学到哪一步？

可以完成本文全部当前功能学习：运行 demo、手工录制虚拟电源、严格回放、注入五类
故障、编写 fake 和 adapter 契约测试、构建并安装 wheel。只有真实串口/VISA 兼容性
无法在没有设备时验证。

### Q2：为什么 record 后找不到目标文件？

先看测试体异常是否逃出了 `with`。异常路径会删除临时文件；如果想保留通信错误，
要在 context 内捕获 CommunicationError 并正常结束。也要检查进入时是否因为目标已
存在且 overwrite=False 而直接失败。

### Q3：为什么命令只差大小写或空格也 mismatch？

v1 匹配原始 command，不做规范化。这样基线的含义明确，不会由库猜测哪些差异不重要。
详见第 8.4 节。

### Q4：空字符串和 null 都是“没内容”，为什么区别对待？

空字符串是成功 query 的合法文本值；null 表示没有 response，用于成功 write 或失败
exchange。混淆它们会掩盖协议差异，详见第 7.5 节。

### Q5：文件第 5 行是不是 fault.at=5？

通常不是。header 占第 1 行，seq 0 从文件第 2 行开始；fault.at 使用 seq。三者的
对照表见第 7.6 节。

### Q6：为什么 recorded/injected timeout 后还能执行下一条？

因为匹配成功后当前 exchange 已消费。调用方捕获通信错误后，下一条从下一个 seq
继续。未捕获并逃出测试体时则按异常退出处理。

### Q7：fault 没触发，先检查什么？

按顺序检查：at 是否等于 seq、match 是否精确一致、操作是否适用于成功 query、
probability 是否通过，以及前面是否已有另一条规则实际触发。见第 9.4 节。

### Q8：普通 replay 会按 duration_ms 等待吗？

不会。只有 delay fault 显式 sleep。at_ms/duration_ms 是观测元数据，不参与匹配。

### Q9：为什么两次 demo 的 cassette hash 不一样？

每次 demo 都重新 record，header 的 created_at 可能变化。demo 保证的是同一次录制后，
各次 replay 前后 hash 不变，不是所有录制文件永远相同。

### Q10：pytest 中只调用 factory、不写 with，会自动检查未消费吗？

不会。插件没有 finalizer 消费检查，必须显式进入 context，由 ReplaySession 在正常
退出时检查。这样也不会让 teardown 掩盖测试断言。

### Q11：session 退出后还需要关闭设备吗？

需要，由设备创建者负责。session 不拥有也不关闭外部 transport，推荐用 try/finally
明确关闭。

### Q12：demo 全 PASS 能否说明真实仪器兼容？

不能。它只证明工具和虚拟协议链路。真实设备必须记录型号、固件、链路、驱动、
termination、timeout 和环境后单独验证。

### Q13：CLI 返回 2 是硬件故障吗？

不一定。退出码 2 表示参数或预期用户错误，例如 cassette 非法、文件不存在或 fault
配置错误。应阅读 stderr 的具体类型和原因，而不是只看退出码。

---

## 23. 术语速查表

| 术语 | 一句话解释 |
| --- | --- |
| adapter | 把不同底层对象包装成共同接口的薄层 |
| API | 库向调用者公开的函数、类和约定 |
| atomic replace | 用完整临时文件一次替换正式目标，避免正式文件半写状态 |
| at_ms | 相对录制 monotonic 起点的毫秒时间，不参与匹配 |
| baudrate | 串口链路速率配置，不是 SCPI 文本格式 |
| branch coverage | 对条件分支执行情况的覆盖率 |
| cassette | 保存 header 和有序 exchange 的 JSONL 文件 |
| CI | 持续集成，在指定环境自动运行测试和检查 |
| CLI | 命令行接口 |
| command | 不含 termination 的原始协议命令 |
| context manager | 通过 with 和 __enter__/__exit__ 管理进入/退出的对象 |
| contract test | 验证 adapter 与驱动对象之间约定的测试 |
| CR/LF | 常见消息终止字节 `\r`/`\n` |
| CRC | 检测传输错误的校验机制，当前未实现 |
| dataclass | 减少数据类样板代码的 Python 装饰器 |
| delay | 等待后仍返回原结果的故障 |
| deterministic | 相同明确输入得到相同结果 |
| disconnect | 当前交互的断连错误，当前不模拟永久断线 |
| duration_ms | 单次操作 monotonic 耗时 |
| editable install | 让环境直接引用当前源码的安装方式 |
| encoding | str 与 bytes 之间的转换规则 |
| entry point | 包向命令行或 pytest 等环境公开的可发现入口 |
| exchange | 一次 write/query 及其结果 |
| fake | 测试控制的脚本化合作者 |
| fault plan | 描述故障位置、操作和概率的 JSON 配置 |
| finalizer | fixture 在测试结束后的清理逻辑 |
| fixture | pytest 注入测试的辅助对象 |
| flush | 把 Python 文件缓冲交给 OS，不等于 fsync |
| hash / SHA-256 | 对 bytes 计算固定摘要；本项目用于概率和文件不变检查 |
| header | cassette 第一行的格式元数据 |
| JSONL | 每行一个 JSON 值的文本格式 |
| load_fault_plan | 加载并结构校验 fault plan 的公共 API |
| match | fault 中可选的精确 kind/command 过滤 |
| mismatch | 当前调用与下一条录制交互不一致 |
| monotonic | 适合测间隔、不受 wall-clock 回拨影响的时钟 |
| mypy | Python 静态类型检查器 |
| None/null | 没有值，不等于空字符串 |
| outstanding | 已发出但尚未完成的请求 |
| overwrite | 是否允许录制正常发布时替换已有目标 |
| partial read | 收到响应残片后尚未读完整 |
| pip check | 检查当前环境包依赖一致性 |
| probability | 与 SHA-256 sample 比较的触发阈值 |
| Protocol（typing） | Python 结构化方法类型约定 |
| ProtocolError | 通信文本或使用方式不符合协议的错误 |
| pyserial | Python 串口库，可选依赖 |
| PyVISA | Python VISA 客户端库，可选依赖 |
| PyVISA-sim | VISA 仿真后端，不是实机 |
| query | 有完整文本响应的请求 |
| record | 调 transport 并逐条写临时 cassette 的模式 |
| replay | 不访问硬件，严格按 cassette 返回结果的模式 |
| resource ownership | 谁创建并负责关闭资源的约定 |
| response | query 的文本结果；成功 write/失败项为 null |
| Ruff | Python lint 和格式工具 |
| schema | 字段、类型和组合约束 |
| seed | 概率摘要输入中的整数种子 |
| seq | exchange 的零起始连续序号 |
| session | 管理 record/replay 当前生命周期的对象 |
| sdist | Python 源码分发包 |
| site-packages | 虚拟环境安装第三方包的目录 |
| sleep injection | 用测试函数替代真实 sleep，以验证等待参数 |
| stable error | 只含受控 type/message、可跨进程回放的通信错误 |
| state machine | 根据当前状态、输入和规则决定下一步的模型 |
| stderr/stdout | 错误输出流/正常输出流 |
| strict replay | kind 和原始 command 必须按序完全匹配 |
| subprocess | 从测试启动独立进程，用于真实 CLI 验证 |
| termination | 消息终止符，不属于原始 command |
| timeout | 规定时间内未完成，不等同于 delay |
| transport | 执行 write/query/close 的底层对象 |
| unplayed | 正常退出时仍未消费的 cassette exchange |
| UTC | 协调世界时，header created_at 使用它 |
| uv | 管理本地 Python、环境和依赖的工具 |
| validate_cassette | 完整读取并校验 cassette 的公共 API |
| venv | 隔离 Python 包环境 |
| VISA | 仪器 I/O 抽象 |
| wall clock | 可受系统校时影响的现实日期时间 |
| wheel | Python 构建分发格式 |
| write | 成功时无响应文本的请求 |

---

## 24. 学完后你应该能回答的问题

如果能不看代码回答下面问题，就已经掌握了本项目主线：

1. 为什么成功 query 的 `""` 和 `null` 必须区分？
2. 为什么 record 遇到逃出的测试异常时不发布 cassette？
3. 为什么 replay mismatch 不消费，而 recorded timeout 会消费？
4. 为什么 seq、文件行号和 fault.at 不能混用？
5. 为什么 at_ms 不参与匹配，普通 replay 也不等待 duration_ms？
6. 为什么 truncate 不适用于 write 和失败 query？
7. 为什么同 seed 可复现，但两次 record 的文件 hash 仍可能不同？
8. 为什么 session 不关闭外部 transport？
9. 为什么 serial adapter 不能用 `.strip()` 清理响应？
10. 为什么 fake、虚拟电源、PyVISA-sim 和实机验证不能互相替代？
11. 为什么 pytest fixture 不做 finalizer 消费检查？
12. 为什么还要在隔离环境安装 wheel，而不只跑 editable 源码测试？

对应关系：练习 0/1 巩固 v0.1；练习 2/4 对应 v0.2；练习 3 连接 v0.3 与 schema
兼容；练习 5 对应 v0.3。v0.4 先研究长度前缀二进制，v0.5 实机验证是 v1.0 的
必要门槛。未完成实机验证时，不应把稳定版或真实仪器兼容当作既成事实。
