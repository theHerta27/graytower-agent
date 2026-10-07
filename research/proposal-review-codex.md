# 技术方案 Codex 章节独立审查

日期：2026-10-03。审查对象为本轮 `TECHNICAL_PROPOSAL.md` 与 `IMPLEMENTATION_ROADMAP.md`；未修改两份主文档。下列主文档行号对应审查时版本。依据为本地 Codex 源码与已保存离线 SDK 实验，补查当前官方 App Server 文档。

结论：**主线可保留，建议冻结前补齐三处设计边界和一处表述。** SDK 局部补丁、Rust 条件扩展、上游 rollout 与产品状态分离、真实 provider/Windows 引擎单独验收等定位准确。没有发现应推翻 App Server＋Python 业务层方案的证据。

## 1. [P1] 人工审批需同时改变请求路由，仅注入 handler 不够

位置：[总体方案:60](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:60)、[路线:28](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:28)。

总体方案“默认command/file审批返回accept”省略了发生层次；路线只要求显式 handler/异步队列，尚未写出从高层默认 `auto_review` 切换到人工路由。实施者若仅把 handler 参数贯穿高层API，仍会沿默认 auto-review 路径运行，不保证提权请求都到人工UI。

源码证据：

- [api.py:138](D:/Desktop/codex-main/sdk/python/src/openai_codex/api.py:138) 的高层 `thread_start` 默认 `ApprovalMode.auto_review`；`:154` 将其转换为协议参数。
- [_approval_mode.py:30](D:/Desktop/codex-main/sdk/python/src/openai_codex/_approval_mode.py:30) 将 auto_review 映射为 `approvalPolicy=on-request` 与 `approvalsReviewer=auto_review`。高层当前只有 deny_all/auto_review。
- [v2/shared.rs:245](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/v2/shared.rs:245) 明确 `ApprovalsReviewer::User` 与 `AutoReview` 控制请求路由。
- [client.py:833](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:833) 的 accept 是**实际送达客户端的 command/file approval 请求的默认 handler 响应**；不能描述成所有操作都绕过 Runtime 审批。
- [client.py:863](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:863) 证明同步handler阻塞唯一reader，已有 [fake-reader实验](D:/Desktop/mihoyo-agent-project/research/evidence/codex-sdk-static-probe-result.json)复现。

建议主方案改为：“高层默认使用 auto_review；若 command/file approval 请求实际到达客户端，低层默认handler返回accept。当前高层缺少完整人工审批模式，且低层同步handler会阻塞事件读取。”

G0补一项：在配置要求允许的情况下暴露人工模式，明确发送 `approvalPolicy=on-request`、`approvalsReviewer=user`，同时将handler贯穿sync/async API；managed requirements不允许时清楚报错，不绕过。用真实binary＋fake模型触发审批，验证“用户未答复时无工具执行、拒绝后无执行、批准仅执行当前请求一次”。不要把修改fallback handler视为已经证明完整人工授权。

## 2. [P1] 明确 MCP Broker 是独立执行权限边界，并双入口验收

位置：[总体方案:94](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:94)、[总体方案:203](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:203)、[总体方案:240](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:240)、[路线:30](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:30)。

主方案已正确要求 Unity runner 使用受限账户/沙箱，且拒绝把参数模板当隔离；但架构图中的 Codex→MCP→Broker/Worker 没有明确指出 **Codex shell sandbox 不会自动成为 MCP 服务及其子进程的沙箱**。G0权限矩阵若只通过Codex内置shell运行，将不能证明后续 `run_game_tests` MCP入口同样受限。特别是 MCP服务可能由控制面先启动，随后以自己账户创建候选代码进程。

源码证据：

- Shell路径在 [tools/orchestrator.rs:125](D:/Desktop/codex-main/codex-rs/core/src/tools/orchestrator.rs:125) 选择/执行sandbox策略。
- MCP路径在 [codex-mcp/connection_manager.rs:975](D:/Desktop/codex-main/codex-rs/codex-mcp/src/connection_manager.rs:975) 校验server/tool并通过客户端RPC调用，`:1031` 发 `call_tool`。
- [mcp_tool_call.rs:847](D:/Desktop/codex-main/codex-rs/core/src/mcp_tool_call.rs:847) 对声明支持能力的服务器可附加sandbox-state metadata；`:856` 未声明时直接返回原meta。**传递策略元数据不等同于服务器执行OS隔离。** 应由MCP服务/Broker显式执行并验证。

建议补句：“MCP是工具协议边界，Broker负责自己的权限、工作区、网络、进程树和取消；不得依赖调用者Codex shell sandbox的隐式继承。”

G0把同一权限矩阵分别跑在①内置shell ②MCP `run_game_tests`/Broker入口；从候选测试代码主动尝试工作区外写入和未授权网络。记录实际账户、sandbox配置、允许根与子进程，而非只检查父进程配置。

## 3. [P2] item/turn ID 不能用作 delta 事件唯一去重键

位置：[总体方案:191](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:191)。

