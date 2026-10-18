# 项目群协作约定

- 2026-10-18用户确认的新主线优先于下方历史四能力/强制A2A等约束：求职项目围绕自研游戏环境中AI修改的可靠交付，先做能力完整的单Agent与可信执行工具、回归验证和人工采用；NPC停止后续主线开发但保留旧成果。多Agent不是必选架构，独立验证Agent先做实际对照，有可重复业务质量收益再决定进入产品；A2A不作为新默认运行链路依赖。Coding继续复用Runtime/官方SDK，不叠加重复的主循环。项目说明.md给出当前讨论方案和目标简历，具体新增能力尚未实施；既有收费授权保持关闭。

- 2026-10-05 最新实施约束优先：V1 只部署单机、本地服务、SQLite；候选身份、幂等、Job receipt 和基本崩溃恢复必需。多实例/HA/OAuth/公网 SSRF/多节点 lease-fencing/生产级 outbox 暂不实现。每个里程碑必须结束于真实可运行业务演示；接口、文档、测试数不能替代链路。A2A 队列问题先官方最小复现及上游核对，不改安装包或维护大 fork；必要修复限隔离、可替换的最小补丁。

- 先读current_context.md、PROJECT_BRIEF.md；当前架构以2026-10-05的TECHNICAL_PROPOSAL.md、FRAMEWORK_ORCHESTRATION_DESIGN.md和IMPLEMENTATION_ROADMAP.md为准。最新用户附件优先于历史三产品/固定协作计划。
- 四能力：Coding产生代码/配置Candidate Change；Config生成策划Candidate Config并做确定性预检/diff/确认；Verification独立验证冻结候选、不编辑候选；NPC独立负责Memory/RAG/角色互动。失败证据回Author，修订产生新候选，不默认递归优化。
- 仅Config→Verification、Coding→Verification两条跨产品边，复用同一标准A2A能力/Card/client schema；不新增Config↔Coding。MCP是各研发Agent到工具的共享边界，不以verify_everything代替独立QA Agent。
- Coding保持Codex Runtime＋官方Python SDK＋业务Adapter，保留原生动态0..N子Agent；主Agent判断任务/人数/分工。旧固定1＋3只是benchmark，负面结果不取消动态能力。产品提供auto/single，实际使用与允许使用分开记录；不重写Runtime主循环或子调度器。
- 新稳定SDK/CLI须固定配对、源码/二进制hash与协议回归；历史alpha/参考dev SDK证据不代表当前稳定版全兼容。fresh child工具传播、role权限和DeepSeek路由须实测，不凭文档或提示词声称子只读。原生MCP优先按稳定版验，必要时沿受测dynamicTools→MCP client窄转接，不建设通用协议网关。
- Config、Verification、NPC采用各自LangGraph，按需复用LangChain模型/工具/结构输出。图节点不等于Agent；schema/规则/统计/hash/权限/执行交程序。保留确定性领域逻辑，旧手写Loop不包进一个大节点。
- Author先物化并冻结完整manifest（baseline/candidate/scenario、规则/环境/Schema及diff来源），再按manifest hash确认。候选确认、验证预算、最终采纳/发布分别记账。Verifier只读输入、写自己的证据；完整日志/仓库不无条件经A2A传输。
- A2A completed表示报告交付，可携带PASS/FAIL/INCONCLUSIVE。准入前不支持kind/profile或非法输入拒绝；已接收任务缺证据/检查暂不可用返回不确定。确定FAIL不能被模型解释覆盖；所有必需检查完整通过才PASS。
- checkpoint、A2A TaskStore、领域账本、Job和世界各有所有权。副作用前持久业务ID/输入hash，按receipt对账；重复消息/resume不重建逻辑operation。物理attempt、模型费用另计；新revision不重置总grant。首版同thread单driver，多实例需另验。
- 游戏Python规则唯一权威，Unity负责玩家表现/输入；NPC可信session绑定存档/角色知情scope，世界state＋receipt＋outbox同事务，记忆inbox/投影对账。模型不能决定奖励或把研发资料当角色经历。
- 成品所有LLM推理用DeepSeek（含Review/子Agent/辅助/修复），禁止隐式provider fallback。密钥不进前端/Player/日志/证据。SDK reader不能等待长审批/QA回调，取消模型、A2A任务与物理作业分别验收。
- MCP/Adapter宿主不自动继承Codex shell沙箱。当前numeric worker只是可信本地配置执行，不能加载不可信代码；代码/build候选须受限Worker、冻结Oracle、无模型凭据和真实清理回执。
- Unity完整Editor/Player tests、产品Player构建、真实OS输入、权威状态对照和进程回收是最终门槛；手测/纯C#不能替代。skip/旧XML/零测试不算通过。
- 统计目标按真实业务、独立pilot与预算预注册；旧5%/2pp/314160场不是默认标准或授权。描述性结果不冒充总体非劣/AV证据；确认集不回流调参，重复计算不增加统计n。
- 协作效果分别比较合理single、资源增强single和动态协作，必要时同分工串/并。可重复业务质量收益可支持更慢/更多token；功能可用不代表质量增益，旧封闭profile结论不外推。开发过程委派不是产品效果证据。
- 旧项目、Codex参考树与封存实验保持只读；游戏与工作台分仓，当前工作台已初始化Git（实施基线321ae64）。不覆盖用户未提交工作。删除旧实现只指从新运行路径淘汰，历史源码/失败证据不删。
- 使用显式项目解释器和依赖锁，研究env独立。区分官方事实/开源参考/项目决策/待验假设，记录日期和证据边界；fixture不算真实Agent/模型/引擎验收。阶段末更新current_context，主方案/路线同步，不重复扩一批计划。
- 2026-10-04协作原始包、真值、manifest、wire/events、盲判seal和费用总账不可覆盖。先前授权仅六公开评测包及分析发送DeepSeek、累计USD3。2026-10-05用户另授权V1 Schema/规则/候选/4场指标及必要摘要到官方chat/completions，仅deepseek-flash、最多8次/USD0.50；首跑用6次、续验后已8次用尽，批次交付后不自动追加其他材料。新收费任务需明确范围/cap，不重置旧账本或扩大外发。
- V1首次真实模型解释误读负AV方向；程序从原始rows用Fraction生成中文数值事实，模型草稿单列未核验，不能覆盖事实/verdict。首次MCP日志序列化故障与原报告保留；附录/新Task不抹去首跑失败。首轮当时没有付费重跑；后续新任务仍保留非法策略/过度解释失败，不声称无故障首跑或模型质量验收通过。
- 2026-10-05续验后费用状态：旧V1批次8/8调用已完成，原6次账本和失败报告不改。用户另授权6 Config开发题与固定dev-c01 QA，最多16次/4场/USD0.50；已16/16完成（首轮6 Config+4 QA、第二轮同6题开发回归），新实际战斗4场，确认集/合成解释未运行。两批均无未知调用，调用额度已耗尽；不可复制账本分支或换目录继续消费。新真实评测仍需具体材料/cap授权。首轮5/6与QA非法策略/Trace过度解释保留；同题回归不能声称独立质量确认。

