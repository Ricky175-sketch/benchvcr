# BenchVCR 学习笔记（zh-CN）

本文面向第一次接触程控仪器、录制回放或硬件测试工具的读者。示例只使用虚拟
电源和 fake，不代表真实仪器已经验证。

## 1. 先建立协议直觉

### 1.1 SCPI、write 与 query

SCPI 常见命令分成两类：

- 设置或动作：`VOLT 5`、`OUTP ON`、`*RST`，本项目中对应 `write(command)`，
  成功时没有响应体。
- 查询：`*IDN?`、`VOLT?`、`MEAS:CURR?`，对应 `query(command)`，成功时返回
  完整文本响应。

问号是这里的协议语义之一，不是 Python 语法。BenchVCR 不试图理解所有 SCPI；
`VirtualPowerSupply` 只实现教学所需的固定命令集。公共 cassette 保存原始命令，
所以 `VOLT 1` 与 `VOLT 1.0`、大小写或空格不同的命令默认不是同一次交互。

同步、单 outstanding 的含义是：调用方发出一个请求并等待它完成，完成后才能发
下一个。首版不处理交叉响应、主动上报和并发请求，因为这些情况需要另一套关联
与缓冲模型。

### 1.2 VISA 与串口分别解决什么

- 串口提供字节流。波特率、数据位、停止位和校验属于串口链路配置；SCPI 文本、
  编码和 termination 属于其上层约定。串口本身不知道一条响应在哪里结束。
- VISA 是仪器 I/O 抽象。message-based resource 可以提供 `write`/`query`/`read`，
  并通过 timeout、read/write termination 等属性描述消息边界。
- PyVISA 是 Python 的 VISA 客户端封装；PyVISA-sim 是仿真后端。它们都不等于真实
  仪器，也不保证某个仪器固件的 SCPI 行为。

因此两个 adapter 都很薄：协议状态机和 cassette 不应该依赖某个厂商 SDK。

### 1.3 termination 为什么不能随手 strip

常见 termination 是 `\n` 或 `\r\n`。发送时 adapter 把 write termination 加到
原始命令后；接收时读取到 read termination，去掉的仅是这段协议定界符。

`.strip()` 会同时删除响应首尾所有空白，可能把有意义的空格、制表符或 `\r`
一起吃掉，也会让 cassette 无法重放原始文本。当前 `SerialTextAdapter` 不用它。
例如字节响应 `b" 1.0 \r\n"`、read termination 为 `\n` 时，结果是 `" 1.0 \r"`，
不是 `"1.0"`。

公共 session 的 `command` 不含 termination，并拒绝 CR/LF。这样记录的是协议命令，
而具体串口换行风格由 adapter 配置负责。

### 1.4 timeout 的几种情况

至少区分：

1. 写操作超时；
2. 响应一个字节也没到；
3. 已收到部分响应，但 termination 一直没到（partial-read timeout）。

第 3 种不能当作完整的空响应，也不能把残片当成功结果。当前 serial fake 测试专门
覆盖它。PyVISA 适配器通过明确的 `VI_ERROR_TMO == -1073807339` 状态映射 timeout；
其他 VISA 错误不会都伪装成超时。

`timeout` 是通信结果，`delay` 只是回放时人为等待。两者可以独立测试。

## 2. 架构和模块依赖

```text
                         ┌─────────────────────┐
应用程序 / 测试 ────────▶│ use_cassette        │
                         │ Record/ReplaySession│
                         └──────────┬──────────┘
                                    │
                    ┌───────────────┴────────────────┐
                    ▼                                ▼
             cassette.py                       faults.py
          JSONL / 不变量 / Exchange       规则选择 / SHA-256 / 故障
                    │                                │
                    └──────────────▶ errors.py ◀────┘
                                      稳定异常
                                    ▲
                                    │
       virtual.py            adapters/serial.py  adapters/pyvisa.py
       确定性虚拟设备          可选外部对象的薄封装（不导入驱动本身）

cli.py ──▶ demo.py ──▶ session.py + virtual.py
   └─────▶ validate_cassette()
pytest_plugin.py ──▶ ReplaySession（只提供显式 replay factory）
```

