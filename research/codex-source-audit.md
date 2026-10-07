# Codex 源码审计与复用决策

研究日期：2026-10-03。范围：本地 `D:/Desktop/codex-main`，只读；未编译 Rust、未调用真实模型、未访问认证文件。项目依据为完整阅读的 `mihoyoJD.md` 与 `PROJECT_BRIEF.md`。本报告的源码行号只对下述快照有效。

## 1. 推荐结论

推荐 **Python 业务服务 + Codex App Server Runtime + 有边界的官方 Python SDK 二次开发 + 游戏工具 MCP 服务**。React/TypeScript 工作台展示任务、diff、审批和验证证据。首版沿用 Codex 的采样循环、历史、compaction、工具路由、执行隔离和恢复，不另造 Coding Agent Runtime。

这不是预设“只接 App Server”。源码审计找到了一个适合本项目、且已用离线实验复现的扩展需求：**官方 Python SDK 当前参考实现的人工审批与并发事件消费不适合直接支撑交互工作台**。它提供底层 JSON-RPC、生成类型、通知路由和版本协商，值得复用；我们应在局部 SDK adapter/fork 中补足异步 server-request 队列、拒绝优先的默认行为、取消、超时、恢复与幂等处理。这比重复实现整个 Python transport 或强行为改 Rust 而设计功能更有业务价值。

Rust 下游扩展保留为有证据触发的第二层选择。参考树已经有 `ext/extension-api`；若对照实验表明外部上下文包在自动 compaction 后丢失关键游戏约束、或 App Server 事件不足以解释内部步骤，则使用 `ContextContributor`/`ToolLifecycleContributor` 增加一个独立游戏扩展 crate。**当前没有证据证明首版必须修改 Rust。** Rust 扩展属于 workspace 编译期接口，不能宣传为稳定的外部动态插件 ABI。

主线适合 JD 中“上下文管理、工具调用、流式交互、任务执行链路、效果评估”“真实开发环境工具”“调试、回放、可观测”要求；游戏 MCP 工具与证据绑定体现实际研发价值，审批与恢复体现 Runtime 边界理解。

## 2. 快照身份与证据等级

`git -C D:/Desktop/codex-main rev-parse HEAD` 返回 `not a git repository`。因此不能给出 commit hash、上游分支或发布日期。目录时间戳只说明本地文件状态，不作为版本证明。`codex-rs/Cargo.toml:162` 的 workspace version 为 `0.0.0`；两个 SDK 的源码版本均为 `0.0.0-dev`。

关键文件 SHA-256：

| 相对于参考树的文件 | SHA-256 |
| --- | --- |
| codex-rs/Cargo.toml | `10BABE56E2EEDC6D740D8B1FD451DEB9356D41C1964567EB129EDC2E2EF64F41` |
| codex-rs/core/src/session/turn.rs | `06BE250922D479BF12E935729C78421A521A148656DE5264BB74C613C6E359CD` |
| codex-rs/app-server-protocol/src/protocol/common.rs | `56F208350D678F946068A92BD9627FAE1578950CD06D5070ECE01B327C1E9524` |
| codex-rs/model-provider-info/src/lib.rs | `941A8EC0E8BE4B45080CAC3DF3D052999A4CB104811575634B1A9ED510690958` |
| codex-rs/ext/extension-api/src/contributors.rs | `C996CDB0F27CAF2EB534A043AFD17CFADB41E67343417CC3645C20B96B541488` |
| sdk/python/pyproject.toml | `DA5E5B8ECA67F727C49BEFC1BEC71ED72957C1358B3C055433AF97A5C0BD4354` |
| sdk/python/src/openai_codex/client.py | `8452AFBD8148EA212C94E8A6727468054B175ACB0DAF95002C84B66B604D05A6` |

证据分为四类：

- **源码确认**：本报告给出的具体实现与调用关系。
- **已运行的离线 SDK 实验**：[脚本](D:/Desktop/mihoyo-agent-project/research/evidence/codex-sdk-static-probe.py)、[结果](D:/Desktop/mihoyo-agent-project/research/evidence/codex-sdk-static-probe-result.json)。直接导入本地 SDK，在内存中模拟 reader；没有启动 Codex 或执行 shell 工具。
- **主控运行的真二进制＋假模型实验**：[结果](D:/Desktop/mihoyo-agent-project/research/evidence/codex-probe-20261003-231459/result.json)。使用已安装 `0.159.0-alpha.12.1`，证明基本协议闭环；它不是参考源码编译产物，也不证明真实 provider 或工具执行兼容。
- **拟实施/待验证**：SDK 修改、游戏 MCP、真实引擎验证、真实 provider 矩阵、Rust 扩展均未在本阶段实施。

