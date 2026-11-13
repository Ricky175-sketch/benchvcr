# BenchVCR 分层 TODO

状态约定：只有代码、测试、文档和本地验收均完成的 v0.1 项才能勾选。CI 文件
的存在不等于远端 Checks 已运行；真实硬件验证也不能由 fake 或虚拟电源替代。

优先级：P0 为当前版本必要项，P1 为重要增强，P2 为探索项。依赖列不仅包括代码，
也包括设备、设计决策或发布条件。

## v0.1 — 同步文本 MVP

- [x] **P0：项目骨架与隔离工具链**
  - 依赖：项目内 uv、Python 3.12、`.venv` 和缓存；无全局环境修改。
  - 验收：打包、pytest、Ruff、mypy、MIT 与 `.gitignore` 配置完整；本地环境目录均位于项目内且被忽略。
- [x] **P0：cassette JSONL v1 与公共异常**
  - 依赖：零起始序号、稳定错误类型和 header/exchange 字段约定。
  - 验收：合法空响应通过；非法 UTF-8/JSON、重复 header、版本、序号、时间和字段组合均有行号与原因测试。
- [x] **P0：原子 record 与严格 replay**
  - 依赖：`TextTransport` 和明确的外部资源所有权。
  - 验收：逐条 flush、正常退出原子替换、默认不覆盖；体异常删除半成品且保留原异常；严格匹配不消费；错误后可继续；未消费和关闭状态测试通过。
- [x] **P0：确定性 fault plan 与五类故障**
  - 依赖：cassette 序号、可注入 sleep、SHA-256 固定算法。
  - 验收：固定向量、同 seed 重放一致、首条实际触发规则、单故障上限、空替换、结构错误及五类操作均有测试；record 拒绝 fault plan。
- [x] **P0：确定性虚拟程控电源与端到端 demo**
  - 依赖：固定负载测量模型和文本命令集。
  - 验收：非法命令不改状态；demo 依次通过 record、clean replay、五类 fault replay 和 cassette 哈希不变检查；无噪声、无硬件、无可选驱动导入。
- [x] **P0：可选 serial/PyVISA 适配器**
  - 依赖：调用方创建的 connection/resource；可选依赖不进入核心环境。
  - 验收：fake 契约覆盖 termination、非 strip、partial-read timeout、异常归一化、明确 VISA timeout 和 close；核心 demo 在无 pyserial/PyVISA 时通过。
- [x] **P0：pytest fixture、CLI 和静态集成样例**
  - 依赖：pytest entry point、当前测试文件旁的 `cassettes/`。
  - 验收：必须显式 `with`；无 finalizer 消费检查；断言不被掩盖；`demo`/`cassette validate`/`python -m benchvcr` 有测试，用户错误为简洁 stderr 和退出码 2。
- [x] **P0：文档、构建和本地验收**
  - 依赖：英文 README、中文学习笔记、本 TODO。
  - 验收：测试与覆盖率、Ruff、格式、mypy、wheel/sdist 构建、`pip check`、隔离 wheel 安装后的 CLI demo 全部实际通过；报告不夸大硬件和远端验证。
- [x] **P1：三平台 CI 配置（仅配置交付）**
  - 依赖：GitHub Actions 工作流；远端运行不是本地完成条件。
  - 验收：Ubuntu/Windows/macOS × Python 3.10/3.13 执行测试和 demo；Ubuntu 质量任务执行 lint、类型检查和构建；未运行时明确标注。

本地验收记录（macOS，Python 3.12.16）：143 项测试通过，核心分支覆盖率 94%；
Ruff、格式、mypy、sdist/wheel 构建、两个环境的 `pip check`、wheel 隔离安装后的
console script 与 `python -m benchvcr` demo/validate 均通过。远端 CI 未运行，真实
串口/VISA 仪器未验证。

## v0.2 — 离线观测与诊断

- [ ] **P1：离线单文件 HTML 时间线**
  - 依赖：v0.1 cassette schema；浏览器安全转义设计。
  - 验收：单个 HTML 无 CDN/网络请求；按 `seq` 显示 kind、命令、状态、相对时间与耗时；命令和响应中的 `<>&"、</script>`、Unicode 分隔符均安全转义；不能通过 cassette 注入脚本；空 cassette、非 ASCII、长文本有测试。
- [ ] **P1：`cassette stats`**
  - 依赖：公共 `validate_cassette()`；空数据输出约定。
  - 验收：输出 exchange 数、write/query、成功/各错误类型、首末 `at_ms`、duration 合计/最大值的确定性文本或 JSON；非法文件沿用退出码 2；时间只统计不参与匹配。
- [ ] **P1：`cassette diff`**
  - 依赖：stats 输出模型和稳定排序。
  - 验收：按 seq 对比 kind/command/ok/response/error，明确新增、删除和变化；时间默认忽略，可选显示；完全相同的文件给出零差异和稳定退出码；包含空响应与错误样例。