核心模块只依赖标准库。`pytest_plugin.py` 由 pytest 环境加载；核心 `__init__` 不导入
它。两个 adapter 接收调用方已经创建的 connection/resource，代码中不执行
`import serial` 或 `import pyvisa`，所以 demo/validate 没有隐式驱动依赖。

建议遵守依赖方向：cassette 不知道 session；faults 根据已验证的 `Exchange` 选规则；
session 组合两者；CLI 和插件只调用公共状态机，不复制匹配逻辑。

## 3. 四条关键调用链

### 3.1 record 正常路径

```text
with use_cassette(path, transport=t)
  → RecordSession.__enter__
    → 检查目标/覆盖策略
    → 在目标同目录 mkstemp 临时文件
    → 写 header 并 flush
    → 记录 monotonic 起点
  → session.write/query
    → RecordSession._run
      → 校验 command
      → 记录操作开始时间
      → 调用外部 transport.write/query
      → RecordSession._append
        → 构造 Exchange（seq、at_ms、duration_ms、结果或稳定错误）
        → JSON 序列化、写一行、flush、seq += 1
  → 测试体正常结束
  → RecordSession.__exit__(exc_type=None)
    → 关闭临时文件
    → 再次检查覆盖策略
    → os.replace(temp, target) 原子发布
```

外部 transport 不由 session 关闭。session 的 `close()` 是资源所有权上的 no-op；
真正发布由 context exit 控制，设备创建者仍应在自己的 `finally` 中关闭设备。

### 3.2 record 的硬件错误与测试体异常

硬件错误在 `_run` 内归一化并写入失败 exchange，然后重新抛出。此时测试体有两个
选择：

- 在 `with` 内捕获通信错误并正常结束：临时文件最终发布，错误可被回放；
- 不捕获，或之后断言失败：`__exit__` 看到测试体异常，关闭并删除临时文件，原异常
  继续传播，目标不发布。

清理过程在已有异常时抑制清理异常，避免“删除临时文件失败”覆盖真正的断言。
要录制硬件错误，必须有意捕获它，而不是让录制器猜测测试是否应该失败。

### 3.3 replay 严格匹配与消费

```text
ReplaySession.__enter__
  → validate_cassette（完整验证，不创建 transport）
  → 可选 load_fault_plan
ReplaySession._run(kind, command)
  → 取 exchanges[index]
  → kind 或原始 command 不同？
       是：CassetteMismatchError；index 不变
       否：index += 1（先消费）
            → 可选 FaultPlan.rule_for / apply_fault
            → 若原 exchange 有 error 且未被故障替换，抛出
            → 否则返回原始/修改后的 response
```

“匹配后先消费”很重要：timeout/disconnect 不代表调用方必须终止整个测试。调用方
可以捕获该错误并调用下一条，下一条应与下一个 seq 匹配。相反，匹配失败不消费，
调用方可以修正命令后重试。

正常退出时 `index < len(exchanges)` 会抛 `UnplayedInteractionsError`。测试体已有
异常时不做该检查。多调用一条属于 `CassetteMismatchError(end of cassette)`。

### 3.4 fault 选择路径

`FaultPlan.rule_for(exchange)` 按数组顺序检查：

1. `rule.at == exchange.seq`；
2. 可选 kind/command 精确匹配；
3. truncate/response_replace 只对成功 query 有实际资格；
4. probability 的无状态抽样通过。

第一条全部满足的规则生效，后面的不再检查。delay 后仍返回或抛出录制结果；
timeout/disconnect 直接替换本次结果；两个响应修改操作不作用于 write 或失败查询。
“配置了规则但资格不满足”不是硬件错误，也不会为了触发它而消费别的 exchange。

## 4. cassette 字段和不变量