“使用应用序号支持SSE重连”正确，但紧接着“渲染去重以item/turn身份为主”容易被实现成删除同一item的后续增量。文本、命令输出的所有delta共享item/turn，甚至相同delta文本可以合法重复。若按这些身份或文本hash去重，UI会丢输出。

源码证据：[v2/item.rs:1437](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/v2/item.rs:1437) `AgentMessageDeltaNotification` 只有 `thread_id/turn_id/item_id/delta`；[同文件:1506](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/v2/item.rs:1506) command output delta同样如此，没有每delta唯一ID。

建议精确区分：

- 事件落入应用ledger时分配 `(runtime_generation, application_seq)` 或唯一event ID；SSE重连按应用序号重放与去重。
- item/turn ID是**投影对象的身份**，用于upsert最终item/turn状态，不用于丢弃同item内的增量事件。
- Runtime重启/重连后，用完整item/history快照进行替换/对账；不要靠重复文本hash猜测增量是否已经处理。

G0新增用例：同一item连续两个完全相同的delta都必须保留；同一应用event因SSE重连重复交付则只处理一次；终态快照到来后文本与最终item一致。

## 4. [P2] 取消验收区分 turn 停止与外部作业停止

位置：[总体方案:191](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:191)、[路线:29](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:29)、[路线:77](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:77)。

现有“不自动重放未知副作用、history不恢复外部进程/Git状态”准确，应保留。建议进一步明确：收到 `interrupted` 仅证明该turn已进入中断终态，不能将它直接作为所有MCP引擎Worker和持久终端已经退出的收据。

源码证据：[tasks/mod.rs:911](D:/Desktop/codex-main/codex-rs/core/src/tasks/mod.rs:911) 的 `handle_task_abort` 取消turn task并记录中断；[tasks/mod.rs:206](D:/Desktop/codex-main/codex-rs/core/src/tasks/mod.rs:206) task abort默认清理hook为空；[tasks/mod.rs:893](D:/Desktop/codex-main/codex-rs/core/src/tasks/mod.rs:893) 的 `close_unified_exec_processes` 是独立入口，[session/handlers.rs:61](D:/Desktop/codex-main/codex-rs/core/src/session/handlers.rs:61) 单独处理 `clean_background_terminals`。外部MCP服务的操作完成、取消和进程树仍需服务端确认。

建议G0分别记录：turn status、Broker job status、实际子进程退出、可复用/未知的artifact收据。取消时按run ID请求Worker停止并设宽限/强制终止策略；状态未确定先标 cancelling/unknown，不能显示“所有执行已停止”。这只是细化已选状态边界，无需更换Runtime。

## 5. 审查通过的关键判断

| 项目 | 判断与证据 |
| --- | --- |
| SDK局部patch而非另写Loop | [总体方案:176](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:176)、路线G0明确保留生成类型/路由/版本协商，业务层不决定模型下一次工具调用，定位正确 |
| 上游版本风险 | [总体方案:58](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:58)和[路线:27](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:27)准确区分无git参考树、SDK依赖0.153.4、安装0.159alpha；没有把版本下界通过当全兼容 |
| custom executable | 后续如需补实现细节，可引用 [client.py:178](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:178) `CodexConfig.codex_bin` 优先；不需要自写transport来选择binary |
| App Server实验性质 | 当前[官方文档](https://learn.chatgpt.com/docs/app-server)明确app-server command/WebSocket transport为实验性质；主方案要求固定版本与协议回归合理。stdio减少传输复杂度，不消除版本风险；feature级experimental与接口整体成熟度是不同维度 |
| Rust扩展条件 | [总体方案:195](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:195)准确说编译期机制、非稳定插件ABI；[contributors.rs:146](D:/Desktop/codex-main/codex-rs/ext/extension-api/src/contributors.rs:146)支持compaction后有界metadata保留，不支持无限历史保留的承诺 |
| 持久化与RNG区分 | 游戏部分明确完整RNG状态/决策阶段，路线限制同构建恢复；没有用Codex rollout来证明游戏随机序列恢复，也没有将seed等同完整存档。Coding rollout与业务作业分别对账的类比边界正确 |
| 动态provider | 主方案没有从旧chat兼容推断Codex兼容；G0要求有效工具调用而非仅文本smoke，正确。长上下文测试应明确涵盖所选compaction路径及function/custom工具格式 |
| MCP/Skills/Reviewer | Skills不能代替权限，Reviewer只读，Git与P4验收区分均正确；多写者各自worktree避免共享修改竞争 |

## 6. 补丁实现时的小边界

“未知请求拒绝”应在实现中使用相应JSON-RPC错误（例如不支持方法），不要对所有服务端请求都回 `decision=decline`；动态工具、用户输入和审批的响应schema不同。遇到未知/不支持请求不能挂起reader，也不能误发成功空对象。[common.rs:1771](D:/Desktop/codex-main/codex-rs/app-server-protocol/src/protocol/common.rs:1771) 后分别定义多种server request类型。

本次审查只写此报告，不改主方案、不重跑模型、Rust构建或sandbox。建议修正文案/门槛后继续既定G0与M1，不需要新增一个“全面Runtime重写”阶段。
