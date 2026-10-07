# 检索与 MCP：源码和小实验记录

日期：2026-10-04。旧项目只读；没有真实模型、embedding、NPC服务或MCP服务调用。此记录支撑方案取舍，不是产品验收。

## 源码事实

- 旧Coding用硬编码系统提示：[CodeContextBuilder](D:/Desktop/herta-agent-coding/backend/herta_agent/coding.py:31)。其[grep_code](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/grep_code.py:37)逐行执行 `query in line`，有限额、行号及截断信息，是字面搜索。
- 旧角色知识库另有[RemoteEmbeddings](D:/Desktop/herta-agent-coding/backend/herta_agent/rag/embeddings.py:118)与[exact cosine Retriever](D:/Desktop/herta-agent-coding/backend/herta_agent/rag/retriever.py:17)，查询向量与全体规范化向量点积，按阈值、重叠、k、字符预算选择片段；不是Coding的代码索引。README明确真实embedding与据证回答效果仍未验收。本次未使用它调用外部API。
- 旧Verification的[prompt加载和消息构造](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/provider.py:38)把Markdown正文放system，把动态JSON放user；[context](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:45)注入整个baseline、catalog、授权参数、当前候选摘要及最近16条观察；[read_evidence](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:46)先核验任务visible_refs再分页。这是结构化上下文与按引用读证据，不是向量检索。
- 对两处运行源码搜索 `SKILL.md / skills/list / load_skill` 未找到Skills装载机制；普通prompt文件不能据此叫Skills。旧角色embedding模块的Chunk也没有玩家/存档/NPC可见性字段，不能原样作为NPC记忆库。
- 现有旧工具通过Python注册/分派函数调用；未发现本项目游戏MCP server实现。本次会话可调用工具清单也没有combat/Unity/NPC工具。方案中的 `inspect_game_contract` 等是拟建工具，不能列作已经接通。

## 固定查询与探索结果

脚本：[词法实验](../probes/retrieval_probe.py)、[自动结构扩展](../probes/retrieval_structure_probe.py)；冻结的[6条查询与必要证据](../probes/retrieval_cases.json)。来源为35份真实Python/C#/JSON文件。输出保留源文件hash、脚本hash、查询hash、实际片段、行号和分数。

所有组最多8片段、6000字符，包含片段定位头。它是相同上下文字符上限，**不是精确相同DeepSeek token数**。基础分词包含完整符号、snake/camel拆词、中文bigram，不以裸unicode61失败充当弱对照。6题是人工挑选诊断集，gold不参与排名，未做训练/保留集划分。

| 组别 | 共享语料 | 必要证据宏平均召回 | 完整覆盖查询 |
|---|---:|---:|---:|
| BM25符号/中文bigram | 363窗口片段 | 61.11% | 2/6 |
| 同法+catalog中文名→ID | 363窗口片段 | 61.11% | 2/6 |
| 同法+catalog ID（结构分块对照） | 650共同片段 | 66.67% | 3/6 |
| 同法+自动JSON/AST关系 | 650共同片段 | 83.33% | 5/6 |

原始结果：[首轮](retrieval-probe-20261004.json)、[后续结构实验](retrieval-structure-probe-20261004.json)。后者看到首轮失败后才设计，属于**同题探索性跟进**，不能当独立保留集提升。共享650片段包含自然JSON对象、短AST分支/字段声明，对照组也使用它们，避免把分块收益全部归给关系。

关系自动来自“catalog名称/精确ID→JSON对象→实际字段→AST属性读取/类型比较分支/契约字段”；没有按题手填答案文件。两跳仅表示可能相关，尚不是完整调用图或已证实影响范围。边理由随结果保存。符号 `shield_expired` 能连接生产者、Trace契约和C#展示；结构扩展补到中文护盾配置及破盾规则。未登记“奶妈大招罩子”各组仍无结果，应澄清或用经维护别名，不能猜作已确认ID。

这些结果足以支持首版尝试小规模配置引用索引，暂不支持引入向量数据库或宣称Coding成功率提高。下一步应使用独立任务集评估必要证据召回、首个命中位置、版本正确率、冗余、实际token与延迟，以及真实DeepSeek任务完成率；索引更新/删除、旧版本不混入也必须测。

附加隔离fixture：故意注入其他玩家、存档、NPC、未来世界版本、隐藏事实5条高匹配干扰项，全部在评分前排除，评分器只收到1条可见事实。只验证示例函数，未覆盖生产鉴权、缓存、日志或数据库查询。SQLite3.45.1实测unicode61对连续句子中的二字“护盾”无命中，整句命中；trigram二字仍无命中、四字“护盾持续”命中。因此FTS5必须配置/验证中文分词，不能把unicode61或trigram默认当中文语义搜索。

## 三个业务如何用检索