| 字段 | 含义 | 关键约束 |
| --- | --- | --- |
| header `format` | 文件类型，固定 `benchvcr` | 不支持时拒绝 |
| `schema_version` | 当前为 1 | bool 不能冒充整数 1 |
| `protocol` | 当前为 `text` | binary 留给后续 schema |
| `library_version` | 写入库版本 | 非空字符串 |
| `created_at` | 创建时的 UTC wall clock | ISO-8601 且 UTC |
| `seq` | exchange 序号 | 从 0 连续递增 |
| `kind` | `write` 或 `query` | 参与严格匹配 |
| `command` | 原始命令，不含 termination | 非空，无 CR/LF，参与严格匹配 |
| `at_ms` | 相对 session 起点的 monotonic 毫秒 | 有限、非负、不倒退，不参与匹配 |
| `duration_ms` | 当次操作耗时 | 有限、非负，不触发自动等待 |
| `ok` | 操作是否成功 | 必须是 JSON bool |
| `response` | 查询文本 | 成功 query 必须是 str，`""` 合法；成功 write/失败项必须为 null |
| `error` | 稳定通信错误 | 失败时含且仅含 `type`/`message`；成功时为 null |

错误 `type` 只有 `timeout`、`disconnect`、`protocol`、`transport`。没有 traceback、
本地路径或任意异常类名，因此回放跨进程更稳定，也减少敏感信息泄露。

验证器一次性读完并检查整个文件，而不是只在消费到时才发现尾部坏数据。非法 UTF-8
通过出错字节前的换行数换算物理行号；JSON 和字段错误也带行号。最后一行的正常换行
允许，额外空白行不允许；JSON duplicate key 和 NaN/Infinity 也拒绝。

## 5. wall-clock、monotonic 与确定性

- `datetime.now(timezone.utc)` 用于 header：回答“这个文件何时创建”，会受到系统
  时间校准影响，不能用来计算稳定操作间隔。
- `time.monotonic()` 用于 `at_ms` 和 `duration_ms`：回答“相对本次录制过了多久”，
  不受 wall-clock 回拨影响；不同机器的绝对值不可比较。
- 回放严格匹配只看 seq 位置的 kind 和原始 command。时间元数据既不做容差匹配，
  也不让普通 replay 自动睡眠。否则测试会无意义地复制录制耗时。
- delay fault 是唯一显式等待行为，sleep 可注入，所以单元测试记录调用参数而不实际
  等待。
- probability 不依赖 Python `random`、进程状态或 hash randomization。固定字符串
  `benchvcr:v1:{seed}:{seq}:{rule_index}` 的 SHA-256 前 8 字节转成无符号大端整数，
  再除以 `2**64`。测试向量固定了输入帧、digest 前缀和浮点结果。

因此“同 seed 可复现”指故障选择可复现，不表示不同机器的录制时间或 header 创建
时间完全相同。

## 6. 推荐源码阅读顺序与调试断点

### 阅读顺序

1. `src/benchvcr/transport.py`：先记住只有 write/query/close。
2. `src/benchvcr/errors.py`：区分配置、cassette、回放状态和通信错误。
3. `src/benchvcr/cassette.py`：从 `validate_cassette` 往 `_parse_exchange` 追字段。
4. `src/benchvcr/session.py`：分别沿 record/replay 的 `_run` 和 `__exit__` 阅读。
5. `src/benchvcr/faults.py`：先看 plan 结构校验，再看 `rule_for` 和 `apply_fault`。
6. `src/benchvcr/virtual.py`：观察先验证、后改状态。
7. `tests/fakes.py`、`test_session.py`、`test_faults.py`：从契约反推设计。
8. 两个 adapter 及各自 fake 契约测试。
9. `demo.py`、`cli.py`、`pytest_plugin.py`：观察组合层而不重复核心逻辑。
10. `test_pytest_plugin.py` 和 `test_cli.py`：理解嵌套 pytest 与 subprocess 验证。

### 关键断点

