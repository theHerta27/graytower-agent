# 当前上下文

更新：2026-10-05，Asia/Shanghai。工作目录D:/Desktop/mihoyo-agent-project，尚不是Git仓库。旧游戏、旧Coding、Codex参考树及现src/封存实验保持原样。本轮是四能力架构审计、必要本地验证和方案交付，不是完整产品实施完成。

## 当前有效的产品边界

1. Coding：Codex Runtime＋官方Python SDK＋业务Adapter；保留主Agent动态0..N原生子Agent，按任务选择人数/分工，正式入口auto/single。旧规则/契约/反例1＋3仅benchmark，不固化；负面profile结果不取消原生动态功能。
2. Config：自然需求→schema/config/规则查询→结构化候选→确定性预检/diff→策划确认；默认不是自动数值优化。先冻结完整Manifest，再确认其hash，包含baseline/candidate/scenario/规则/schema及diff来源。
3. Verification：独立QA Agent，只读Author给定候选，理解意图、计划/执行检查、调查失败、核验证据、交付PASS/FAIL/INCONCLUSIVE；不修改候选。失败回Config/Coding，由Author产生新revision、新请求，延续总预算。
4. NPC：独立LangGraph＋LangChain，Memory/RAG/角色状态、多轮与合法世界行动；不因其他能力协作而拆多Agent。

只有Config→Verification、Coding→Verification两条跨产品边。一个标准A2A Card/verify_candidate能力，同一客户端schema；不造Config↔Coding。MCP是研发Agent→工具的复用边界，不把Verifier包装为verify_everything。内部程序节点可直调领域接口。成品LLM全部DeepSeek，包含Review/子任务/辅助；不要求当前开发助手更换模型。

## 本轮完成与发现

主文档已更新：TECHNICAL_PROPOSAL.md、FRAMEWORK_ORCHESTRATION_DESIGN.md、IMPLEMENTATION_ROADMAP.md；README/AGENTS/原任务书优先说明/VALIDATION_REPORT第11节同步。三个源码/官方版本审计在research/evidence/*-audit-20261005.md。旧计划作为历史，不再驱动默认架构。

- 旧Verification根层与v2含Author/修候选循环；当前combat_worker也仍apply_changes。保留校验/Evaluator/模拟/账本/恢复，把生成归Config，Verifier新契约只读完整候选；完成收据补上游预期hash，失败诊断也持久化。当前src没有被静默迁移，仍是旧numeric基线。
- 旧Herta尚无Codex接入，UI/工作区/安全/事件资产可迁，手写Loop不迁。源码SDK默认审批accept且reader同步handler；fresh child不自动继承父dynamicTools，旧角色权限投影与现文档不同。不能靠role/prompt说子只读，G0要求shell/apply_patch/MCP/dynamicTools越权写负例。
- 官方当前CLI0.160.0；历史测试alpha0.159.0-alpha.12.1；参考SDK0.0.0-dev默认CLI0.153.4，三者分开。正式采用发布SDK默认pin优先评估，显式替换runtime需另过矩阵。先验稳定版原生MCP，必要时用受测dynamicTools→官方MCP client窄桥，旧桥是MCP1.26 fixture。
- 新隔离环境research/.venv-protocols安装A2A SDK1.2.1/spec1.0、MCP2.3.0、LangGraph1.2.12、checkpoint4.2.0、sqlite saver3.1.1、Pydantic2.13.5；完整锁在research/probes/protocol-requirements-20261005.lock.txt，pip check通过。旧环境不升级。
- 冻结候选probe：6项边界测试、真实4场战斗，完整4Trace；Author生成1.4→1.7，Verifier只读，结构PASS、行为DESCRIPTIVE、总体INCONCLUSIVE。9文件hash、40旧游戏源/配置、8当前src核对不变。证据research/evidence/frozen-candidate-probe-20261005及-review.json。只有逻辑边界，非OS沙箱/A2A产品。
- 标准协议probe：真实loopback A2A1.0、两个官方测试client、一个Card/skill、MCP2 stdio真子进程、固定LangGraph决策；4 tests含37功能断言通过。owner隔离、三verdict、业务去重、INPUT_REQUIRED同Task续行、断流Subscribe/Get、取消及SQLite重开读回通过，候选不变，0模型。它没有接真实Codex/Config或游戏，也未测运行中跨进程恢复。
- A2A SDK1.2.1终态再输入拒绝后出现2个EventQueueSource dispatcher/pending/OpenTelemetry关闭告警。功能PASS且production_ready=false，不能完成生产生命周期门槛。G0先上游修复或受测最小补丁；不删除失败记录、不绕改安装包。agent最终run为a2a-mcp-test-20261005-e8qqhg02；父任务独立重跑run为si27ylda，37项和清理缺口均复现。
- 两份独立架构评审共5项实质问题已修并复核，记录architecture-review-domain/runtime-20261005.md。清理缺口仍明确待修，不用文档一致代替产品实现。
- 父任务6＋4项新测试独立重跑与来源hash核验记录research/evidence/architecture-validation-20261005.json；旧证据持续由check_documents.py核验。全部新增模型调用0，真实战斗仅4场，无新增DeepSeek费用。

## 下一步执行入口

按路线M3-A/B先交付Config生成/预检/确认→A2A独立Verification计划/调查→证据报告回Author。先trusted config，独立QA入口可选现有候选，不等待完整Unity；把协议/领域两条probe接成真实模型链还未做。产品实现前建Git、锁版本和输入/报告schema，接跨revision总grant、真正身份、持久Job与失败证据、工作台页面。

并行M1 BattleSession/真人输入/同规则复现、G0-C稳定SDK与动态Runtime、G0-U真实Unity。M2再接代码/build冻结候选到同一QA；M4 NPC接版本化世界支援；M5四能力独立入口与联合演示。旧三产品人日估计不继续当承诺。

Unity最终必须真实Editor EditMode/PlayMode、UTF Player tests、产品Player、OS输入、权威状态与进程回收；本轮未启动引擎。游戏尚是模拟/回放底座，完整可玩输入未交付。NPC拟120盾/各自3普通回合、SP+1二选一未实现。撤销默认5%/2pp/314160场；先描述性与机制检查，概率声明按独立pilot和业务/预算预注册。

## 历史冻结证据与费用授权

2026-10-04固定协作16开发＋28确认已结束，不重复启动。single/A+/parallel各14/14已知根因、0FP，完整证据9/14、10/14、8/14；四串并对Runtime墙钟少46.9%，非全产品端到端或质量等价。结果只适用于该profile。报告research/evidence/collaboration-evaluation-20261004.md；原始packet/oracle/manifest/wire/events/盲判seal保持原样。

共享账本352预留/350已知/2未知，峰价已知实耗＋未知预留USD1.022392；100万输出总cap内。用户明确授权仅六冻结公开包及Agent分析到DeepSeek responses、累计USD3，不能重置账本或扩展为新源码授权。本轮无收费调用；新真实模型批次先确定材料范围与总cap。

历史Verification16 tests、最终12正常＋4故障恢复、212场业务探索、检索结构探索；游戏181 Python/16纯C#，旧Coding206/13skip/167subtests及React24均按原日期引用。不是本轮全面重跑，也不能当四能力/引擎验收。详细证据与限制在VALIDATION_REPORT.md。