## 3. 一个真实代码任务怎样推进

代表任务：程序员要求“增加带来源和持续回合的战前支援护盾，扩展Scenario和Unity展示，旧Scenario默认行为保持不变，运行规则与消费端测试”。这是总体方案选择的真实功能缺口。产品服务先创建任务、隔离工作区和约束记录，再启动 Codex thread。下面是源码中的对应推进链。

### 3.1 Thread、Session、Turn、Sampling step 并非同一层

| 阶段 | 精确入口与符号 | 意义 |
| --- | --- | --- |
| RPC 方法定义 | [common.rs:551](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/common.rs:551) `ThreadStart`；[common.rs:1038](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/common.rs:1038) `TurnStart` | JSON-RPC 请求表；thread 负责会话，turn 负责一次输入推进 |
| 创建 thread | [thread_processor.rs:1127](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/thread_processor.rs:1127) `thread_start_inner`，`:1315` `thread_start_task`，`:1498` `start_thread(StartThreadOptions)` | 解析并校验配置、环境、动态工具等，进入 core |
| Core 管理 | [thread_manager.rs:1036](D:/Desktop/codex-main/codex-rs/core/src/thread_manager.rs:1036) `start_thread`；`:2040` `spawn_thread` | 管理 live thread、历史与会话初始化，不是一个聊天字符串列表 |
| Session 实例 | [session/mod.rs:512](D:/Desktop/codex-main/codex-rs/core/src/session/mod.rs:512) `Session::spawn`，`:540` `spawn_internal` | 装配模型、工具、历史、环境、扩展与输入/事件通道 |
| 输入 admission | [turn_processor.rs:522](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/turn_processor.rs:522) `turn_start_inner`，`:653` `TurnInputRequest`；[codex_thread.rs:378](D:/Desktop/codex-main/codex-rs/core/src/codex_thread.rs:378) `start_or_steer_turn` | 先检查 thread/provider/输入；输入可能启动新 turn，也可能 steer 当前 turn |
| Core 输入分流 | [session/handlers.rs:420](D:/Desktop/codex-main/codex-rs/core/src/session/handlers.rs:420) `submission_loop`，`:485` `Op::TurnInput`；[turn_input.rs:211](D:/Desktop/codex-main/codex-rs/core/src/session/turn_input.rs:211) `handle`，`:299` `start_or_steer` | 该快照已使用 `TurnInput`，不能套用旧文章的 `Op::UserTurn` 主链 |
| Turn task | [tasks/regular.rs:40](D:/Desktop/codex-main/codex-rs/core/src/tasks/regular.rs:40) `RegularTask::run`，`:105` 调用 `run_turn` | 注册可取消任务，发送 `TurnStarted`，处理在运行中进入的输入 |
| 采样循环 | [session/turn.rs:163](D:/Desktop/codex-main/codex-rs/core/src/session/turn.rs:163) `run_turn`，`:426` loop，`:524` `run_sampling_request`，`:1618` 实现 | 每次采样可能产生工具调用；工具结果进入历史后再次采样；结束条件还要考虑待处理输入和 `end_turn` |

`TurnInputSubmission::Started/Steered/NotSubmitted` 的区分在 [turn_processor.rs:673](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/turn_processor.rs:673)。RPC 接受输入不等于模型已经完成，也不等于输入已被持久化到所有存储。产品应分别显示“已接受”“运行中”“等待审批”“完成/失败/中断”，不要收到 `turn/start` response 就宣告成功。

### 3.2 上下文与 compaction

`run_turn` 在每个请求前捕获一个 `StepContext`，让上下文、公布的工具和实际工具调用使用同一视图：[turn.rs:461](D:/Desktop/codex-main/codex-rs/core/src/session/turn.rs:461)。随后记录变化的 world state、reasoning override，再从历史生成输入 `clone_history().for_prompt(...)`（`:507`、`:517`）。`build_prompt`（`:1589`）组合 input、模型可见工具、base instructions、structured output schema。

历史管理见 [context_manager/history.rs:485](D:/Desktop/codex-main/codex-rs/core/src/context_manager/history.rs:485) `record_items`、`:581` `for_prompt`、`:625` `estimate_token_count`、`:686` `replace_compacted`。历史既有模型可见部分，也有上下文/来源与重建元数据，不能把产品任务数据库直接当成模型历史。