- `RecordSession.__enter__`：临时文件在哪里、默认覆盖如何拒绝。
- `RecordSession._append`：失败/成功字段如何形成，flush 前 seq 是多少。
- `RecordSession.__exit__`：正常发布与异常删除的分支。
- `ReplaySession._run`： mismatch 前后的 `_index`；通信错误前是否已加一。
- `FaultPlan.rule_for`：每条规则在哪一个资格条件被跳过。
- `apply_fault`：delay 后为何还可能出现 recorded error。
- `SerialTextAdapter.query`：partial buffer 在空读时如何处理。
- `ReplaySession.__exit__`：测试体异常为何不会追加 unplayed。

常用命令：

```bash
.venv/bin/python -m pytest tests/test_session.py -x --pdb
.venv/bin/python -m pytest tests/test_faults.py::test_fixed_probability_vectors -vv
.venv/bin/python -m benchvcr cassette validate path/to/file.jsonl
.venv/bin/python -m benchvcr demo --output-dir /tmp/benchvcr-debug --seed 42
```

调试 mismatch 时先打印异常的结构化字段：`seq`、`expected_kind`、
`expected_command`、`actual_kind`、`actual_command`，不要先改匹配逻辑。调试录制发布
时查看同目录隐藏的 `.<cassette-name>.*.tmp`，同时保留原测试异常。检查回放是否改
文件时，在前后对原始 bytes 计算 SHA-256，而不是只比较格式化后的 JSON。

## 7. 测试策略：每一层回答不同问题

### 7.1 fake 与状态机单元测试

`FakeTransport` 是脚本化调用序列，不模拟真实电气行为。它适合验证：

- 原始命令是否原样传递；
- 通信错误是否被记录、归一化并重新抛出；
- 外部 close 是否被错误调用；
- 异常退出是否发布半成品。

直接构造坏 JSON/bytes 比通过正常录制器生成坏文件更有效，因为正常录制器本来
就不应生成这些输入。参数化测试覆盖字段组合，而不是只覆盖 JSON 语法。

### 7.2 adapter 契约测试

serial fake 控制每次 `read(size)` 返回的 bytes 或异常，因此能确定地制造空读、
partial read、多字节 termination、termination 后多余数据和短写。VISA fake 提供
`status_code`，验证真正的 timeout 状态，而不是按错误消息猜测。

契约测试证明 wrapper 对约定对象的行为，不证明真实驱动/固件兼容。后者只能由
v0.5 实机矩阵补足。

### 7.3 静态 cassette 与 pytest 集成测试

`tests/cassettes/plugin.jsonl` 是人工可审查的固定输入。插件测试还使用 pytester
创建“当前测试文件旁的 cassettes”目录，验证相对路径不是相对于 shell  cwd。

断言失败、unplayed 和“不进入 with”分别运行嵌套 pytest，确保 fixture 没有
finalizer 偷做消费检查，也没有把测试体断言覆盖掉。

### 7.4 demo 与 CLI 测试

demo 串联真实核心代码和虚拟设备，覆盖 record → clean replay → 五类 fault replay
→ hash 不变。CLI 既有直接 `main([...])` 测试，也有 `python -m benchvcr` subprocess
测试；后者验证模块入口、退出码和 stderr 隔离。

wheel 验收还要在另一个干净虚拟环境安装构建产物，再运行 console script，避免
“源码目录恰好可见”掩盖打包或 entry point 问题。

### 7.5 跨平台矩阵

Ubuntu/Windows/macOS 与 Python 3.10/3.13 的 CI 主要防止：

- 路径分隔符和当前目录假设；
- 文本编码/换行差异；
- `os.replace`、临时文件关闭时机差异；
- 旧 Python  typing/标准库 API 不兼容；
- hash/probability 算法意外依赖平台。

CI YAML 只是配置。只有远端实际运行记录才能支持远端通过声明；本地只能报告本机
实际执行结果。

## 8. 常见 FAQ