- [ ] **P1：错误诊断改进**
  - 依赖：保持严格匹配，不自动修复顺序。
  - 验收：mismatch 显示安全的预期/实际 repr、后续少量候选和修复提示；未消费错误列出剩余 seq 范围；控制转义、截断长度和敏感信息边界有测试，不改变原异常类型。

## v0.3 — 测试框架与匹配能力

- [ ] **P1：OpenHTF 可选集成**
  - 依赖：v0.1 公共 API；OpenHTF extra；真实 OpenHTF API 版本调查。
  - 验收：核心不隐式导入 OpenHTF；薄封装把 record/replay transport 显式交给 phase，不创建隐式硬件；fake 契约和一个可选示例覆盖通过、断言失败、通信错误与清理路径。
- [ ] **P2：PyVISA-sim 示例**
  - 依赖：PyVISA/PyVISA-sim extras 和固定 YAML 仿真资源。
  - 验收：示例离线可重复，明确它不是实机验证；覆盖 termination 与 timeout；未安装 extra 时给出可操作错误，不影响核心测试。
- [ ] **P1：更多匹配能力**
  - 依赖：先定义命令规范化、正则安全、乱序匹配与“未消费”语义的兼容策略。
  - 验收：精确匹配仍是 v1 默认；新增匹配显式 opt-in； catastrophic regex 有输入限制或禁用；匹配失败不消费的语义不变；schema/feature 协商和旧文件测试通过。

## v0.4 — 有边界的二进制帧

- [ ] **P1：长度前缀二进制请求—响应帧**
  - 依赖：新 binary protocol schema、明确字节序/宽度/最大长度、十六进制或 base64 编码决策。
  - 验收：先只支持单一同步请求—响应格式；覆盖零长度、最大长度、非法/负/溢出长度、短写、header/body 短读、partial timeout 和多余字节；文本 v1 回放不变。
- [ ] **P2：评估其他帧格式**
  - 依赖：长度前缀实现复盘和真实协议样例。
  - 验收：为固定头、分隔符、CRC 等分别写协议矩阵；只有边界、错误归一化和测试向量明确后才实现，不一次性宣称“通用二进制”。

## v0.5 — 真实设备验证（v1.0 必要门槛）

- [ ] **P0：真实串口设备回环/设备验证**
  - 依赖：获得授权设备、线缆/电平确认、安全操作规程；可在获得设备后提高排期优先级。
  - 验收：记录设备型号、接口、波特率、数据位/停止位/校验、编码、termination、OS、驱动和依赖版本；保存最小 cassette；验证正常、超时、断连与短读；写明未能覆盖的限制。
- [ ] **P0：真实 message-based VISA 仪器验证**
  - 依赖：授权仪器、VISA 实现和网络/ USB/GPIB 环境。
  - 验收：记录仪器厂家/型号/固件、VISA 后端、resource 字符串（脱敏）、termination 与 timeout；分别验证 write/query 和 VISA timeout 映射；禁止危险输出设置，说明测量误差不在本工具保证范围内。
- [ ] **P1：可复现实机手册与限制清单**
  - 依赖：前两项实际日志和 cassette。
  - 验收：第三方可按手册重复环境搭建；fake、PyVISA-sim、虚拟电源与实机结果分栏报告，不互相冒充。

## v1.0 — 稳定与发布门槛

- [ ] **P0：API 与 cassette/fault schema 兼容策略**
  - 依赖：v0.2–v0.4 的 schema 变更经验。
  - 验收：书面定义语义化版本、reader/writer 支持范围、未知字段处理、迁移工具和旧 fixture 矩阵；至少验证每个已发布 schema 的读取行为。
- [ ] **P0：弃用与支持矩阵**
  - 依赖：实际 CI 和用户可见 API 清单。
  - 验收：弃用警告、替代 API、最短保留周期明确；Python/OS/可选驱动支持矩阵由实际测试支撑；不声明未测平台兼容。
- [ ] **P0：真实硬件门槛复核**
  - 依赖：v0.5 两项实机验证。
  - 验收：实机记录、限制、回归 cassette 和发布检查全部归档；缺少真实硬件时不得把版本标为 v1.0 稳定版。
- [ ] **P0：发布检查与 PyPI 名称复核**
  - 依赖：兼容策略、实机门槛、干净 wheel/sdist 和发布授权。
  - 验收：重新查询并核验 PyPI 名称可用性（不能沿用早期假设）；隔离安装、entry point、许可证、元数据、签名/ provenance 和 TestPyPI 流程通过；发布必须显式批准，不能由本地 TODO 自动触发。

## 学习练习对应

`docs/learning-notes.zh-CN.md` 的 `MEAS:POW?`、stats、fault 序号匹配、HTML 时间线
和 OpenHTF 练习分别对应 v0.1 虚拟设备巩固、v0.2 stats、schema 兼容设计、
v0.2 时间线和 v0.3 OpenHTF。练习先写契约与失败测试，再扩展实现。