自动压缩策略由 [turn.rs:1471](D:/Desktop/codex-main/codex-rs/core/src/session/turn.rs:1471) `run_auto_compact` 选择本地或远端路径。这里“本地 compaction”仍可能调用模型生成摘要，并非纯本地字符串截断。[compact.rs:245](D:/Desktop/codex-main/codex-rs/core/src/compact.rs:245) `run_compact_task_inner_impl` 形成新历史，`:359` `build_compacted_history`，`:367` 重建 initial context，`:379` `replace_compacted_history`，`:393` 重算 token usage，并发送压缩 item 与精度提示。

业务含义：任务约束、允许路径、引擎版本、测试 run ID 应有**确定性外部来源**；不能期待模型摘要永远记住它们。首版用任务 manifest、受控工具、每阶段附带有界证据包保证约束。MCP 返回结果应是有 token/byte 上限的摘要和 artifact 引用，完整日志留在磁盘。压缩前后必须用长任务用例评估引用完整性和约束保持率。

### 3.3 工具执行与流式事件

`run_sampling_request` 构造 `ToolCallRuntime`（[turn.rs:1638](D:/Desktop/codex-main/codex-rs/core/src/session/turn.rs:1638)），`try_run_sampling_request`（`:2525`）调用 `ModelClientSession::stream`（`:2572`）并处理 `ResponseEvent`。

代表性工具链：

1. [tools/router.rs:248](D:/Desktop/codex-main/codex-rs/core/src/tools/router.rs:248) `ToolRouter::build_tool_call` 从 FunctionCall、CustomToolCall 等构造规范调用。
2. [router.rs:350](D:/Desktop/codex-main/codex-rs/core/src/tools/router.rs:350) `dispatch_tool_call_with_code_mode_result_inner` 交给 registry。
3. [tools/registry.rs:526](D:/Desktop/codex-main/codex-rs/core/src/tools/registry.rs:526) `dispatch_any_with_state` 检查工具存在/类型，运行 pre-tool hooks；`:612` 对 Blocked 返回模型可见错误；hooks 可改输入，但这不等同于 OS 隔离。
4. Shell/unified exec 进入 [unified_exec/process_manager.rs:503](D:/Desktop/codex-main/codex-rs/core/src/unified_exec/process_manager.rs:503) `exec_command`；`:862` `write_stdin`；`:1437` `open_session_with_sandbox`。PTY 会话/过程输出与模型 turn 是不同生命周期。
5. [tools/orchestrator.rs:125](D:/Desktop/codex-main/codex-rs/core/src/tools/orchestrator.rs:125) `ToolOrchestrator::run` 集中处理审批、选择 sandbox、执行及 sandbox denial 后的受控重试。

事件也有层次：provider `ResponseEvent::OutputTextDelta/OutputItemDone/Completed` 分别在 [turn.rs:3002](D:/Desktop/codex-main/codex-rs/core/src/session/turn.rs:3002)、`:2688`、`:2952`；`Completed` 更新 token usage，**不必然等于用户 turn 完成**，`end_turn=false` 仍需下一轮采样（`:2994`）。Core `EventMsg` 再通过 [bespoke_event_handling.rs:155](D:/Desktop/codex-main/codex-rs/app-server/src/bespoke_event_handling.rs:155) 的 turn/item 映射变成产品事件；`:1331` 构造 `TurnCompletedNotification`。消费者必须检查 terminal status，保留 thread/turn/item/call/request ID，不能只拼接 delta 文本。

### 3.4 审批与 Windows sandbox

[common.rs:1771](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/common.rs:1771) 定义 `item/commandExecution/requestApproval`，`:1778` 文件修改审批，`:1784` 用户输入，`:1796` permissions，`:1802` dynamic tool call。它们是**服务端向客户端的请求**，不是无需响应的通知。

[bespoke_event_handling.rs:638](D:/Desktop/codex-main/codex-rs/app-server/src/bespoke_event_handling.rs:638) 与 `:667` 将 patch/exec approval 交给客户端；core 保留 pending waiter，最终决定再影响工具执行。产品自己的“合并变更审批”要与 Codex 的“本次工具提权审批”区分，不能用一个按钮含糊承担两种授权。

Windows 路径见 [sandboxing/src/manager.rs:49](D:/Desktop/codex-main/codex-rs/sandboxing/src/manager.rs:49) `get_platform_sandbox`，`:310` `select_initial`，`:352` `transform`。本快照存在 restricted-token 和 MXC 等实现路径，具体启用依赖配置/平台能力；存在代码不等于本机已验证。

[sandboxing/src/windows.rs:14](D:/Desktop/codex-main/codex-rs/sandboxing/src/windows.rs:14) 明确区分 elevated 后端的 read/write roots 与 unelevated restricted-token 的限制；`:118` 附近说明 WRITE_RESTRICTED token 不能实现 split read/deny-read，配置无法执行时明确拒绝，而非悄悄无隔离运行。[manager.rs:527](D:/Desktop/codex-main/codex-rs/sandboxing/src/manager.rs:527) 对 managed networking 要求 elevated 后端。

