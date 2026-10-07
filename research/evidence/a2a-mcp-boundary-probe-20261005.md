# A2A / MCP / LangGraph 本地协议探针

日期：2026-10-05 Asia/Shanghai；原始 UTC 时间为 2026-10-04 晚间。独立研究 fixture，零模型调用、零付费、无游戏引擎、无生产身份；没有修改产品 src、全局环境或历史冻结证据。

**37 项功能断言通过，新增 4 项测试通过，现有 16 项测试通过。生命周期不合格，production G0 不能通过。** [最终 result.json](a2a-mcp-test-20261005-e8qqhg02/result.json) 明确写有 pass_scope 与 production_ready:false。SDK 队列清理缺陷需要上游修复或受测最小补丁，再回归 terminal 拒绝、client 关闭等负例；不能用功能 PASS 掩盖这一门槛。本探针与真实游戏冻结候选探针独立，不构成已接通的真实 QA Agent。

## 接线、版本与证据

[脚本](../probes/a2a_mcp_boundary_probe.py)与[测试](../probes/test_a2a_mcp_boundary_probe.py)使用 research/.venv-protocols/Scripts/python.exe，Python 3.11.9；a2a-sdk 1.2.1、mcp 2.3.0、langgraph 1.2.12、checkpoint 4.2.0、checkpoint-sqlite 3.1.1、pydantic 2.13.5、uvicorn 0.54.0、starlette 1.7.0。官方固定源码身份见[版本审计](a2a-mcp-langgraph-audit-20261005.md)。

实际链路：官方 A2A client → 127.0.0.1 HTTP JSONRPC/SSE → 官方 routes/DefaultRequestHandlerV2 → AgentExecutor → 确定性 LangGraph → 官方 MCP Client → 独立 stdio MCPServer 进程。沙箱允许本次 loopback，无需提权。同一张 [Card](a2a-mcp-test-20261005-e8qqhg02/agent-card.json) 有一个 verify_candidate skill、JSONRPC / protocolVersion 1.0；两个固定测试身份分别代表 Config/Coding，仅访问 Verification。公开 fixture bearer 不是生产 OAuth。MCP 真正经 server/discover 协商 2026-07-28。

| 功能 | 实际结果与边界 |
| --- | --- |
| 结论 | 三个 TASK_STATE_COMPLETED 分别携带 PASS / FAIL / INCONCLUSIVE；固定数值规则，不是模型质量 |
| 身份 | body author 不改变可信 owner；跨 owner Get/Cancel/续输入为 TaskNotFoundError，List 按 owner 裁剪，匿名 HTTP 401 |
| 输入 | 传 candidate ref/hash，MCP 校验 bytes hash；错误 hash 拒绝；运行前后候选未变 |
| 幂等 | 同业务 ID/冻结 payload 的新消息产生不同 A2A Task，复用原 verification_run_id、报告和证据；新增 validate 次数及逻辑 reservation 均为 0；异 payload REJECTED |
| 澄清 | INPUT_REQUIRED 同 Task 补 goal 完成；错误 context 为 InvalidParamsError，终态续输入 UnsupportedOperationError；续输入先发 Task snapshot |
| 流 | 读首 Task 后关闭流，服务继续；Subscribe 首事件当前 Task，最终 Get 读报告 |
| 取消 | hold 场景为 CANCELED，executor 观察到 CancelledError；已完成取消为 TaskNotCancelableError；不证明外部进程树回收 |
| 持久化 | 官方 DatabaseTaskStore/aiosqlite 写入，另一 engine/store 实例按 owner 读回同 Task；不证明进程重启后的工作流恢复 |
| MCP | 实际 list_tools/call_tool；仅 query_schema、validate、read_artifact；未注册 candidate_write 报错；结构化结果/证据 readback 一致 |

[HTTP wire](a2a-mcp-test-20261005-e8qqhg02/http-wire.json)、[流事件](a2a-mcp-test-20261005-e8qqhg02/stream-events.json)、[MCP 调用](a2a-mcp-test-20261005-e8qqhg02/mcp-tool-calls.jsonl)、[MCP 返回](a2a-mcp-test-20261005-e8qqhg02/mcp-responses.jsonl)、[executor 事件](a2a-mcp-test-20261005-e8qqhg02/executor-events.json)、候选、证据和两份 SQLite 均保留。wire 为标准 SendMessage/SendStreamingMessage/GetTask/ListTasks/CancelTask/SubscribeToTask，没有替代协议。

