# LangGraph / LangChain 恢复语义与职责审查

审查日期：2026-10-04。范围：读取本项目 `TECHNICAL_PROPOSAL.md`、`IMPLEMENTATION_ROADMAP.md`，查询 LangChain 官方文档，给出设计与故障验收建议。本报告未安装依赖、运行框架探针、调用真实模型或修改主方案。以下“框架事实”来自文档；“本项目设计”是审查建议，尚非已实现、已通过的保证。

## 1. 建议与需要更新的地方

建议按新方向拆分：Verification 使用 LangGraph 的显式图承接现有 Agent 编排；NPC 使用 LangGraph 编排，LangChain 负责模型、消息、工具声明和结构化输出；Coding 保持 Codex Runtime + App Server + Python SDK，不包进新的模型/工具循环。

本次读取时主方案 D03、架构图和路线 M3 仍以手写领域状态机为主，应改为上述职责。原有授权、预算、Evaluator、Game Host 世界事务、Worker 收据、NPC inbox/outbox 都应保留。这些是领域正确性的实现，不是采用框架后应删除的重复编排。LangGraph 接管“下一步、分支、暂停、恢复、节点重试”；领域服务继续决定“是否允许、是否已做、还能花多少、什么结果是真的”。

需要删除或避免四类过强表述：checkpoint 保证工具只执行一次；sync 能把世界提交与图提交变成同一事务；resume 天然幂等；有 thread_id 即可安全并发运行同一流程。推荐明确承诺为：**允许节点或请求重跑，通过持久业务 ID、唯一键、收据查询、事务条件和单一图驱动，使重复尝试不重复提交领域结果。**

## 2. 框架事实及其边界

| 主题 | 已核实语义 | 对本项目的约束 |
|---|---|---|
| checkpoint / superstep | 图在 superstep 边界保存完整状态；同一步可能有并行节点。成功节点的 pending writes 可在同一步其他节点失败时被复用。 | 完整 checkpoint 与节点写入不是同一种记录；“图 checkpoint 未更新”不必然表示所有兄弟节点都重跑。须分别测节点异常与进程硬崩溃。 |
| durability | `sync` 在下一步前完成检查点持久化；`async` 与下一步重叠；`exit` 只在正常、错误或 interrupt 退出时保存。 | 首版重要流程选 sync。async 有崩溃窗口；exit 不适合长实验的中途崩溃恢复。三者都不与外部服务事务自动原子提交。 |
| 标识 | `thread_id` 定位线程；`checkpoint_id` 定位具体快照；`checkpoint_ns` 区分图/子图。 | 都不能直接替代世界 command_id、实验 operation_id 或玩家存档授权。 |

上述 checkpoint 机制依据 [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)。其中减少重跑的条件是相关结果已经持久化；不能把“成功返回前发生过外部副作用”推断成“已持久 task result”。