推荐在独立工作区内使用原生 Windows 工具与已验证 sandbox，精确配置游戏引擎/编译器读路径、build/cache 写路径。首次搭建应验证只读/允许写/禁止写/网络阻断/取消子进程，再扩大根目录；测试环境不默认给予全桌面写权限。不能把 Docker/Linux 当成 Windows 引擎/编辑器兼容性的证明。远程 MCP 或自建 MCP 中执行的引擎动作需要该服务自身的参数校验、目录边界、超时和进程管理；Codex shell sandbox 不自动覆盖远端服务副作用。

### 3.5 持久化、resume、cancel 与 interruption

[rollout/recorder.rs:875](D:/Desktop/codex-main/codex-rs/rollout/src/recorder.rs:875) `RolloutRecorder::new`，`:1035` `record_canonical_items`，`:1074` `flush` 展示后台 JSONL 写入、确认与错误；历史读取/分页还依赖 thread-store/state 等层，产品不应直接改写这些内部文件。

[thread_processor.rs:3641](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/thread_processor.rs:3641) `thread_resume_inner` 读取历史并在 `:3974` 调用 `resume_thread_with_history`；[session/rollout_reconstruction.rs:169](D:/Desktop/codex-main/codex-rs/core/src/session/rollout_reconstruction.rs:169) `reconstruct_history_from_rollout` 处理 compaction checkpoint、TurnContext、response items、world state 基线与中断段。恢复的是代理的持久化上下文，不会天然恢复外部引擎进程或数据库事务。

取消链：[turn_processor.rs:1598](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/turn_processor.rs:1598) `turn_interrupt_inner` 校验 active turn，`:1637` 提交 `Op::Interrupt`，一般等 Core `TurnAborted` 后才答复；[tasks/mod.rs:537](D:/Desktop/codex-main/codex-rs/core/src/tasks/mod.rs:537) `abort_all_tasks`，`:911` `handle_task_abort` 取消 token、等待宽限期、abort 任务、记录中断标记，`:972` 先 flush 后发终态。pending approval 的清理由取消之后处理，防止把“用户停止”错写成“用户拒绝”。

还有独立的 [turn_suspension.rs:13](D:/Desktop/codex-main/codex-rs/core/src/session/turn_suspension.rs:13) `suspend_turn_and_shutdown`，用于保留 unfinished turn 的恢复路径；这与普通 interrupt 不同。不能把内部 suspension 行为等同于外部产品已获得可靠任务迁移。

设计要求：restart 后从 Runtime 读 thread/turn 状态，重建 UI；业务作业以 run ID、输入 hash 和 workspace commit 关联；旧审批不得恢复成有效新授权；未知外部工具完成状态先查询再决定是否重试。取消不回滚已写文件，恢复不是 exactly-once 外部执行。

### 3.6 MCP、Skills、Review 与多 Agent

- MCP：[tools/handlers/mcp.rs:196](D:/Desktop/codex-main/codex-rs/core/src/tools/handlers/mcp.rs:196) 捕获本次调用绑定、权限/呈现快照和取消 token，`:245` 选择输出截断策略；[codex-mcp/src/connection_manager.rs:975](D:/Desktop/codex-main/codex-rs/codex-mcp/src/connection_manager.rs:975) `call_tool` 在 `:1019` 合并 server/request timeout。`:148` 的并行能力依赖 read-only annotation 或 server 显式 opt-in，所以游戏写操作不得错误标成只读。
- Dynamic tools：`thread/start.dynamicTools` 在 [v2/thread.rs:145](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/v2/thread.rs:145) 明确标为 experimental；调用通过 `item/tool/call` 回到宿主。第一版优先 MCP 服务让三个 Agent 可共用确定性工具实现，但各自凭证、权限、任务/存档数据不共用。
- Skills：[ext/skills/src/extension.rs:185](D:/Desktop/codex-main/codex-rs/ext/skills/src/extension.rs:185) 的 `ContextContributor` 负责 skill catalog/context；`:379` turn input contribution，`:616` `read_main_prompt`；[app-server/src/extensions.rs:106](D:/Desktop/codex-main/codex-rs/app-server/src/extensions.rs:106) 注册 skills providers。适合携带仓库约定与测试流程，不能代替确定性访问控制或质量判定。
- Review：[turn_processor.rs:1548](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/turn_processor.rs:1548) `review_start_inner` 区分 inline 与 detached；后者使用 review-agent skill 创建评审线程。可复用 review 入口/结果流，但游戏不变量、引擎测试、误报评测必须由项目补充。
- 多 Agent：[core/src/agent/control/spawn.rs:274](D:/Desktop/codex-main/codex-rs/core/src/agent/control/spawn.rs:274) `spawn_agent`，`:917` `spawn_forked_thread`；[thread_manager.rs:1468](D:/Desktop/codex-main/codex-rs/core/src/thread_manager.rs:1468) `fork_thread_from_history`。首版一个执行 Agent + 独立评审就足够；并行分析可读同一快照，修改要各自隔离并由统一集成者收敛，避免把共享目录竞争当成协作能力。