RAG是“取可用证据→筛选/组装上下文→模型据证生成”的流程；BM25、向量相似度、SQL实体查询、引用图是可替换的检索方法。使用LangChain、MCP或某个tool都不自动构成有效RAG。本次无神经embedding，全部属于词法和结构关系检索。

| 业务 | 查什么、先过滤什么 | 如何进入本轮上下文 | 效果与边界 |
|---|---|---|---|
| Coding | 符号/定义/引用、中文配置名→ID、规则字段→Python结算→Trace契约→C#消费者→测试；按repo/worktree、commit+dirty hash、release/index版本、允许目录过滤 | 系统/开发指令只放工作方式；检索返回tool数据，携带路径、行号、hash、关系理由、截断/下一页；随后read_file核实再改。索引缺失回退rg/read，不悄悄混旧索引 | 必要证据召回、错误版本率、真实任务成功/回归、token/延迟；复杂关系再扩大，不能把读到代码当测试通过 |
| Verification | 首先精确查授权scope对应的参数、catalog归属、锁定配置、指标定义；结果出来后按candidate/report/seed/event ref查失败证据和机制 | 当前小配置直接有界结构化注入通常优于建RAG；增长后投影相关实体。每轮固定Spec/授权摘要+预算剩余+候选状态，工具只返回当前授权证据切片；报告数值由Evaluator提供 | 字段归属正确率、越scope建议/执行率、Spec遗漏、无依据数值、定位失败原因的证据命中、额外模型调用；历史相似实验只给建议，不能替代新候选模拟 |
| NPC | 已发布世界知识、该NPC亲历/被告知事件、关系与未完成承诺；服务端先绑定profile/save/npc/世界可见性版本及事实有效期，检索前过滤，缓存键含同scope | 常驻Persona/行为边界+当前可见世界投影+少量带event_id/来源/时间的经历，检索片段作数据；行动意图由程序核验，执行收据再更新经历 | 可见事实召回、未知时承认未知、跨存档/角色泄露=0、过期事实纠正、引文/记忆来源、行动合法率和真实延迟；研发聊天与验证报告不能直接当NPC经历 |

世界版本通常用于选择该版本的可见投影，历史经历可以在未失效且该NPC仍知情时检索；不是简单删除所有旧版本事件。上述fixture只使用精确版本快照，未实现这个生产投影逻辑。

Skills应只承载可复用做事方法：例如“修改战斗字段后定位契约消费者并运行哪些profile”；稳定边界在系统指令，动态事实在上下文，实际校验/计算/权限在工具代码。Verification/NPC不必为单一业务另造Skills插件加载器；将稳定流程、tool schema和版本化领域规则直接实现即可。三者默认一个推理Agent，多节点确定性流程不等于多个角色；Reviewer仅按任务风险或用户需求启用。

## MCP推荐边界

MCP host是管理模型与多个client的应用，client是host内连接某server的协议组件，server暴露tools/resources/prompts；领域服务拥有业务规则与状态。MCP不负责决定模型、RAG方法或是否多Agent。[官方架构](https://modelcontextprotocol.io/specification/2025-11-25/architecture)；当前官方默认文档已跳转2026-07-28，实施应按所锁SDK/Runtime实际支持版本配对，不能假定已装Codex支持最新版。

推荐 `Codex Runtime(host/client) → game-development MCP server → 领域服务/Broker/worker`。薄server负责协议、schema和可信身份传递；领域层再次做权限、预算、候选版本、幂等receipt。研发首批工具可为 `inspect_game_contract`、`search_game_evidence`、`simulate_candidate`、`run_game_tests`、`read_artifact` 及job查询/取消；输入是已授权任务/候选ID与白名单test profile，避免给任意shell、任意URL或任意本地文件路径。Verification同进程时直接调用同一领域API即可，不强迫绕MCP。

NPC首版也可用内部受限API；确有跨客户端复用再提供**独立NPC MCP server与独立principal**，仅 `get_visible_world`、`search_npc_memory`、`list_allowed_actions`、受控行动提交/收据查询。server在可信会话绑定scope，不信任模型传来的save_id/profile_id，不接受研发凭据；不给源码、模拟预算、构建、任意文件或发奖管理权限。奖励资格、world transaction、action idempotency仍归Game Host。

服务器必须验证输入及访问控制，客户端验证结果、超时和审计；这些不是tool名称或“只读”标注能保证的。[官方tools要求](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#security-considerations) MCP server和子进程也不会因为来自Codex工具调用就自动获得shell沙箱；Worker隔离/超时/取消必须单测。不同server的凭据与受众需分开，不能透传通用高权限token。[官方安全说明](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices#token-passthrough)

不需要为展示MCP先实现第二款游戏。先把当前游戏的不可变release、授权候选、标准job/receipt与artifact四类边界做窄；将来真实第二游戏适配时再验证复用，而不在首版抽象任意游戏规则或统一全部指标。
