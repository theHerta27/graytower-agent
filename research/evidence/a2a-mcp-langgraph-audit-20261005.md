# A2A / MCP / LangGraph 官方版本与边界审计

检索及本机核对日期：2026-10-05，Asia/Shanghai。本文区分官方事实、参考实现、项目决策建议与待验行为。没有模型调用、安装全局包或修改现有产品源码；后续隔离探针结果单独记录。

本轮后续实测见[协议探针记录](a2a-mcp-boundary-probe-20261005.md)：37 项功能断言及 4 项新增测试通过，但 SDK 1.2.1 终态拒绝路径有队列清理问题，生命周期不合格，生产 G0 不能通过。下文版本推荐是固定研究基线，上线须先解决该问题并回归，不能只凭功能 PASS 推广。

建议采用**一套 Verification A2A 服务与 Agent Card，Coding 和 Config 分别作为客户端；Verification 内部用 LangGraph，Agent 到工具使用 MCP**。Author 提交不可变 Candidate 的引用与验证目标，Verification 自主选择调查/验证步骤、产生证据与 PASS / FAIL / INCONCLUSIVE，不修改 Candidate。Config 与 Coding 之间不增设 A2A 链路；失败或证据不足由调用方 Author 决定是否修改后生成新候选。这是本轮已明确的产品边界，不是协议强制的角色划分。

## 1. 版本事实与明确推荐