## 4. 复用方式比较与 Python SDK 实证

| 路线 | 能控制什么 | 收益与代价 | 本项目结论 |
| --- | --- | --- | --- |
| CLI `exec` | 参数、输出 schema、JSON 事件、resume、进程取消 | 成本最低，适合批量评测；交互审批/持续双向控制有限 | 保留为基线和离线任务入口 |
| TypeScript SDK | thread/runStreamed/run；仍通过 exec | [exec.ts:91](D:/Desktop/codex-main/sdk/typescript/src/exec.ts:91) `run` 构建 exec 参数；[thread.ts:70](D:/Desktop/codex-main/sdk/typescript/src/thread.ts:70) 消费流 | 不因前端是 TS 就选择此 SDK 作为 Runtime bridge |
| 官方 Python SDK + App Server | 持续 JSON-RPC、生成类型、thread/turn 控制、通知 | 符合 Python 业务栈；要处理当前 SDK 人工审批缺口和版本漂移 | 首选，局部 adapter/fork |
| 直接 App Server client | 完整双向协议与 UI 请求 | 可完全控制，但要自担分流、关闭、背压、RPC 错误、事件竞态 | SDK缺口无法局部修复时才替代，别重复造已有transport |
| Rust 下游 fork/独立扩展 crate | sampling/context/工具生命周期内部、持久化策略 | 深层控制最强；编译、三平台、protocol及rollout兼容成本最高 | 依据失败实验触发，首版不强制 |
| 选择性重实现 / 全 Runtime | 可设计任意模型协议、状态机 | 同时失去成熟取消、恢复、sandbox、tool并发、compaction与评审链 | Coding Agent 不推荐全面重写；业务侧任务/证据状态机仍自主实现 |