`interrupt()` 暂停后，恢复会从所在节点开头重跑。中断之前的代码要可重入；避免吞掉其控制异常，保持节点内 interrupt 顺序稳定，使用可序列化 payload。多个并行 interrupt 可用 ID 到回答的映射恢复。把副作用挪到审批之后可以解决审批前重跑问题，但不能消除“副作用完成、节点结果尚未落盘”的崩溃窗口。[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

Functional API 从 entrypoint 开头重放，复用已保存的 task/subgraph 结果；未完成 task 可再次执行。非确定性值和副作用应放进 task，并仍设计幂等。Graph API 首版宜用独立节点划清边界，必要时在节点内使用 task；不要把整个旧 while-loop 塞进一个节点后宣称已具备细粒度恢复。[Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)

`RetryPolicy.max_attempts` 包括首次执行，重试重新运行失败节点；应明确 `retry_on`、上限、退避和 jitter，不能假定默认策略等同业务需要。当前文档的节点 timeout、RunControl 等能力带 `langgraph>=1.2` 版本门；timeout 仅支持异步节点。drain 在 superstep 间协作退出，不杀线程，也不取消正在运行的 asyncio task。[Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)

节点更新通过 reducer 合入状态；没有 reducer 的字段默认替换。`update_state`、旧 checkpoint 回放不是“撤销外部世界”。中断中的图不能随意删除/改名它即将进入的节点，状态键改名或不兼容类型变化亦有风险。[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)

本项目不应直接复制当前最新示例中的 `stream_events(version="v3")`、`response_schema` 或新 timeout API 而未核对安装版本。锁文件至少分别固定 `langgraph`、`langgraph-checkpoint`、SQLite checkpointer、`langchain`、`langchain-core`、provider 集成、Pydantic 与 Python；保留 wheel/lock hash。文档更新日期不等于本机 wheel 能力证明。

## 3. Checkpointer、线程与版本方案

以下是本项目设计建议：

- 首版使用文件型 SQLite checkpointer，异步调用对应异步实现；`InMemorySaver` 仅用于小测试，不能证明跨进程恢复。官方将 SQLite 定位于本地流程/实验，首版单机适用性仍需实际并发、崩溃和数据库生命周期测试。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- `Verification thread_id` 从业务数据库中的 workflow_instance 读取，绑定 task_id、revision、graph_version；新 revision 创建新 workflow，同时引用旧证据和同一授权预算账本，不能借新 thread 重置额度。NPC 的 thread 映射绑定 profile/save/npc/conversation，世界 command 另有独立身份。用户输入不能任意选别人的 thread。
- 图状态只放可序列化业务引用、冻结版本和小型派生数据，不放数据库连接、密钥或唯一权威预算。长记忆和世界事实有各自持久存储；conversation checkpoint 不天然提供知情过滤。
- workflow_instance 固定 graph_version、state_schema_version、release_lock、模型/工具/提示版本。旧流程继续旧图，或经过有输入/输出夹具的显式迁移；不靠“字段还能反序列化”证明业务含义兼容。checkpointer 格式版本、channel version 与本项目 graph/release 版本应分别记录。
- 首版只有一个 Supervisor 驱动图；同一 thread 的 start/resume/input 串行化，入口请求先持久化。接管必须确认旧 graph driver 已退出。SQLite 文件锁并不等于完整流程串行锁。
- 若未来允许租约到期自动接管，必须同时解决旧 driver 的 checkpoint 写入。领域 fence 只阻止领域提交，不会自动约束 checkpointer；仅在 state 中放一个 epoch 也不是持久存储写入时的 fencing。未做这一层前禁止两个 driver 同时驱动同一 thread。Worker 可并行，但最终结果提交须有 fence/CAS。

即使业务账本和 checkpointer 使用同一 SQLite 文件，分别调用业务事务与 saver API 也不会自动形成共同事务。首版明确采用两套提交和对账，不假装获得跨资源 exactly-once。图进度是可修复的投影，权限/扣账/世界事实以领域账本为准。

## 4. 业务身份必须先于副作用持久化

以下标识应由可信服务生成和校验，不能让模型自由填写，也不依赖运行中临时生成、稍后才进入 checkpoint 的 UUID。

| 记录 | 唯一约束 / 绑定内容 | 创建位置 |
|---|---|---|
| inbound_request | `(scope_id, client_request_id)`；规范化输入 hash 不同则冲突 | API 入口事务，先落盘再触发图 |
| workflow_instance | task revision 或 NPC 对话实例；固定 graph/release 版本 | 接受请求的领域事务，保存 thread 映射 |
| operation | `(workflow_instance_id, logical_step_key)`；保存 operation_id、payload_hash、授权、seed/baseline/候选 hash | 执行副作用前通过数据库 get-or-create；冲突时读取已存在记录，禁止换 ID 重试 |
| budget_reservation | operation_id 唯一；预算类型、预留额、结算状态 | 与 operation、dispatch_outbox 在同一事务内创建 |
| approval | approval_id 唯一；绑定 workflow、revision、proposal hash、审批人和决策 | 审批 API 原子 pending→decided，与 resume_outbox 同事务 |
| world_receipt | `(save_id, command_id)`；另存 immutable payload hash、前后 revision、事件 | Game Host 改世界的同一事务 |
| one_time_reward | `(save_id, quest_instance_id, reward_key)` | 与奖励发放同事务，防两个不同 command_id 领取同一奖励 |
| NPC event inbox | `(save_id, event_id)` | NPC 消费事件与写入经历同一事务 |

`logical_step_key` 应来自已冻结的计划/候选槽/实验规格，例如 `candidate-slot-2/exploration/seed-manifest-hash`；不能使用“本次 retry 次数”生成新 operation。payload hash 用来检测同 key 不同内容，而不是把不同内容的 hash 加进唯一键后悄悄创建第二个 operation。模型重算后提出不同候选，必须走新的候选槽、预算与授权路径。

若计划本身还未 checkpoint，也先把模型提议以稳定 decision_slot 持久化为不可变 proposal；恢复先加载该 proposal。不能在 checkpoint 丢失后重新问模型生成不同内容、沿用已授权槽位执行。`attempt_id` 可以每次重试变化，仅用于诊断；业务 operation_id 不变。

计费需要分开：同一业务 operation 的实验额度只预留/结算一次；若实际发生重复计算或重复模型请求，真实 CPU/token 成本仍需按 attempt 记账，不能声称没有发生。纯模拟可以允许重算后只发布一个结果，但物理运行次数必须保留在证据中。

## 5. 三个必须通过的恢复场景

### 5.1 实验完成，但图 checkpoint 尚未更新

正确路径是 `reserve → dispatch → reconcile_receipt → evaluate`。reserve 在一个领域事务中创建 operation、预算 reservation 和 outbox。dispatcher 重发相同 operation_id，Worker inbox/执行器识别重复；Worker 完成后发布内容寻址产物，并原子提交 receipt。receipt 绑定输入、seed、基线、候选、运行版本和产物 hash。

恢复执行节点时先用领域表取回 operation_id，再查询 receipt：已完成且 hash 匹配，直接重建 observation；仍运行，进入等待/查询；不存在，依据 outbox 重投同 ID；状态未知，进入 reconciliation，不能换新 ID“再跑一次”，也不能退还预算。只有确认旧运行退出或接收端能拒绝旧 fence，才可明确重试。自动重试失败或无法确认的 profile 需要人工处置。

故障注入位置必须包含：① reservation 已提交、checkpoint 未提交；② dispatch 后进程退出；③ receipt 已提交、RPC 响应未送达；④节点收到 receipt、return/checkpoint 前退出。分别使用新 Python 进程读取同一数据库恢复。断言 operation/reservation/已发布 receipt 各一条，预算不增加，证据 hash 一致；记录物理 attempt 次数，避免把结果只发布一次冒充只执行一次。

产物文件与数据库也不是共同事务：先写临时文件、校验并原子发布不可变内容，再提交引用其 hash 的 receipt；留下的孤儿文件可回收。禁止写出“成功 receipt”后才写产物。恢复读 receipt 仍应验证文件存在和 hash。

### 5.2 重复 resume、审批已接受但响应丢失

审批不是任意 `Command(resume=True)`。UI 提交 approval_id、decision、proposal hash 和 client_request_id；服务确认当前 pending approval、身份与 revision，原子记录第一次合法决策，重复同决策返回原收据，冲突决策拒绝。

同事务写 resume_outbox 后，由该 thread 唯一 driver 读取当前图状态及 pending interrupt；只有它与 approval_id、proposal hash 对应时才发送带 interrupt ID 的 resume。节点在恢复后验证并读取权威 approval 记录，不能把 resume payload 本身当授权凭证。

如果“图已处理 resume、outbox 尚未标记送达”就崩溃，恢复先查看图当前阶段和领域 operation：仍在原审批处则投递同批准记录；已前进则对账并完成 outbox；现在是另一审批则旧回答不能传给它。未知状态保持 pending reconciliation。框架调用和 outbox 状态之间仍有提交间隙，最终写动作必须用第 4 节幂等约束兜住。

建议一个审批节点只含一个固定 interrupt，审批意图在前一节点幂等持久化；不要在节点内随机选择不同 interrupt 顺序，也不要通过“已有 approval 所以跳过前几个 interrupt”修补流程。代码升级必须保持旧图中断含义。

故障注入：双击审批、两个并发客户端、resume 响应丢失、批准落盘后 driver 重启、恢复后出现下一条审批再收到旧批准。断言一个 approval decision、一次业务预算/世界提交，旧批准不能匹配新提议；不能只断言最终输出相同。

### 5.3 NPC 世界 commit 成功但响应丢失

在玩家确认的 intent 持久化事务中生成 command_id，绑定 save_id、NPC、预编写 action/参数 hash、expected_revision 和授权。LangGraph 节点只取用该记录。Game Host 在单个事务中完成：查现有 receipt、校验新命令的权限/条件/revision/fence、改变世界、写 receipt、写 outbox。

重发同 command_id 时先比对已有 receipt 的 payload hash；匹配就返回原提交结果，即使当前世界 revision 已前进也不能错误认定旧命令尚未发生。只有不存在 receipt 的新执行才按 expected_revision 等条件继续；同 ID 不同内容必须拒绝。跨存档分支使用新的 save_id，不能把旧响应落到新世界。

RPC 超时表示提交状态未知。NPC 恢复先查 receipt；无收据时在接收端允许的条件下重发相同 ID；无法确认时显示处理中，不让模型写“已发奖”。Game Host 的 reward 唯一键再防不同 command_id 重复发同一奖励。

世界 outbox 与世界状态同事务，NPC inbox 去重与经历写入同事务；消费失败可重投，乱序事件按世界版本对账。世界成功但经历尚未同步是允许的暂态；对话下一轮先补齐相关事件或说明结果尚在同步。图 checkpoint 仅记 receipt/event 引用，取消不删除已经提交的世界事实。

故障注入：世界事务前退出、世界提交后丢响应、NPC 经历写入前退出、经历写入后 ack 丢失、重复/乱序 outbox、旧分支迟到、两个不同 command_id 争抢同一奖励。断言一个世界效果、一个奖励、一个经历事件，图最终能从收据修复；同一奖励不能因重跑模型重新分配 ID 而再次获得。

### 5.4 Fence 与取消的实际含义

fence 是接收端在最终提交事务中与当前 owner_epoch 比较并拒绝旧 owner 的条件。只在日志/请求头放 fence 不起作用。Worker 更新 result/status、预算结算、Game Host 新写命令都要经过适用的原子检查；已存在 receipt 的只读查询可以返回原事实。fence 不会停止旧进程占 CPU，也不会撤销它已提交的操作。

图中断、超时、客户端断连与 Worker 已退出分别记录。取消先持久化 cancel_requested，禁止后续未开始的写动作；在途作业等退出/收据确认。旧任务若已获准提交且完成，按事实展示。Windows 进程树回收仍由现有 Broker 验证，LangGraph 不替它提供执行沙箱或强制终止保证。

## 6. RetryPolicy 和模型调用的分工

本项目建议按节点列出异常矩阵：读取与模型网络故障可有限重试；业务越权、过期 revision、余额不足、候选不合法通过明确边进入拒绝/澄清/修订，不靠泛化 retry。写调用的 timeout/断连先查收据，不以新业务 ID 重试。格式错误可以有受预算约束的修复分支，保留原输出和错误。

LangChain provider 自身重试、LangGraph 节点重试、Agent 格式修复循环的上限需要合并计算。三个层次各自“最多 3 次”不能被报告为最多 3 次请求。`recursion_limit` 只是图执行步数上界，不是 token、实验次数、CPU 或跨 resume 的授权额度。预算仍由独立持久账本决定。

## 7. LangChain 在 NPC 中具体负责什么

直接模型节点可用 `with_structured_output(NpcProposal)` 返回 Pydantic 提议。`json_schema`、`function_calling`、`json_mode` 支持取决于 provider；Pydantic 可做运行时字段校验，TypedDict/裸 schema 不应被当成本地等价校验。`bind_tools` 返回工具调用请求，独立使用模型时仍需执行器执行并返回对应 tool_call_id 的结果。[Models](https://docs.langchain.com/oss/python/langchain/models)

`create_agent(response_format=...)` 是另一套高层入口，会选择 ProviderStrategy/ToolStrategy，结果放 structured_response；如果同时使用工具和结构输出，provider 必须支持该组合。它不能与直接模型的 `with_structured_output` 混为一个 API。首版自定义 StateGraph 不必为了使用 LangChain 再嵌一个无限制通用 Agent 循环。[Structured output](https://docs.langchain.com/oss/python/langchain/structured-output)

工具声明、args_schema、ToolMessage、ToolRuntime 可复用。可信上下文如 save_id、角色可见范围来自服务端 runtime/context；不要让模型任意指定范围。工具返回的 Command 能更新图状态，不能因此当成授权世界事务。[Tools](https://docs.langchain.com/oss/python/langchain/tools)

本项目推荐 `NpcProposal` 包含对话草稿、来源引用、action enum 和预编写 action_id；明确禁止任意奖励数值。LangChain 负责模型/消息/格式，领域 validator 负责知情范围、剧情条件、玩家确认、一次性资格、版本和库存。合法 JSON 也可能是越权行动。只读检索工具可用 ToolNode；世界写命令走专用校验/commit/reconcile 节点，不能把带写权限的函数直接交给模型自动循环。

首轮 provider 契约需验证结构输出模式、工具参数、并行 tool calls、流片段合并、usage、超时/取消和错误形态；记录实际适配包和模型 ID。离线 fake model 能证明图和解析路径，不能证明 DeepSeek/其他真实模型支持某个组合或达到延迟与质量目标。

## 8. 建议的两张真实业务图

Verification：`ingress/reconcile → understand → clarify 或 freeze_spec → approval → choose_next → reserve_operation → dispatch → reconcile_receipt → evaluate → revise/inspect/reviewer/finalize`。choose_next 可由模型提议，但条件边只接受有限合法行动；Evaluator、授权、候选槽、种子清单与预算由程序校验。并行 seed 分片只有在业务 ID、收据与 reducer 去重都测通后开放。

NPC：`ingress/reconcile → visible_world → retrieve_memory → model_proposal → validate → player_confirm → commit_or_query_receipt → reconcile_memory → render_response`，无行动提议可跳过 commit；拒绝与离线模型走明确降级边。身份、版本和副作用边界始终由领域层掌握。

框架学习应交付下列可审查产物，才足以证明理解：

1. 两张从真实编译图导出的图，加每个 state key 的权威来源、reducer、持久性和版本说明；不是手画节点却仍调用一个旧大循环。
2. 新进程恢复的故障测试、数据库记录与事件时间线：标出 superstep/checkpoint、task pending writes、business operation/receipt、approval、attempt/fence，能解释哪些代码重跑以及为什么没有重复领域提交。
3. 一个并行节点成功、另一个失败的 pending-writes 测试；一个外部提交成功而 task/checkpoint 尚未落盘的反例测试。后者证明不能依赖框架缓存保证 exactly-once。
4. sync/async 持久化时序夹具和崩溃测试。通过控制 saver 的写入屏障观察顺序；真实文件库另测重启。测试结果只覆盖所锁版本、SQLite设置及进程崩溃，不能扩写成断电可靠性证明。
5. 重复 resume、冲突决策、图版本变化、跨存档读取、旧 fence 提交和模型格式失败测试；每个测试写业务不变量，不能只断言 graph.invoke 返回成功。
6. LangChain 模型/工具契约测试：Pydantic 不合法、结构合法但业务非法、tool_call_id 匹配、工具观察回传、来源过滤、离线降级；后续单独附真实 provider smoke 与成本/延迟记录。
7. 迁移对照：相同旧 Verification 任务集的 verdict、预算和证据保持，真实 Agent 分支仍可追踪；只替换编排，不改评分器去掩盖回归。NPC 则给出营地—战斗—返回和丢响应恢复的玩家闭环。

这些交付比“用了 LangGraph/LangChain”更有面试价值：能够展示框架具体省掉哪部分运行控制，以及哪些业务一致性问题必须由应用解决。本报告提供实验设计，不代表上述实验已执行；结果由主控框架探针和后续实现另行记录。