| 层 | 2026-10-05 官方稳定版本 / 源码身份 | 推荐与限制 |
| --- | --- | --- |
| A2A 规范 | [v1.0.1](https://github.com/a2aproject/A2A/releases/tag/v1.0.1)，发布页 2026-05-28，变更条目日期 05-26，commit `3303592` | wire / AgentInterface 使用 `protocolVersion: "1.0"`；规范补丁号与 wire major.minor 分开 |
| 官方 Python A2A SDK | [a2a-sdk 1.2.1](https://github.com/a2aproject/a2a-python/releases/tag/v1.2.1)，2026-09-30，[commit 041c17bbe8d5ced7a8f6c48761152ce01ffbfc14](https://github.com/a2aproject/a2a-python/commit/041c17bbe8d5ced7a8f6c48761152ce01ffbfc14) | 新隔离环境锁 `a2a-sdk[http-server,sqlite]==1.2.1`；首个 binding 为 JSONRPC over HTTP，流为 SSE；不同时铺开三个 binding |
| 官方 Python MCP SDK | [mcp 2.3.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0)，2026-10-02，[commit 2118f14f8a19bc158d8a1cf90af58d85d187f849](https://github.com/modelcontextprotocol/python-sdk/commit/2118f14f8a19bc158d8a1cf90af58d85d187f849) | 新工具服务锁 `mcp==2.3.0`；本机研究用真实 stdio 子进程，部署共享服务再测 Streamable HTTP；不把旧 1.26 桥直接升级 |
| LangGraph | [langgraph 1.2.12](https://github.com/langchain-ai/langgraph/releases/tag/1.2.12)，2026-09-21，[commit 49cce0ca852be4cfb567a1cbe0e511ff325a1682](https://github.com/langchain-ai/langgraph/commit/49cce0ca852be4cfb567a1cbe0e511ff325a1682) | 保留已装 `langgraph==1.2.12`、checkpoint 4.2.0、sqlite 3.1.1；不用平台 SDK 的版本号冒充 graph 版本 |

A2A SDK 官方[兼容表](https://github.com/a2aproject/a2a-python/blob/v1.2.1/README.md#-compatibility)说明 1.0 和 0.3 compat 的 JSON-RPC、HTTP+JSON/REST、gRPC 均有 client/server 支持。三种 binding 是选择，不是三种验证能力。当前没有历史 A2A 客户端需要迁移，故新服务只声明和验证 1.0，暂不打开 0.3 兼容路由。HTTP+JSON 可在确有非 SDK 客户端需求时另测；gRPC 当前没有跨语言/吞吐证据驱动。

本机只读 metadata 检查：`research/.venv-framework` 为 Python 3.11.9；langgraph 1.2.12、langchain 1.4.3、langchain-core 1.6.6、langgraph-checkpoint 4.2.0、langgraph-checkpoint-sqlite 3.1.1、pydantic 2.13.5、httpx 0.28.1，未安装 a2a-sdk、mcp、starlette、uvicorn。根 pyproject 当前要求 Python `>=3.11,<3.13`。旧 MCP 窄桥的冻结 dependency-lock 明确是 mcp 1.26.0，不能把它报告为已通过 MCP 2。主控已另建 `research/.venv-protocols`，其最终安装清单与实测以探针记录为准。

[A2A pyproject](https://github.com/a2aproject/a2a-python/blob/v1.2.1/pyproject.toml)要求 Python>=3.10、httpx>=0.28.1、pydantic>=2.11.3、protobuf>=5.29.5；[MCP pyproject](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/pyproject.toml)要求 Python>=3.10、pydantic>=2.12、httpx2>=2.10.0，以及 Windows pywin32>=311。现有 Python/Pydantic 满足这些下界，**只是静态依赖兼容判断**；实际共装、事件循环、清理和协议仍需探针。httpx 与 httpx2 可共存，但其 client/auth/exception 对象不能混传。

## 2. A2A 协议事实与本项目映射

### 2.1 卡、绑定及消息格式

官方发现路径是 `/.well-known/agent-card.json`。本项目发布一个 Verification Card，含一个 `verify_candidate` skill、受支持输入/输出 media type、认证声明和 `supportedInterfaces` 中的 URL / `JSONRPC` / `1.0`。卡的 `version` 是服务自身版本；卡不携带仓库、凭据、模型上下文或对候选的写权限。固定配置卡 URL 足以服务这两个已知客户端，无需先建注册中心。[Agent Discovery](https://a2a-protocol.org/v1.0.1/topics/agent-discovery/)

1.0 的 JSON-RPC 方法使用 `SendMessage`、`SendStreamingMessage`、`GetTask`、`ListTasks`、`CancelTask`、`SubscribeToTask`；不混用 0.3 示例的 `message/send`、`tasks/resubscribe`。传输请求 ID、`messageId`、服务生成的 Task ID、`contextId` 各有不同作用。1.0 使用 ProtoJSON、`ROLE_USER` / `TASK_STATE_*` 枚举及 `task` / `message` / `statusUpdate` / `artifactUpdate` 包装，旧 `kind` 不能照搬。[固定规范 v1.0.1](https://a2a-protocol.org/v1.0.1/specification/)

SDK 类型已从 Pydantic 转成 Protobuf：`Part(text=...)`、`Part(url=...)`、`Part(data=ParseDict(value, Value()))`；模型序列化不再用旧 `.model_dump()`。服务使用 `create_agent_card_routes` 和 `create_jsonrpc_routes` 组合到 Starlette/FastAPI；client 可用 `await create_client(card_or_url)`。旧 A2AStarletteApplication 等 wrapper 已移除。FastAPI 直接挂 Starlette routes 不自动进 OpenAPI，要显示才使用专用 helper。[官方 v0.3→v1.0 迁移指南](https://github.com/a2aproject/a2a-python/blob/v1.2.1/docs/migrations/v1_0/README.md)

### 2.2 Task 生命周期与业务结论分开

简单交互可只回 Message；需追踪的验证应创建 Task。`contextId` 可关联多个任务；补充当前任务输入使用该任务身份，终态后的修订产生新 Task，可引用旧任务。一个 terminal Task 不应被重新打开。[Life of a Task](https://a2a-protocol.org/v1.0.1/topics/life-of-a-task/)

本项目决策映射如下，不能用协议状态替代结果契约：

| 协议状态 | Verification 含义与业务处理 |
| --- | --- |
| SUBMITTED / WORKING | 已接收 / 正在调查；没有最终 verdict |
| INPUT_REQUIRED | 缺少目标、候选引用或授权说明；保持候选不变，由客户端提交受校验的补充输入 |
| AUTH_REQUIRED | 需要额外认证；通过可信认证通道补齐，不能把聊天中声称“已授权”当凭证 |
| COMPLETED | 验证服务成功交付报告；报告可以是 PASS、FAIL 或 INCONCLUSIVE |
| FAILED | 验证执行本身异常，未成功交付；保存故障和已有证据；不可翻译成“候选业务失败” |
| REJECTED | 服务拒绝执行，例如不支持的范围；不等于已验证候选有缺陷 |
| CANCELED | 协议任务取消；外部已启动 job/进程/扣费是否停止或已完成，另按领域收据对账 |

INCONCLUSIVE 适用于服务正常完成调查但证据不足、覆盖不足或预算内无法判定；FAILED 适用于工作没有正常完成。候选的 FAIL 是有依据的验证结论，也可以是 COMPLETED 的正常产物。

### 2.3 追加输入、获取、流与取消

`GetTask` 用于状态/产物对账，historyLength 可限量。`CancelTask` 是尽力取消，可能返回不可取消；`SubscribeToTask` 对活动任务重订阅，首事件须为当前 Task，终态应改用 Get。协议并未给本项目一个“丢掉任意流片段仍恰好重放所有日志”的承诺。[规范操作定义](https://a2a-protocol.org/v1.0.1/specification/#31-core-operations)

SSE 的 artifact 分块带 append/lastChunk 等重组语义。断线后可重订阅；UI 的流是观察路径，最终结果从 Task 与不可变证据读回。断线不作为重新开始一次验证的依据。不同 interrupted 状态的流关闭行为不能混为一谈；尤其 AUTH_REQUIRED 有带外凭据续行的情况，需按 SDK 实际表现测试。[Streaming and Async](https://a2a-protocol.org/v1.0.1/topics/streaming-and-async/)、[认证定义](https://a2a-protocol.org/v1.0.1/specification/#7-authentication-and-authorization)

**项目决策：** Author 先持久化 verification_request_id 与规范化 payload hash，再发送。未知接收/超时先查该业务请求的 receipt；重发保留业务 ID，禁止换 ID 偷跑预算。重复 A2A message 可能产生不同协议 Task，业务执行只能由自己的 ledger 去重并关联原 report；不为了强行重用 Task ID 私造传输协议。新增 candidate revision 是新验证请求，继续引用同一总授权预算，不能借新 Task / context / LangGraph thread 归零。

### 2.4 必须分别保存的身份

| 身份 | 产生者 / 用途 | 不能等同于 |
| --- | --- | --- |
| JSON-RPC id | client，单次请求响应关联 | 去重键、预算授权 |
| messageId | 消息创建方，通信 turn 身份 | 恰好一次业务执行保证 |
| A2A taskId / contextId | 服务任务 / 会话关联 | git revision、可信用户身份 |
| candidate_id + manifest/hash/revision | Author 冻结的内容身份 | 任意本机 path、可变工作树 |
| verification_request_id / verification_run_id | 可信业务入口 / 独立验证执行 | A2A taskId、LangGraph内部 task_id |
| workflow/thread_id + graph_version | 服务内部编排与恢复 | 所有权、外部 job 完成事实 |
| operation_id / job_id / receipt_id | 工具执行和领域账本 | MCP JSON-RPC id、流事件序号 |
| artifactId + evidence content hash | A2A产物身份与内容核验 | 文件名、可改写 latest URL |

Artifact 是任务输出；文件内容可内联或提供引用，A2A 不替服务克隆仓库、装依赖、授权访问路径或定义文件系统一致性。本项目传标准 Part 中的领域 JSON：候选内容地址、hash、base revision、允许验证范围与目标；下载/解析由受限 artifact 服务处理。输出固定 report schema，绑定 candidate/hash、验证环境/工具/图版本、证据索引和 verdict。报告引用不能因为字符串里有“hash”就被当成已校验。

## 3. 官方参考实现能复用什么

优先复用官方 SDK 的 executor / updater / request-handler / routes / task-store，而非重写一套貌似 A2A 的 HTTP API。可固定到 v1.2.1 的 [samples/hello_world_agent.py](https://github.com/a2aproject/a2a-python/blob/v1.2.1/samples/hello_world_agent.py) 展示 Task 首事件、TaskUpdater、流、取消与三绑定接线；该示例使用 InMemoryTaskStore，并非生产持久验证服务。

重要源码事实：[request_handlers/__init__.py](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/request_handlers/__init__.py) 把 DefaultRequestHandler 指向 DefaultRequestHandlerV2。旧文件内的实现名为 LegacyRequestHandler，不能仅凭旧文件名判断当前默认行为。[V2 handler](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/request_handlers/default_request_handler_v2.py) 使用 ActiveTaskRegistry，接受旧 queue_manager 参数却不使用；有 aclose 清理和 versioned store / event-stream 接口。配置数据库保存 Task，不会自动复活外部作业或图 driver，也不自动构成完整分布式恢复方案。

[InMemoryTaskStore](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/tasks/inmemory_task_store.py) 已按 owner_resolver 划分存储，但进程退出即丢状态。SDK SQLite extra 提供数据库后端依赖；本轮优先验证真实 SQLite store 是否可用，不能仅见 extras 就声称已持久恢复。

官方 [LangGraph sample](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/langgraph) 是框架接线参考；README 明确为演示用途，外部 card/message/artifact/status 应视为不可信输入。此次读取 main（2026-10-05），未锁该仓库 commit，因此不用它作为固定可复现底座，也不运行其中模型配置。SDK tag 内固定示例和源码更适合本轮零模型协议探针。

认证事实：A2A 采用既有 HTTP/TLS/认证方案；卡声明不执行认证，应用仍需身份和授权。任务获取/取消/列表、artifact读取都应按**经认证调用身份**校验；body 中的 author、role、contextId、tenant 不可自证权限。带外凭据流不等于要求 Author 把自己的 provider/tool 密钥交给 Verification。[Enterprise Features](https://a2a-protocol.org/v1.0.1/topics/enterprise-ready/)

## 4. MCP 2 的能力和迁移边界

官方 SDK2 暴露 `MCPServer`、`Client`，支持工具、资源、prompt 与 stdio / Streamable HTTP；已有 `ClientSession` 低层入口可按需要保留。纯本机单宿主管理的服务先选 stdio；共享部署再选 Streamable HTTP，不能把 A2A SSE endpoint 与 MCP endpoint 合并为同一种会话。[SDK README](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/README.md)、[Client transports](https://py.sdk.modelcontextprotocol.io/client/transports/)

SDK2 默认 `Client(mode="auto")` 先探测 server/discover；现代连接为 2026-07-28，旧服务可回落到 initialize。`mode="legacy"` 使用旧握手；固定现代版本会跳过发现，不能仅打印该本地值证明服务兼容。探针保留发现结果、实际协议和调用证据。[Protocol versions](https://py.sdk.modelcontextprotocol.io/protocol-versions/)

迁移注意：FastMCP→MCPServer；Python属性改 snake_case（input_schema / is_error / structured_content），wire仍用别名；httpx2不能混入httpx对象。SDK2移除了原 experimental Tasks runtime；2026 Tasks扩展尚未实现，因此不采用它承接验证工作流或Unity作业。短工具用call_tool，长作业将来使用领域job提交/查询/取消和receipt；两者都不替代A2A Task。[官方迁移说明](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/migration.md)

**项目决策：** Verification 的工具集合只读 Candidate，允许在独立证据区写验证产物；Config/Coding各自工具边界可有受限修改权。MCP协议不提供OS沙箱、进程树回收、模型凭据隔离、业务预算或恰好一次副作用。工具参数必须把可信授权上下文与模型提议分开。A2A caller token不直接透传给任意MCP目标。

旧窄桥 [runtime-deepseek-assessment.md](runtime-deepseek-assessment.md) 和其 dependency-lock 为 mcp1.26.0 的 SDK dynamicTools→MCP fixture证据；可以复用设计/映射经验，不能宣称MCP2、真实引擎、远程OAuth或所有Runtime工具已验。

## 5. LangGraph 已装能力及可复用证据

本机 inspect 已确认 1.2.12 有 `interrupt(value, response_schema=...)`、StateGraph.add_node 的 retry_policy/timeout/error_handler/trace_policy、Pregel.astream 的 durability/control，以及stream_events。依赖元数据要求langchain-core>=1.4.7,<2、checkpoint>=4.1,<5，与已装1.6.6/4.2.0吻合。API存在不等于本项目相应行为已测试。

当前官方区分 checkpointer 的thread状态与store的跨thread信息；内存saver不跨重启，SQLite面向本地使用。interrupt恢复会重新进入节点，副作用仍须可重入；schema约束只管输入形状，不代表业务授权。timeout仅适用于async节点，RunControl/drain不能替代强制终止外部Worker。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)

仓库已有 [恢复语义审查](../langgraph-recovery-review-20261004.md)、[离线探针记录](langgraph-probe-run-notes.md) 和 [锁版本](../probes/framework-requirements.lock.txt)。先复用这些证据：跨进程退出/恢复、checkpoint前副作用、ToolNode必须在图内得到Runtime等；不重跑模型。此前Verification图含候选生成/修订的旧职责必须按本轮Author/Verifier分离修订：Verification的图只处理接收/澄清/计划/工具调查/对账/证据/结论，不持有修改Candidate的节点。

**项目决策：** A2A executor是协议适配，LangGraph是Verification内部agent编排；前者Task身份与后者thread映射持久化。一个thread单driver；预算、approval、job与receipt继续是领域账本。协议TaskStore和graph saver即使都是SQLite，也不是自然共同事务。成熟框架能减少通用生命周期/编排代码，不能删除这些业务约束。

## 6. 本阶段探针与之后验收

主控已确认隔离研究probe：一个官方AgentCard/skill，两个固定测试身份的Config/Coding客户端；真实loopback HTTP JSONRPC＋官方SDK；真实MCP2 stdio子进程的query_schema/validate/read_artifact；LangGraph使用固定fixture决策，零LLM。只访问临时小JSON候选与证据，不向远端传仓库。

| 现在测 | 应保存的不变量 / 失败证据 |
| --- | --- |
| 卡和绑定 | 两客户端取得同一张卡、同一skill；wire为1.0真实方法与ProtoJSON，不私造REST冒充A2A |
| 结果语义 | COMPLETED分别承载PASS/FAIL/INCONCLUSIVE；客户端读取结构报告判业务，不凭状态判PASS |
| 身份 | body author伪造不改变owner；另一身份Get/续输入/取消无权任务不能成功；本地测试凭据不称生产OAuth |
| 候选引用 | 请求传candidate ref+hash；MCP读取指定临时文件并核验；hash不符不继续验证；前后候选hash一致 |
| 重试/幂等 | 新messageId/可能新Task重发同业务ID同payload不重复业务执行；同ID异payload拒绝；业务ledger与协议store分开记 |
| 追加输入 | INPUT_REQUIRED同Task补齐、错误context拒绝、terminal再输入拒绝；不借补输入替换候选 |
| 流和恢复观察 | 首Task、artifact、终态；断流后Get能读最终产物；活动task重订阅观察及SDK限制如实记，不声称事件全重放 |
| 取消 | CancelTask返回与终态；执行器退出/工具清理证据另记；已完成不可取消按协议处理 |
| 存储 | 优先官方SQLite store再实例化读回；这只证明Task持久化，不是运行中任务/Worker自动恢复 |
| MCP边界 | 真list_tools/call_tool、独立请求ID、schema/参数错误、不可调用未注册写工具；不依赖已移除Tasks runtime |

后续正式门槛另测真实DeepSeek规划/调查质量、真实游戏与Unity候选沙箱、artifact ACL/下载权限、跨进程中途崩溃/丢响应/取消竞态、总预算跨revision、真实身份认证、版本升级和工具schema变化。协议fixture通过不能替代它们。

本次调研限制：官方latest页面可能变化，关键推荐固定tag；部分未固定样例只作参考。终端普通网络只读请求受到沙箱socket限制，本次网页/source查证通过浏览工具完成；没有绕过限制。关于SQLite store、HTTP断连与MCP子进程的实际兼容性，必须以随后独立probe结果为准，不在本文预宣称通过。