**Q：为什么命令只差一个空格也 mismatch？**
v1 选择可预测的原始文本严格匹配。规范化和正则属于后续显式 opt-in 能力，不能
悄悄改变旧 cassette 的含义。

**Q：termination 存在 cassette 的 command 里吗？**
不存在。命令不含 CR/LF；adapter 在 I/O 边界添加/移除配置的 termination。

**Q：`response: ""` 和 `response: null` 有什么区别？**
前者是成功 query 的合法空文本；后者用于成功 write 或失败 exchange。成功 query
的 null 是 schema 错误。

**Q：录制时遇到 timeout，为什么最后没有 cassette？**
如果 timeout 逃出测试体，context 按异常路径删除半成品。要保留该错误，在 context
内捕获 `CommunicationError` 并正常结束。

**Q：注入 disconnect 后为什么下一条还能执行？**
v1 只建模当前 exchange 的断连，不建模永久断线；匹配项已经消费，调用方可捕获后
继续。永久连接状态属于后续专门设计。

**Q：为什么 truncate 规则在 write 上没有报错？**
它“不具备实际触发资格”，会继续寻找下一条规则。结构合法但当前结果不适用的规则
不伪装成硬件错误。

**Q：普通 replay 会按 duration_ms 等待吗？**
不会。时间是观测元数据，只有 delay fault 调用 sleep。

**Q：为什么 cassette 的 seq 从 0 开始？**
fault plan 的 `at` 与数组式序号一致，第一条交互是 `at: 0`。行号则仍从 1 开始，
header 是第 1 行，所以 seq 0 通常在文件第 2 行。

**Q：pytest fixture 能自动录制或自动创建硬件吗？**
不能。录制使用公共 API 并显式传 transport；插件只有 replay factory，没有全局
`--record` 或 `auto` 模式。

**Q：session 会替我关闭 pyserial/PyVISA 资源吗？**
不会。创建者拥有并关闭资源；demo 对虚拟电源也用 `finally: supply.close()` 展示
这一所有权。

**Q：虚拟电源的测量值能证明真实电源精度吗？**
不能。固定负载公式只验证协议与工具链，不包含噪声、校准、热效应或仪器固件差异。

## 9. 循序渐进练习与参考思路

### 练习 1：新增 `MEAS:POW?`（对应 v0.1 虚拟设备）

任务：输出开启时返回测量电压乘测量电流，输出关闭时为零，固定六位小数。

参考思路：

1. 先在 `test_virtual.py` 写电压受限和输出关闭两组失败测试。
2. 在 `VirtualPowerSupply.query` 增加精确查询分支，复用 `_measurements()`，不要从
   设定值直接计算，否则电流限制时结果会错误。
3. 保持非法命令不改状态，不需要改 cassette schema。
4. 如需 demo 覆盖，把新 operation 加到脚本会改变后续 seq；必须同步调整 fault
   `at`，最好利用明确常量而不是散落数字。
5. 验收：`VOLT 12`、`CURR 0.5`、10 Ω 时功率为 `2.500000` W（5 V × 0.5 A），
   关闭后为 `0.000000`，重复查询一致。

### 练习 2：新增 `cassette stats`（对应 v0.2）

任务：CLI 输出交互数、write/query 数、成功/失败分类和耗时统计。

参考思路：

1. 先定义空 cassette 和人类可读/JSON 输出契约，再写 CLI 测试。
2. 在独立模块函数中接收 `Cassette`，让 CLI 只负责 `validate_cassette` 和打印；
   不要重新解析 JSON。
3. duration 合计、最大值和首末 at 要区分；不要把它描述为 wall-clock 测试耗时。
4. 对空集合不要算除零平均值；浮点输出规定格式和顺序。
5. 非法 cassette 继续走统一用户错误路径和退出码 2。
6. 验收：空、单 query、混合成功/错误、空响应、非 ASCII、倒序时间的坏文件均有
   测试；同文件重复输出逐字一致。

### 练习 3：扩展 fault 序号匹配并讨论 schema 兼容