官方资料确认 Python SDK 是 App Server JSON-RPC 客户端，并允许显式设置本地二进制；不能将 SDK 与 Runtime 当成互斥方案。[官方 SDK 文档](https://learn.chatgpt.com/docs/codex-sdk)。App Server 有稳定与 experimental 字段之分，websocket transport 当前文档标为 experimental/unsupported；首版用 stdio，并逐项锁定 schema 和 feature。[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)。这里不把整个 SDK/App Server 组合宣传为已经对本产品验证的生产稳定方案。

### 4.1 版本与 custom executable

- [sdk/python/pyproject.toml:19](D:/Desktop/codex-main/sdk/python/pyproject.toml:19) 依赖固定 `openai-codex-cli-bin==0.153.4`；本地 SDK 源码自身为 dev version。固定 runtime 依赖不意味着它与主控正在运行的 `0.159.0-alpha.12.1` 相同。
- [client.py:178](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:178) `resolve_codex_bin` 优先 `CodexConfig.codex_bin`；[client.py:196](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:196) 暴露 `codex_bin/config_overrides/cwd/env/experimental_api`；`:256` 默认启动 `app-server --listen stdio://`。
- [client.py:304](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:304) `initialize` 读取 serverInfo/userAgent 并发送 initialized。[runtime requirements:13](D:/Desktop/codex-main/sdk/python/src/openai_codex/_runtime_requirements.py:13) 下界是 `0.151.0`，支持 alpha hotfix 版本归一化；`:37` 可对 checkout 生成 schema 做字段检查。下界通过不代表所有 RPC/实验字段兼容。
- [async_client.py:57](D:/Desktop/codex-main/sdk/python/src/openai_codex/async_client.py:57) `AsyncCodexClient` 包装同步客户端，通过异步桥调用；不是第二套独立 transport。

交付锁定：SDK版本、Runtime版本/二进制hash、生成schema hash、provider配置能力集一起写 manifest。默认使用受测试版本组合；显式override用于下游Rust构建或已安装版本兼容试验，不能无提示跟随机器PATH升级。

### 4.2 审批缺口及离线验证

源码事实：

1. [client.py:833](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:833) `_default_approval_handler` 对 command/file approval 均返回 `accept`。
2. [api.py:85](D:/Desktop/codex-main/sdk/python/src/openai_codex/api.py:85) 与 `:316` 的高层 `Codex/AsyncCodex` 构造只接受 config；自定义 handler 位于低层 [client.py:217](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:217)。公开高层 ApprovalMode 当前只有 deny_all/auto_review（[_approval_mode.py:13](D:/Desktop/codex-main/sdk/python/src/openai_codex/_approval_mode.py:13)）。高层 `thread_start` 默认 `auto_review`（[api.py:138](D:/Desktop/codex-main/sdk/python/src/openai_codex/api.py:138)），映射为 on_request + auto_review；因此不能把低层默认handler行为描述成“所有操作绕过Runtime审批”。准确的缺口是：当审批请求实际到达客户端时，当前默认handler会接受，而且高层没有完整人工交互模式。
3. [client.py:863](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:863) `_reader_loop` 在唯一 stdout reader 内同步运行 `_handle_server_request`；等待浏览器点击的 handler 会暂停之后的 notification/response 分发。

离线 probe 在 Python 3.11.9、pydantic 2.13.4、packaging 26.0 下运行成功；未装依赖。注意 packaging 低于 pyproject 声明 `>=26.2`，本次仅证明使用到的版本比较/导入路径可工作，不构成完整依赖安装认证。

实验实际得到：两个默认审批为 accept；高层签名没有 handler；自定义二进制优先；`0.159.0-alpha.12.1` 通过版本下界；当 fake approval handler 等待时，排在之后的 fake delta 通知未被消费，解除等待后消费恢复。脚本没有修复这些行为，也没有运行上游测试集。它支持“人工审批工作台需要局部SDK改造”的判断，不支持“真实shell已被安全限制”的结论。

拟修复：reader 只解帧/分类；server request 入独立队列；dispatcher 发UI事件并异步等待；request绑定 thread/turn/item/connection generation；超时、断线、取消和未知请求 fail closed；迟到/重复答复拒绝；只允许一次答复；关闭时唤醒所有waiter。继续复用生成类型、版本协商与通知路由。默认审批改动必须有明确回归测试，不能只将源码中的 accept 字符串替换成 decline 就声称完工。

## 5. 推荐的 4 项游戏研发二次开发

| 优先级与工作 | 放在哪层、为何 | 验证设计 |
| --- | --- | --- |
| P0 人工审批、取消与恢复适配 | Python SDK 局部补丁 + 业务事件适配层；缺口是宿主交互/事件消费，不是Rust模型推理 | fake transport覆盖审批期间通知、并发thread、interrupt、断线、超时、迟到答复；真实binary+fake model触发工具审批；在隔离fixture验证允许/拒绝/取消无误执行 |
| P0 游戏开发工具与可复现证据 | Python MCP服务 + 引擎runner；`inspect_rules/run_headless/run_engine_tests/read_run_artifact` 等固定接口，参数schema、seed、build hash、超时、输出界限和run ID由确定性代码负责 | 相同commit/config/seed复现；超时/错误码/大输出/重复请求/取消/读写边界；模型只拿摘要，UI能打开完整日志/回放 |
| P1 变更范围与游戏上下文包 | 工作区管理 + 代码索引/rg/符号与资源引用工具 + 任务manifest + Git diff审查；先解决“知道改什么、哪些文件不允许改、改完用什么证明” | baseline为裸Codex+普通仓库说明；对照约束违规率、关键依赖命中率、实际任务通过率、无效检索量/token；上限/脱敏/过期hash验证 |
| P1 评审与执行证据回放 | Python任务ledger + App Server事件投影 +独立review；区分模型推测、测试事实和人工决定 | 注入已知游戏缺陷，统计review precision/recall；每条结论绑定代码快照/测试run；重启UI及Runtime后恢复相同终态；失败案例可单步复盘 |

P4、UE/Maya跨端、复杂多Agent并发可作为后续适配：首版 Git + 单一游戏引擎先形成闭环。P4的锁定、changelist与提交语义应单独建adapter并使用真实服务器验证，不能声称Git包装自然覆盖P4。

## 6. Rust 扩展的真实边界与启动条件

[ext/extension-api/src/contributors.rs:109](D:/Desktop/codex-main/codex-rs/ext/extension-api/src/contributors.rs:109) `ContextContributor` 支持 thread context、turn context、world state；`:146`/`:151` 的 `retain_world_state_after_compaction` 明确只保留该contributor自己的有界元数据，不能把全部渲染文本塞进去。它恰好适合将游戏规则快照hash、选定证据ID等保留为重建依据。

[contributors.rs:381](D:/Desktop/codex-main/codex-rs/ext/extension-api/src/contributors.rs:381) `ToolLifecycleContributor` 是观察接口：dispatch排除nested code-mode，command start包含code-mode，start并不代表审批/创建进程已成功，blocked/cancelled的finish未必有对应start。它不提供任意改写调用/拒绝的返回值；改写用hooks，拥有工具用ToolContributor，授权决策另有 `ApprovalReviewContributor`（`:422`）。不能把telemetry回调当安全gate。

[app-server/src/extensions.rs:51](D:/Desktop/codex-main/codex-rs/app-server/src/extensions.rs:51) `thread_extensions` 在Rust构建中使用 `ExtensionRegistryBuilder` 注册具体crate（`:97`附近包含guardian/memories/MCP，后续含skills）。虽是pub trait，仍使用上游workspace的Rust类型和内部生命周期；没有查到稳定动态加载ABI或任意外部Python插件安装机制。

只有出现下列证据才启动一个窄Rust补丁：

- 20个以上包含多次自动compaction的真实长任务中，外部manifest工具＋阶段证据包仍不能满足既定约束保持目标，而可靠重建需要每个sampling step自动更新world state。
- 事件回放出现无法由公共item/turn/工具run修复的归因缺口，且工具生命周期contributor能直接提供所缺字段；先写出最小可复现失败及未修改Runtime的对照。

此时新建独立 `game-dev-extension` crate，最少注册改动；遵守上游AGENTS的“resist adding code to codex-core”。必须做compaction/resume/fork、异常/中断、上下文大小与cache稳定性集成测试；保证新增fragment有硬上限，无超过10K token的item，新增超过1K token片段按上游要求人工审阅。若改protocol，更新schema；改依赖同步锁文件；使用 `just test -p ...`，不直接cargo test。本阶段没有执行这些构建/测试，因此Rust路线为条件设计。

参考现成测试位置：`core/tests/suite/compact_resume_fork.rs`、`step_settings_compaction.rs`、`approvals.rs`、`unified_exec.rs`、`review.rs`；`app-server/tests/suite/v2/turn_interrupt.rs`、`thread_resume.rs`、`dynamic_tools.rs`。这些是后续编写测试的切入点，并非本阶段通过记录。

## 7. Responses 与 Chat Completions 兼容性

[model-provider-info/src/lib.rs:97](D:/Desktop/codex-main/codex-rs/model-provider-info/src/lib.rs:97) 给出移除chat的错误；`WireApi`只有Responses（`:104`），Deserialize遇到`chat`明确返回错误（`:127`）。[core/src/client.rs:2226](D:/Desktop/codex-main/codex-rs/core/src/client.rs:2226) `stream` 只匹配 `WireApi::Responses`，选择WebSocket或HTTP Responses路径。

结论限定于这个参考快照：**支持自定义base URL ≠ 支持Chat Completions wire format；旧项目chat provider成功 ≠ Codex provider兼容**。也不能据此反推某家厂商永远没有Responses接口。模型供应商能力会变，Coding Agent选择通过实际契约测试的Responses provider；Verification/NPC可按自己业务需要选择不同provider接口。

锁定前需跑矩阵（每项记录请求/响应脱敏fixture与Runtime版本）：

| 项目 | 必验内容 |
| --- | --- |
| 基本文本/SSE | response.created、text delta、output item完成、response.completed、断流、错误码与重试 |
| 工具调用 | function/custom tool、call ID对应output、多工具、工具失败、并行支持；不要用单轮文本冒充兼容 |
| Context | 历史重送、reasoning item、structured output、token usage、上下文溢出、所选compaction路径 |
| 特性关闭 | 不支持WebSocket时明确关闭；不支持tool_search/namespaces/code-mode相关格式时验证可用配置或判定不兼容 |
| 取消与恢复 | 长流中断、重新开进程resume、工具结果中断后的处理、无重复外部动作 |
| 成本与质量 | 同一任务集上完成率、有效token/cached token口径、延迟、成本；provider报告不完整时标缺失 |

不推荐首版自建“Responses→Chat Completions”通用网关：需要映射工具、reasoning、压缩、stream和恢复语义，问题会转移到一个新的Runtime边界；只有明确需要的模型无法通过Responses且收益足够时另立适配实验。

## 8. 下一阶段最小可交付与验收

第一个Coding交付阶段做“一个Windows本地工作台中的小代码任务”：连接固定Runtime，创建隔离fixture repo；显示流式item与终态；运行预置无害测试；触发一次人工审批并验证拒绝/接受/取消；重启后恢复任务；最后给出diff和绑定run ID的证据。模型先用可控fake Responses覆盖协议路径，再选真实provider做少量真实任务。

必交：SDK adapter局部diff及回归fixture、固定版本manifest、启动脚本、工具runner契约、事件ledger、成功与失败录像/回放、数据驱动的验收报告。首版验收需证明审批期间仍能接收其他thread事件；interrupt不会被审批handler阻塞；重复答复/重启后旧答复不能执行工具；允许范围外写入失败；工具取消和任务终态一致。

评测分开记录：协议正确性、确定性工具正确性、模型任务效果。用CLI/原SDK作为工程基线，裸Codex+仓库说明作为能力基线；不要用模型最后一句“测试通过”充当测试证据，也不要把fake模型协议测试汇总成真实任务成功率。

当前局限：未验证真实provider、原生sandbox与引擎实际执行；未验证SDK生成schema对已装alpha的全部兼容性；未测试Rust扩展编译和跨平台；未证明任意外部工具的exactly-once恢复；参考源码没有可追踪commit。后续先用这些已发现边界组织验收，不通过推测补齐完成状态。

## 9. 方案评审补充：独立 command/exec 执行后端（仅源码确认）

复核主控提出的“无模型凭据的独立 App Server 执行进程＋`command/exec`＋显式sandboxPolicy”后，未发现它与当前参考源码明显矛盾。该路线可以作为G0首选候选，**尚未证明已装二进制或本机Unity可用**。

- [CommandExecParams:21](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/v2/command_exec.rs:21) 明确 standalone argv command、不创建thread或turn。[message_processor.rs:975](D:/Desktop/codex-main/codex-rs/app-server/src/message_processor.rs:975) 要求连接initialize；`:1837`直接分发至command processor；[command_exec_processor.rs:35](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/command_exec_processor.rs:35) 只检查local environment，然后构造执行请求。此链未见模型推理或模型登录前置，也没有ThreadManager递归调用。启动仍会装配App Server各模块，因此“无凭据”须由独立配置/认证目录与进程环境实现，不能仅假定不发模型请求便不会加载已有认证。
- `command/exec`是受信任宿主直接执行入口，不经过一次模型turn的工具授权对话。Broker必须先完成命名profile、任务权限、固定argv/cwd、参数和授权校验，再发RPC；不能期待它自动弹出Coding thread中的审批卡。
- [command_exec_processor.rs:154](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/command_exec_processor.rs:154) 先按shell environment policy生成env，再合并请求env。**请求env是覆盖/删除项，不是完整环境替换。** 应清理执行App Server的启动环境，使用受测的`inherit=none`/必要平台变量白名单策略，再传受限env；不能只提供少量env键就声称其他变量已排除。
- [command_exec_processor.rs:202](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/command_exec_processor.rs:202) 在使用legacy `sandboxPolicy`时，sandbox基准cwd来自server config.cwd，而非本次请求cwd。执行进程应固定到对应任务worktree/受测sandbox根；启动目录不能是控制面仓库并期待请求cwd自动收紧全部根。`:245`设置policy时会校验约束，错误应显式失败。
- [command_exec.rs:178](D:/Desktop/codex-main/codex-rs/app-server/src/command_exec.rs:178) 的WindowsRestrictedToken路径拒绝TTY、stdin/out streaming；`:184`还拒绝非默认output cap（含关闭cap）。`:205`转入buffered `execute_env`；[processor:189](D:/Desktop/codex-main/codex-rs/app-server/src/request_processors/command_exec_processor.rs:189) 将timeout配置成执行expiration。必须显式启用有限timeout，不用`disableTimeout`。
- [command_exec.rs:437](D:/Desktop/codex-main/codex-rs/app-server/src/command_exec.rs:437) 拒绝此分支write/terminate/resize；[同文件:388](D:/Desktop/codex-main/codex-rs/app-server/src/command_exec.rs:388) 的connection_closed只对Active会话发送Terminate，UnsupportedWindowsSandbox没有该控制通路。因此关连接/丢弃RPC也不能宣称任务已终止。

结论：首版允许短批次、buffered、硬超时与`cancel_requested`等待在途退出的方案准确；低延迟停止长Unity作业不是这条分支已经具备的能力。G0必须验证timeout是否清理实际后代进程、输出截断与产物完整性、路径/网络边界、断线期间作业状态以及Unity授权/缓存。进程树回收不能保证则禁用该自动profile；如即时终止成为必要需求，另做窄执行层/Rust改动及对照测试，不能移除sandbox解决。以上均为源码阅读结论，本次未运行此RPC或任何候选代码。