- 2026-10-05工作台续轮：React/Starlette本机入口已接现有图/A2A/MCP，默认模型关闭；已准入QA显式恢复可零推理续checkpoint，但未知Job仍拒绝。新两题32k/USD0.40授权实际7/8调用、8场、0未知，费用估USD0.00663312；题目完成后剩余1次关闭。两次响应各双Decision旧解析仅取首，原9条reason保留，不声称无故障通过；新exact-one guard仅离线通过，不能把新代码倒算到原质量成绩。详见workbench-qa-20261005证据。

- 2026-10-05 JSON/Config续轮：JSON mode默认，公开LangChain generate保留全部choice，严格原文校验；4次旧异常上下文协议回归通过，12题Config首次确认独立助手复核12/12（24标准）通过，非盲非真人/非QA全链。新授权28次/USD1.10实际16次/0战斗/估USD0.018343908，剩余12次关闭；json-config-acceptance-v2为master scope，两个子账本均封存，不能续用。旧v1准备无调用。原词句/原评分保留，不以同集结果调参后再称独立确认。

- 2026-10-05 Coding续轮：正式SDK/默认CLI固定0.160.0；新coding文件能力支持single/auto原生子Agent，仅primary动态写，MCP只读。最终fixture及189项测试通过，尚非真实模型里程碑；新scope bd9ff50285c0757d777932617f3e1ce9d01648e1d90b08d82fcac598d70e1c48（coding-runtime-demo-v1）待用户授权，最多24 Responses＋4 Chat、4场、USD0.85。旧授权均关闭。授权后run_coding_demo单次执行，先查源码/SDK/冻结环境与Review树绑定，不自动重跑或应用。

- 2026-10-05最新：coding-runtime-demo-v1已获明确外发授权并完成20调用/4场，峰价估USD0.021308352，未用8次关闭。自主spawn0、原生Review子线程2；QA机制弱关联保留，不当协作质量证明。中文最终使用手册待全产品完成。M1只在D:/Desktop/graytower-game新clone实施，旧游戏继续只读。
