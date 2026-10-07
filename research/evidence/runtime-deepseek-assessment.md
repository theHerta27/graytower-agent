# G0 DeepSeek / Codex 兼容性证据

日期：2026-10-04。结论：**单 Agent Coding 与原生 inline Review 已有最小真实模型证据；SDK dynamicTools→官方 MCP client→同一 MCP server 的窄转接已有真实本地运行证据；完整游戏工具、原生多 Agent 和生产配置尚未通过 G0。** 本记录是兼容性实验，不是产品实现或模型质量验收。

## 本次实测

- 真实 CLI：`codex-cli 0.159.0-alpha.12.1`，SHA-256 `1722907aa64401bcc9b34467ef5c2af43f6aef9a5045ef04d11d19dfae4589fb`。
- Python 3.11.9；`D:/Desktop/combat-foundation/.venv/Scripts/python.exe`；pydantic 2.13.5、packaging 26.3。
- SDK 直接导入只读参考树 `D:/Desktop/codex-main/sdk/python/src`，版本 `0.0.0-dev`。其 pyproject 依赖 CLI `0.153.4`，本次用显式 `codex_bin` 测已装 alpha，**未验证 0.153.4 配对，也未证明整个 SDK schema 兼容**。
- [离线结果](runtime-deepseek-20261004-152433/result.json)：默认模型元数据、显式 catalog、dynamic tool 往返、inline Review、原生子 Agent V1、V2 共 6 场景通过。父/子/Review 请求均为同一本地 provider 上的 `deepseek-flash`。没有执行模型生成的 shell 或文件修改。
- [真实结果](runtime-deepseek-20261004-152744/live-result.json)：3 次请求均为 `https://api.deepseek.com/responses`、`deepseek-flash`、HTTP 200。前 2 次完成 immutable `read_fixture` function 调用、function_call_output 回传与正确最终值；第 3 次由 `review/start` 原生 inline Review 完成一个内嵌整数相加函数的结构化无缺陷评审。
- 真实请求总输入 7,513 token，其中 cache hit 1,792，输出 159（含 review reasoning 50）。按当天官方 Flash 非高峰价格估算约 **USD 0.000959**，不是账单实扣证明。三个请求分别封顶 2,000 output tokens，总授权 cap 6,000，未再发模型请求。
- 真实 smoke 使用本地审计 relay：仅加输出 cap，并把工具列表收窄为一个只读 function（Review 为无工具），SSE 工具调用校验后才转给 Runtime；无 Responses→Chat 翻译。因此**不是未改请求的完整生产工具兼容证明，也不测实时流延迟**。
- 所有运行均使用新的子进程 `CODEX_HOME`，清理继承环境，没有读取用户 Codex auth。旧游戏 `.env` 只在内存读取指定 DeepSeek key；证据无 key/auth header。配置键：`COMBAT_API_BASE=https://api.deepseek.com/`、`COMBAT_MODEL=deepseek-flash`、非空 `COMBAT_API_KEY`。3 次 200 证明该 key 当时可用于该 endpoint/model。旧 Coding 根/backend 未发现 `.env`。

## 窄 MCP 转接补充实测（无新增模型费用）

[结果](runtime-deepseek-20261004-154144/dynamic-mcp-result.json)、[MCP 原始线协议](runtime-deepseek-20261004-154144/mcp-wire.jsonl)、[依赖锁定](runtime-deepseek-20261004-154144/dependency-lock.txt)。真实 CLI/官方 Codex SDK 通过 dynamicTools 暴露普通 function `game_read_fixture`；独立的官方 MCP Python SDK 1.26.0 `ClientSession` 将其映射为同一只读 fixture 服务的 `read_fixture`。服务进程与配置保持由受信任业务宿主管理，Runtime 仍拥有全部模型采样/工具续步循环。

- 5 次本地 fake Responses 由 Runtime 自动续步，未改 wire API；工具面无 namespace，无 Responses 语义网关，未改 Rust。
- Runtime call ID `runtime_success` / `runtime_mcp_error` 经 MCP `_meta.runtime_call_id` 到达服务；对应真实 MCP JSON-RPC ID 为 2 / 3。thread/turn/call ID、动态名称、服务名与 MCP 工具名均有映射记录。
- 成功返回 `IMMUTABLE_MCP_FIXTURE`；未注册的 `game_write_fixture` 被 Runtime 拒绝且未进入 Adapter；注册工具的非法参数被 Adapter 拒绝且未进入 MCP；服务注入 `isError=true` 后 Adapter 返回 dynamic `success=false` 与错误文本，Runtime 继续采样并完成 turn。
- MCP 工具调用恰好 2 次，初始化/列工具各一次，客户端 owner 正常关闭。客户端依赖只安装到本次 `research/evidence/runtime-deepseek-mcp-client-deps`，未修改旧项目环境。
- **限制：**这是串行诊断 handler，会阻塞当前 SDK 的 reader，不是已交付的异步生产 Adapter。3 秒 MCP timeout 不证明 worker 已停止、事务回滚或不再产生副作用。未测取消/断线/重复调用/receipt/进程树清理。既有真实 DeepSeek function smoke 与本次本地 MCP 转接是分段证据，尚非真实 DeepSeek→生产游戏 MCP 的端到端验收。

## 必须保留的兼容边界