## 失败记录与修正

- 普通 `-> dict` 在 MCP 2 只有文本 content，structured_content=None，触发我方图 TypeError。[w92jrw4k](a2a-mcp-20261005-w92jrw4k/result.json)与[esjfpe0e](a2a-mcp-20261005-esjfpe0e/result.json)保留。按[固定 SDK 类型处理源码](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/utilities/func_metadata.py)改为 `dict[str, Any]` 并显式 structured_output=True，在注册时拒绝无效结构类型，没有静默解析文本补救。
- 初版我方续输入 executor 不发 Task，V2 send-stream 的 include_initial_task=False 不会代生成；客户端 StopIteration 见[nsfojnzy](a2a-mcp-20261005-nsfojnzy/result.json)。最终显式先发 resumed Task，并断言首事件；Subscribe 则由 SDK 生成 snapshot。[规范流序列](https://a2a-protocol.org/v1.0.1/specification/#117-streaming)支持该要求。
- 我方 ledger 初版将 sqlite3 事务上下文当成连接关闭，Windows 清理临时目录报 WinError32；改用 closing。拒绝检测也从任意 Exception 收紧为具体官方错误类，避免网络失败被当成权限拒绝。已完成取消预期纠正为实测 TaskNotCancelableError。
- 首次功能通过[grkqj3bw](a2a-mcp-20261005-grkqj3bw/result.json)，收紧检查的中间版[j16r970f](a2a-mcp-test-20261005-j16r970f/result.json)及最终 e8qqhg02 均保留。较早临时 unittest 的目录随测试清理，失败文本在工具调用记录；后续集成测试每次写独立 evidence 目录，不覆盖历史。

## SDK 生命周期问题：未修复

[sdk-diagnostics.log](a2a-mcp-test-20261005-e8qqhg02/sdk-diagnostics.log)保存两条 pending task 与 OpenTelemetry detach ContextVar 错误。已在 Starlette lifespan 使用官方 handler.aclose，并关闭 HTTP client、MCP session/stdio、SQLAlchemy engine；没有关日志或修改 site-packages。

定向观察：terminal replay 前 EventQueueSource dispatcher 为 0，拒绝后为 2。固定 1.2.1 的 [ActiveTask](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/agent_execution/active_task.py#L436) 构造两队列，[EventQueueSource](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/events/event_queue_v2.py#L65) 构造即启动 dispatcher。ActiveTask.start 检出终态的异常路径仅设 finished、安排清理；[registry remove](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/agent_execution/active_task_registry.py#L118)只 pop，未 close。**结合源码与 0→2 实测推断**，这是告警来源；没有声称完成上游缺陷修复或全场景证明。

需独立重现终态/不存在任务 start 失败与 client 关闭，验证官方修复或最小补丁后无残留 dispatcher/遥测错误，再测持续服务重复拒绝。当前只将 1.2.1 保留为有已知限制的研究基线。

## 测试与未覆盖范围

```powershell
.\research\.venv-protocols\Scripts\python.exe -m unittest research.probes.test_a2a_mcp_boundary_probe -v
# Ran 4 tests, OK；最终 e8qqhg02，37 功能断言
$env:PYTHONPATH='src'
.\research\.venv-framework\Scripts\python.exe -m unittest discover -s tests -v
# Ran 16 tests, OK；旧环境与 src 未变
```

逻辑预算单位不是美元/token；首次响应在获得任何 Task ID 前完全丢失、并发重复、服务中途崩溃、正式 OAuth/TLS、artifact ACL、只读 OS 强制边界、MCP 子进程沙箱、外部 job 回收、真实模型自主调查及真实 Coding/Config→QA 均未验。图没有持久 saver，待输入保存在内存；业务 ledger 对 running 重投只拒绝并要求对账，没有完整持久 Job 系统。不能把部分断流与已完成请求去重合称完整丢响应恢复验收。

只读抽查三份新主文档的协议/API及状态映射：一套 Card/两客户端、Author 先冻结完整 manifest 再确认、准入拒绝与已接收调查 INCONCLUSIVE、可信 principal、Task/业务 run/graph/job 分离均与本次审计一致。子只读权限、物理回收及跨服务故障仍明确列为待验；本探针不能清空产品故障矩阵。