任务：希望一个规则同时命中多个 seq 或一个区间，例如 `[1, 3, 4]`。

参考思路：

1. 先列出兼容问题：旧 reader 看到数组 `at` 会怎样？新增 `at_any`/`at_range` 字段
   是否被旧 reader 的未知字段检查拒绝？probability 输入里的 seq 是否仍是实际
   exchange seq？规则数组顺序是否保持？
2. 最安全做法是让现有 `at` 的整数语义保持不变。若让 `at` 同时接受数组，会改变
   v1 类型，不应悄悄发布为“兼容”。
3. 可选设计是新增 schema v2，提供明确 reader 协商/迁移；或在有正式 feature
   协商机制后增加可选字段，但不能假设当前严格 v1 reader 能读取。
4. 选择逻辑仍对每个实际 exchange 调用，并以该 exchange.seq 参与 SHA-256，不能
   用规则数组里的位置替代，否则故障概率不可复现语义会改变。
5. 验收：边界、重复序号、空列表、倒序区间、超大整数、首条实际触发规则、旧 v1
   文件和固定概率向量都有测试；README/TODO 同步说明迁移策略。

### 练习 4：安全转义的离线 HTML 时间线（对应 v0.2）

任务：把 cassette 生成单个离线 HTML，无 CDN、无运行时网络请求。

参考思路：

1. 先构造恶意命令：`</script><script>alert(1)</script>`、引号、`&`、`<`、`>`、
   U+2028/U+2029，并写安全测试。
2. 放入 HTML 文本节点时使用 `html.escape`；放入属性时还要正确处理引号。不要把
   原始 cassette 字段拼进 `<script>` 或事件处理器。
3. 如果嵌入 JSON，优先放在不可执行的数据节点并至少转义 `<`、`>`、`&` 和 Unicode
   行分隔符；不要用 `innerHTML` 渲染这些值。更简单的是生成静态 DOM 行，不嵌脚本。
4. 时间轴使用 seq 和相对 at/duration，不能从 created_at 推单条操作时刻。
5. 验收：生成文件离线打开；恶意字符串只显示为文本；空 cassette、长响应、错误行、
   非 ASCII 和 Windows 路径测试通过；无外部 URL 请求。

### 练习 5：OpenHTF 薄集成（对应 v0.3）

任务：让 OpenHTF phase 显式使用 BenchVCR transport，同时不污染核心依赖。

参考思路：

1. 先调查目标 OpenHTF 版本的 plug/phase 生命周期，再定义最小包装接口；不要猜
   API 后直接声称兼容。
2. 把集成放在独立模块和 optional extra 中，只有用户导入该模块时才导入 OpenHTF。
3. transport/cassette 路径由调用方显式传入；不要增加隐式硬件创建或全局 record
   开关。
4. 用 fake phase/plug 契约覆盖成功、断言失败、通信错误和资源清理；保留 session
   “不关闭外部 transport”的所有权约定。
5. 可选示例应在未安装 OpenHTF 时给出清楚安装提示，核心测试仍不导入它。
6. 验收：核心无 OpenHTF 环境通过；集成测试有真实版本约束或由明确标记的可选 CI
   job 执行；fake 结果不被描述成 OpenHTF 全版本兼容。

## 10. 与 TODO 的关系

- 练习 1 巩固 v0.1，不应借机扩张为完整仪器驱动。
- 练习 2 和 4 属于 v0.2，先确定输出契约和转义边界，再实现观测功能。
- 练习 3 是 v0.3 匹配能力与 v1.0 schema 兼容策略之间的桥梁。
- 练习 5 属于 v0.3，可选依赖边界比“能 import”更重要。
- v0.4 二进制帧应先完成长度前缀及短读/非法长度测试，再评估其他格式。
- v0.5 真实串口/VISA 设备验证是 v1.0 的必要门槛；没有设备时可先做设计和 fake，
  但不能把相应实机项勾选为完成。