1. **MCP 也是 namespace。** [本地 MCP schema 结果](runtime-deepseek-20261004-153025/result.json) 在 direct 模式仍发送 `type=namespace` / `mcp__immutable_fixture`；该场景只证明声明捕获及文本 turn 完成，**没有证明 MCP 调用可被 DeepSeek执行**。源码 `core/src/tools/handlers/mcp.rs:497`、`:525` 固定生成 Namespace。
2. **原生多 Agent V1/V2 都发送 namespace**；V2 回传历史还出现 `agent_message`。源码 `core/src/tools/multi_agent_tool.rs:87` 及 `core/src/tools/handlers/multi_agents_spec.rs:81`。DeepSeek 官方兼容表只明确 function 与 apply_patch custom；其他工具类型/未列 input 会被忽略。因此这些路径是待实测契约风险，不能宣传“全原生兼容”。
3. 官方支持 `custom apply_patch`，不支持其他名字的 custom（400）。显式 catalog + direct 模式的基础 Coding 工具为 function/custom apply_patch，符合文档类型集合；本次真实模型没有执行 apply_patch、shell、MCP、compaction、恢复或取消。
4. DeepSeek API 无服务端会话；需完整历史重送，reasoning 只支持明文 content，developer 被当作 user，部分高级字段被忽略。权限与游戏约束必须在确定性业务层执行。源码 custom provider 的 remote compaction 为 Unsupported，走同 turn context 的本地摘要路径；未做真实长上下文验证。
5. `review/start` 的 inline 与审批 `auto_review` 是不同链路。SDK 高层默认 auto_review 不能用于“严格单模型”且未审计的成品启动；本实验显式 `approvalPolicy=never` / `approvals_reviewer=user`。生产人工审批仍需原有异步 adapter 工程。

## 模型继承与防止隐藏调用

- Review：`core/src/tasks/review.rs:103` 克隆当前配置，`:123` 选 `review_model`，缺省回退当前模型。detached Review 在本参考版已 deprecated，paginated thread 不支持；独立 review 用新 thread + inline，不预设永久 reviewer 角色。
- 子 Agent：`core/src/agent/child_config.rs:107` 从有效父配置构建；`:138` 复制 turn provider；`:204` 支持 `agents.default_subagent_model`；角色覆盖见 `core/src/agent/role.rs:35`、`:90`，允许 model 但不投影 model_provider。角色/显式 model/冷恢复均需纳入 adapter 的模型白名单。
- 审批自动评审：`ext/guardian-reviewer/src/model.rs:17` 优先 catalog/`auto_review_model_override`，否则父模型回退；不是当前参考版无条件硬编码 OpenAI model。`ext/guardian-v2/src/sync_reviewer/reviewer_config.rs:12` 克隆父 provider。严格单模型应固定 DeepSeek catalog、显式审批模式，并对自动评审另做真实验收；不能只设顶层 `model`。
- 可新增的业务 adapter：独占受测 runtime/config、DeepSeek-only model allowlist、拒绝未授权 turn/model/profile/role 覆盖、记录实际 model/provider/usage、禁止静默跨 provider 降级；关闭未验收的 apps/记忆/多 Agent/审批自动评审等隐式模型入口。恢复旧 thread 时核对持久化 provider。还需实际网络出口策略，日志观测不是隔离证明。

## G0 决策建议

- 保留 **Codex Runtime + 官方 Python SDK + 业务 adapter**，单 Agent 作能力和成本基线；按任务证据决定是否启用 Review/subagent，无固定多角色流水线。
- 暂不建设通用 Responses→Chat 网关。基础 Responses/函数工具/inline Review 已有真实证据。
- **优先落实已获得本地证据的有限业务转接：SDK dynamicTools→官方 MCP client→原 MCP/Broker。** 它只映射受信任工具目录、参数与结果，保留 Runtime 循环，不造通用 Responses 网关、不改 Rust。需补异步 SDK server-request 分流、审批、取消、call ID/receipt、schema/错误投影及真实 DeepSeek→游戏工具端到端验收；不能冒称已复用 Runtime 原生 MCP 调用链。原生 MCP namespace 与原生 subagent 仍单独验证，不作为此方案默认依赖。
- SDK 人工审批 reader 分流、幂等 receipt、worktree、游戏/Unity工具和证据验收仍是自有工程；本次未实现它们。

## 复核入口与失败保留

- `research/probes/runtime_deepseek_probe.py`：仅本地 fixture；可传 `mcp_direct` 单场景。
- `research/probes/runtime_deepseek_mcp_fixture.py`：只读本地 MCP。
- `research/probes/runtime_deepseek_dynamic_mcp_probe.py`：官方 MCP client 的动态工具窄转接、本地模型 fixture、拒绝与错误映射。
- `research/probes/runtime_deepseek_live_smoke.py`：收费 smoke，**不要无新授权重跑**。
- `runtime-deepseek-20261004-152202` 保留早期探针错误：Review 监听了错误 SDK 队列；V1 fixture 未发送 namespace。这是探针错误，修正后的上述 6 场景通过，不应计作 Runtime 缺陷。
- `runtime-deepseek-20261004-152720` 保留网络 sandbox PermissionError；请求未到 DeepSeek，之后按权限流程升级并成功。

官方资料（本次实际打开）：[OpenAI Python SDK](https://learn.chatgpt.com/docs/codex-sdk)、[OpenAI 配置](https://learn.chatgpt.com/docs/config-file/config-reference)、[DeepSeek Responses 兼容表](https://api-docs.deepseek.com/guides/responses_api/)、[DeepSeek Codex 配置](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)、[DeepSeek 价格](https://api-docs.deepseek.com/quick_start/pricing/)。网页证明厂商声明；本地 fixture 证明客户端行为；真实 smoke 只证明所述受限路径，三者不可互相替代。
