# 灰塔 AI 游戏研发工作台

仓库：[theHerta27/graytower-agent](https://github.com/theHerta27/graytower-agent) · 当前研发入口：[feature/reliable-game-agent](https://github.com/theHerta27/graytower-agent/tree/feature/reliable-game-agent)

**当前新入口：** 双击 **打开灰塔研发助手.cmd**，打开 http://127.0.0.1:18790/development 。第一次使用请读[开始使用](开始使用.md)；业务定位、技术取舍与求职表述见[项目说明](项目说明.md)。

## 当前主线（2026-10-27）

2026-10-27 最新结果：用户授权的连续批次已结束，共 86 次已知调用、0 未知，峰价估算 USD 0.314869152，余 20 次关闭。资源修复通过；上限首次未实现、一次修订后通过该功能验收；护盾核查交付结论且未误改。两道资料题开放组均未使用知识库，不能声称 RAG 提升或实际使用后无效。保留失败与工程整合的评分限制，详见[本轮真实结果](research/evidence/completion-20261027.md)。 当前保留单 LangGraph＋LangChain、Git 候选、Docker 检查和人工采用；词法资料检索可选，不新增向量库或模型对照。

新研发入口采用 **LangGraph＋LangChain 的单 Agent**：动态决定调查、修改、检查和修订。Codex Runtime/SDK退出新默认路径，历史实现和实验保留；Herta不改。

主要实现位于 [`development/agent.py`](src/agent_workbench/development/agent.py)（图与恢复）、[`model.py`](src/agent_workbench/development/model.py)（ChatDeepSeek工具调用与预算）、[`context.py`](src/agent_workbench/development/context.py)（有限上下文）、[`memory.py`](src/agent_workbench/development/memory.py)（有来源和版本的项目记忆）。候选、Docker检查和人工采用仍复用原领域模块。

页面支持新需求、真实源码Diff、检查、澄清回复、原任务继续、项目记忆管理、人工采用和恢复。新默认安装无需Codex SDK；仍只处理当前灰塔Python规则与配置，不把图节点、检查程序叫作多个Agent。

新增“研发资料”：从当前游戏Git版本的README/docs中按章节预览、导入并确认；Agent按需检索冻结原文，返回出处、行号和版本。SQLite FTS5/BM25完成本地词法检索，不新增LlamaIndex或Embedding。12条本地查询中，11条有相关资料，10条首项命中；同义表达漏召回被保留，尚不代表真实任务修复质量提升。方法与复现入口见[检索评测](research/evals/knowledge-rag-v1/README.md)。

较早的非思考基线（三题）记录：资源原子性修复完成，可配置上限未实现，护盾核查未交付有效说明。51次调用、峰价估算USD0.094584，余1次关闭，候选未采用。不能将程序结束或原规则通过直接当任务成功；详见[本轮结果与限制](research/evidence/knowledge-rag-20261027.md)。

基于失败已修复源码分页和上下文裁剪：准确续读、完整JSON、历史来源索引和剩余调用提示；工具标记文本现在返回未完成，原文与用量保留。两份旧响应本地重放和真实Git/Docker业务探针通过；这不等于新的真实模型成绩。

此前非思考开发回归记录为1题完成、2题未完成；两份异常交付已明确标partial。45次、峰价估USD0.124739，余7次关闭。当前完整405项回归（401通过/4既有skip）、前端34项及构建通过；详细成功与失败均在上方结果记录，不把同题回归当独立质量确认。

10月25日的新图还在临时游戏副本完成了真实Docker的“资源检查失败→脚本决定修订→资源6项及规则99项通过→人工采用→恢复”，并验证待确认记忆提案。**这段历史模型决定来自明确标注的脚本，0次外部调用，只是工程链路证据。** 10月27日真实模型三题结果见上文；更多独立任务和稳定性仍待验证，旧封存额度不可续用。操作见[开始使用](开始使用.md)，原理与求职定位见[项目说明](项目说明.md)。

<details><summary>2026-10-18的Runtime阶段记录（历史）</summary>

新代码位于 [`src/agent_workbench/development`](src/agent_workbench/development)。它从真实灰塔Git提交创建隔离候选，让单个Codex Runtime通过检索、读取、编辑和真实检查反馈继续修订，不按旧演示题号分支。

新React/Starlette页面支持创建新需求、审阅源码前后变化、按需检查、人工采用与恢复。先修改隔离候选，只有人明确确认采用才写回原游戏；不自动Git提交或更新Unity。真实模型运行先展示材料和预算，用户确认后才开始，密钥不交给Runtime或检查容器。CLI仍可通过 `python -m agent_workbench.development --help` 使用。

已验证真实Runtime＋Docker能够在同一线程完成“检查失败→修订→通过”，其中模型响应为本地脚本，不能当真实模型质量成绩。匹配Python3.11.9环境后，完整游戏规则99项全部通过；页面在临时游戏副本走通创建、手工候选修改、真实99项检查、采用、恢复，真实原游戏未改。本轮0外部模型调用，真实模型自主修复留给用户亲测。新资源参数检查在原游戏发现2项失败，作为真实待修问题保留。

想了解这轮具体怎么开发，读[开发记录](开发记录.md)：保留失败、修正、命令原始记录位置和每阶段提交。

</details>

## 旧V1演示入口（2026-10-08，保留参考）

本机双击 **打开任务中心.cmd**，浏览器打开 **http://127.0.0.1:18784/tasks**。先点“① 体验数值调整”和“② 看护盾代码修复”，按页面查看改动、独立报告、采纳到本地测试版本和回退。普通启动关闭模型，查看结果和重新检查不产生模型费用。

**第一次使用：本机双击 [项目说明书.html](项目说明书.html)，阅读带目录和步骤导航的浏览版。** 也可以直接看 [中文使用手册](使用手册.md)，或查阅 [安装与 GitHub 操作](GitHub使用手册.md)。说明书包含启动、两条体验流程、按钮含义、试玩回退、玩家营地和常见问题。

本轮已实际演示 Config→独立 QA→配置采纳→真实规则试玩→回退，以及真实 Coding 护盾修复→独立代码 QA→独立源码版本采纳→回退。第二个战技点修复首次 QA 失败，已禁止采纳；追加修订由用户留待亲测，未执行。代码采纳不自动替换 Unity。原始结果和封存账本保留；实现与验证摘要见[交付记录](research/evidence/v1-product-20261008.json)。下文早期端口及进度作为历史记录保留，以本段及手册为当前入口。

新机器安装与 GitHub 操作见 [GitHub 使用手册](GitHub使用手册.md)；玩家演示步骤见 [使用手册](使用手册.md)。源码配套游戏仓库为 https://github.com/theHerta27/graytower-game 。

## Agent 源码入口

四项能力位于 `src/agent_workbench/`。中文模块说明：[Coding](src/agent_workbench/coding/README.md)、[Config](src/agent_workbench/config/README.md)、[Verification](src/agent_workbench/verification/README.md)、[NPC](src/agent_workbench/npc/README.md)。Verification 工作台主入口现位于 `verification/agent.py`；`qa.py` 保留旧导入兼容。共享领域、工具、模型和协议实现位于相邻模块，游戏规则与 Unity 位于同级 `graytower-game` 仓库。

<details>
<summary>历史开发记录（含旧端口与阶段状态，仅供追溯）</summary>

## 2026-10-05：可直接演示的营地闭环

按用户“优先快速闭环，不扩复杂严谨度”的最新要求，本轮交付本机演示：React营地→真实LangGraph离线对话/玩家选择→世界支援→Unity实际按键→同规则结算→分享战报→角色记忆隔离。入口 http://127.0.0.1:8780/camp ，双击 `开始剧情演示.cmd`；中文步骤见[使用手册](使用手册.md)。研发真实历史结果仍在8767。当前演示NPC是明确标注的离线台词，0新增模型调用，不冒充真实DeepSeek自由对话。

Unity升级官方6000.3.21f1后，同原存档、UIA读取和Alt+F4退出已正常exit0；新键盘5项PlayMode/Player均通过，构建02完整封存。当前真实营地首场85条命令胜利：1条由原生Enter两次提交，其余84条由页面明确标注的固定策略完成；战报实际分享后岚知道、砾仍0来源记忆。不能将固定策略等同OS自动操作。新NPC4项unittest、前端8项测试与build通过。

本轮先保证正常展示，暂不扩分布式保障、完整故障矩阵、Electron和大型协作对照。NPC真实模型/代码build隔离Worker等仍待后续，四能力完整发布未宣布完成。下方早期失败/预算记录保留为历史，最新运行入口以上文及手册为准。


**2026-10-05 M1 最新验收：** 用户已在真实 Unity 中完成破盾战技及丢响应重试：相同请求提交两次，仅结算一次，revision 1、1 条命令、11 个事件，完整组件状态与权威快照一致。已确认态 Player 重启和正式启动器均读回同一存档、无新行动。但原生 Alt+F4 退出两次触发 UnityPlayer.dll 访问冲突；一次独立恢复探针在读回后超时回收。正常退出、pending 跨 Player 重启及完整自动战斗输入未通过，M1/G0-U 不关闭。详见[现场证据](research/evidence/m1-player-interaction-20261005.md)。

最新 Coding 增量：真实 DeepSeek 单任务及 auto 文件编辑→原生 Review→冻结候选→同 A2A 独立 QA 已执行，20次请求、4场、峰价估USD0.021308352；未用8次关闭。auto自主委派0，原生Review子线程2，不据此声称多Agent质量提升；首次编辑失败及QA弱机制关联保留。新增文件工作台可浏览两条真实记录和原报告，见[真实验收](research/evidence/coding-live-workbench-20261005.md)。

“可玩游戏＋Coding＋Config＋独立Verification＋NPC”的技术与实施工作区。2026-10-05开始单机 V1 实施：Config、独立 QA、标准 A2A/MCP 和本地 SQLite 恢复已有 CLI，React 浏览器工作台接入同一业务服务；四能力全产品、Electron 和可玩 Unity 尚未交付。

先读[总体方案](TECHNICAL_PROPOSAL.md)，再看[实施路线](IMPLEMENTATION_ROADMAP.md)、[验证报告](VALIDATION_REPORT.md)和[当前上下文](current_context.md)。图状态、领域事实、外部Job与NPC丢响应恢复详见[框架设计](FRAMEWORK_ORCHESTRATION_DESIGN.md)。

此前 Config 结果：默认JSON严格单决定适配已完成4次真实已知上下文回归；12题Config首次确认均首答完成，独立助手24项标准复核12/12通过。16调用峰价估USD0.018343908、0新战斗，未用额度关闭。此前[候选演示](http://127.0.0.1:8766/)保留1.4→1.48的真实记录；本轮领域适配升级后，旧冻结候选新检查会提示环境漂移，旧报告/收据仍保留，完整结果与限制见[确认报告](research/evidence/json-decisions-config-confirmation-20261005.md)。

## 浏览器工作台

当前新增的Coding真实演示位于 [文件工作台](http://127.0.0.1:8767/)。点击“文件开发”，可查看两种模式的实际修改、原生 Review，再点“核对这一候选”进入差异与同一独立QA报告。该目录只复制已关闭批次的证据；浏览不会新增模型或战斗。重启命令：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m agent_workbench.cli --data local-data/coding-workbench-v1 web --port 8767
```

需要在新目录建立展示副本时运行 `scripts/prepare_coding_workbench_demo.py --data <新目录>`，拒绝覆盖已有目录；`coding-runs`、`coding-show <operation_id>` 可在CLI只读查看。Coding Responses额度独立于下文Config/QA的Chat开关，当前普通`web`不会据`--call-cap`开放Coding。完整中文使用手册在游戏、NPC和联合交付完成后补齐。

本机入口为 `http://127.0.0.1:8765`。策划从“配置提案”查看需求与前后差异，按完整候选身份确认；“独立验证”可选择现有候选、填写验证目标和战斗预算，再读取程序计算的事实、运行错误、战斗摘录和单列的模型意见。确认不会应用配置或启动战斗。

```powershell
Set-Location -LiteralPath 'D:\Desktop\mihoyo-agent-project\frontend'
npm ci
npm run build
Set-Location -LiteralPath 'D:\Desktop\mihoyo-agent-project'
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m agent_workbench.cli --data local-data/workbench-v1 web --port 8765
```

默认关闭模型，仍可查看、确认已有候选并阅读证据。本机 `workbench-v1` 的初始数据由 [prepare_workbench_demo.py](scripts/prepare_workbench_demo.py) 从真实历史结果只读复制，来源见目录内 `demo-provenance.json`；它是已有结果演示，不是新模型成绩。脚本拒绝覆盖已有目录。新机器无这些本地证据时使用空目录启动。

模型能力只能在服务启动时以 `--call-cap N --audit-path <已授权共享账本>` 开启；`--qa-only` 仅开放独立验证。网页不能改调用上限、凭据或数据目录。旧两批 8/8、16/16 调用均已用尽，不能用换目录或新账本复用旧授权。新 [QA 两题](research/evals/qa-independent-v1/README.md) 已获单独授权执行：7次/8场，费用估USD0.00663312，剩余1次关闭；语义目标完成，但两次双Decision响应异常保留。详见[工作台与真实验收](research/evidence/workbench-qa-20261005.md)。

页面刷新查询同一个持久操作；丢失提交可按原内容/同ID重试。服务重启把未完成操作标记为中断，QA 可显式恢复原请求；模型关闭时也可沿已有checkpoint和收据收尾，不新增推理。发现已启动但无收据的作业时停止并要求核对现场。这里没有多实例、高可用或运行中取消承诺。

## CLI 业务入口

此前CLI开发结果：Config首轮6个开发需求通过5个，修复后同题回归6/6；新候选已交独立QA跑4场，但首次非法策略和Trace过度解释仍计失败。预算/状态/报告/证据摘录已据此修复，后两项QA模型效果仍待独立确认，M3未关闭。详见[真实续验、费用与限制](research/evidence/v1-followup-20261005.md)。

使用当前项目 `.venv`；可用 [锁文件](requirements-v1.lock.txt) 重建。游戏仍固定使用可信的 `D:/Desktop/combat-foundation` 和它的解释器，新工作台不会改写游戏基线。真实模型通过环境变量 `DEEPSEEK_API_KEY` 提供凭据，禁止写入前端、候选或证据。每个 data 目录的演示调用账本最多 8 次；重启不重置。

```powershell
Set-Location -LiteralPath 'D:\Desktop\mihoyo-agent-project'
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
$wbPython = '.\.venv\Scripts\python.exe'
& $wbPython -m agent_workbench.cli --data local-data/workbench preview '把击破手战技倍率从1.4提高到1.7，其他规则不变'
& $wbPython -m agent_workbench.cli --data local-data/workbench draft '把击破手战技倍率从1.4提高到1.7，其他规则不变'
# 先阅读 draft 的 Diff，再把返回的完整 manifest_hash 填入下一条命令。
& $wbPython -m agent_workbench.cli --data local-data/workbench confirm '<manifest_hash>'
& $wbPython -m agent_workbench.cli --data local-data/workbench verify qa-001 '<manifest_hash>' '比较前后胜负和行动值，检查本批战斗是否变快' --max-battles 4
& $wbPython -m agent_workbench.cli --data local-data/workbench show qa-001
& $wbPython -m agent_workbench.cli --data local-data/workbench report qa-001
```

`preview` 不调用模型。`confirm` 绑定完整候选身份，也不自动模拟或修改基线。`verify` 使用官方 A2A client 调用本机服务，QA 通过 MCP 读候选、执行获批模拟、读证据；同请求重复执行复用报告。也可在一个终端运行 `serve --port 8771`，另一终端的 verify 增加 `--url http://127.0.0.1:8771`，服务端和客户端使用同一 data 目录。当前单用户本机信任范围，不声称多租户或公网服务。

完整演示脚本 [demo_v1.py](scripts/demo_v1.py) 默认只准备外发预览；`--live` 才执行真实模型。首次演示的范围见 `local-data/v1-demo/outbound-scope.json`。小样本总体结论只能 FAIL/INCONCLUSIVE，结构检查 PASS 独立显示；没有统计总体保证或 Unity 测试完成声明。A2A 暂不支持续输入与取消；未知作业不会静默再执行。

实测交付及已知失败见 [V1 实施记录](research/evidence/v1-implementation-20261005.md)。直接阅读已保存结果：`python -m agent_workbench.cli --data local-data/v1-demo report v1-live-demo`，不需要密钥、不调用模型、不跑战斗。`report` 由原始配对结果计算中文事实；`explain` 可另花最多一次调用生成未核验的模型解释草稿，不能覆盖程序事实或原判定。首次模型草稿曾误读负数方向，原输出保留，未用追加调用洗掉失败。

## 审计与研究证据

- [四能力总体方案](TECHNICAL_PROPOSAL.md)：业务流程、选型原因、候选与证据契约、产品页面与保留/迁移决定。
- [框架与恢复设计](FRAMEWORK_ORCHESTRATION_DESIGN.md)：Config/Verifier分图、A2A任务与Job/图状态分工、丢响应/重复恢复/取消。
- [Verification源码审计](research/evidence/verification-boundary-audit-20261005.md)、[Coding/Runtime审计](research/evidence/coding-runtime-boundary-audit-20261005.md)、[官方协议审计](research/evidence/a2a-mcp-langgraph-audit-20261005.md)。
- [冻结候选验证](research/evidence/frozen-candidate-probe-20261005-review.json)：6项边界测试、4场真实战斗、完整Trace，候选/旧源未变；结构PASS、总体INCONCLUSIVE，模型调用0。不证明OS沙箱或完整QA Agent。
- 协议验证使用独立[锁版本环境](research/probes/protocol-requirements-20261005.lock.txt)，A2A SDK1.2.1/spec1.0、MCP2.3.0、LangGraph1.2.12；[37项协议功能实测](research/evidence/a2a-mcp-boundary-probe-20261005.md)及SDK队列清理缺口见[验证报告第11节](VALIDATION_REPORT.md)；生产生命周期门槛未通过。新MCP2证据不覆盖旧MCP1.26桥升级。

当前已有 Config/QA 工作台；下一步独立确认单决定响应规范与完整质量验收，并行后续推进可玩 BattleSession、稳定 Runtime/动态子 Agent 和 Unity 执行门槛。Config 默认不自动搜索最优数值，Verifier 没有改候选的工具。

## 当前可运行的历史切片

2026-10-04可信numeric实验CLI：读取人工准备的需求和数值方案→沿LangGraph校验→暂停等待按hash批准→调用真实游戏核心→给配对AV/胜负转换的描述性报告。无需模型、Coding或NPC在线；当前JSON方案是操作者准备的。worker仍内部应用changes生成候选；它是迁移参考，不是新“Author冻结→Verifier只读”产品接口。新边界已用独立probe验证，尚未迁入src。

本机已验证Python3.11.9、LangGraph1.2.12、SQLite saver3.1.1和Pydantic2.13.5。使用现有隔离研究环境；其他机器先以[依赖锁](research/probes/framework-requirements.lock.txt)创建独立环境，并准备受信任的游戏checkout。`pyproject.toml`给出最小包依赖，尚无独立发行包/doctor。

```powershell
Set-Location -LiteralPath 'D:\Desktop\mihoyo-agent-project'
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
$verifyPython = '.\research\.venv-framework\Scripts\python.exe'
& $verifyPython -m agent_workbench.verification --data .\local-data\verification-demo --game-root D:\Desktop\combat-foundation prepare .\examples\verification-breaker.json
```

检查返回计划、12场预算和`plan_hash`，把确认的hash填入下方命令。批准后运行真实模拟；不更改游戏原配置。

```powershell
& $verifyPython -m agent_workbench.verification --data .\local-data\verification-demo --game-root D:\Desktop\combat-foundation approve breaker-exploration-001 --plan-hash '<准备结果中的plan_hash>'
& $verifyPython -m agent_workbench.verification --data .\local-data\verification-demo --game-root D:\Desktop\combat-foundation show breaker-exploration-001
& $verifyPython -m agent_workbench.verification --data .\local-data\verification-demo --game-root D:\Desktop\combat-foundation resume breaker-exploration-001
```

也可将`approve`改为`reject`。同request ID换内容拒绝；决定不可改写，新实验用新ID并重新确认。结果若已完成，恢复复用收据；已准入但结果未知则保守停止，不自动重算。当前只管理每计划预算，未实现跨revision授权总额，不能让模型无限自行创建新计划。

报告只给`DESCRIPTIVE_ONLY`，不证明总体胜率/严格非劣或玩家通关时间。可信本地numeric worker不是候选代码沙箱，禁止用这条入口加载模型生成的不可信代码。完整自然语言决策、工作台UI、异步作业、统计确认与生产发布仍待路线验收。

## 验证与证据

```powershell
& $verifyPython -m unittest discover -s tests -v
& $verifyPython research\probes\verification_slice_probe.py
& $verifyPython research\probes\check_documents.py
```

第二条会另跑4场真实模拟、强制退出故障子进程并建立新证据目录；不调用付费模型。真实DeepSeek收费脚本不应作为普通回归自动执行。

- [最终正常12场结果](research/evidence/verification-slice-final-20261004/result.json)、[最终故障恢复](research/evidence/verification-recovery-n7zc67l5/result.json)、[16项测试日志](research/evidence/verification-slice-tests-20261004.log)。
- [212场业务校准](research/evidence/game-semantics-calibration-20261004.json)：推翻默认5%改善等假设，全部为探索。
- [DeepSeek/Codex证据](research/evidence/runtime-deepseek-assessment.md)：3次真实请求，受限工具往返和inline Review；原生MCP namespace未证兼容，dynamicTools→官方MCP client窄转接仅离线通过。
- [检索与MCP说明](research/evidence/retrieval-mcp-notes-20261004.md)：词法/别名/结构对照，NPC仅有scope fixture。
- [历史游戏审计](research/game-verification-audit.md)、[Coding审计](research/coding-audit.md)、[Codex源码](research/codex-source-audit.md)、[统计核算](research/verification-statistical-budget-20261004.md)、[Unity最终自动化合同](research/unity-automation-delivery-20261004.md)。

历史统计计算保留，但旧12万场/任务与31万场整批不再是默认执行计划。当前没有完成真实Unity自动链路；它仍是最终硬门槛。原始任务见[PROJECT_BRIEF.md](PROJECT_BRIEF.md)和[mihoyoJD.md](mihoyoJD.md)。

## 真实Coding协作实验

已实现Codex Runtime原生1主＋3专业子Agent，全部使用DeepSeek；领域分工为规则、契约/恢复和反例，Runtime负责子线程与生命周期。本机研究入口[collaboration_profile_runner.py](research/probes/collaboration_profile_runner.py)在任务开始时支持`single`、`single_plus`、`team_parallel`、`team_serial`。它是完整冻结资料下的只读候选评审实验入口，尚不是带仓库检索/改码、取消恢复和工作台的正式Coding产品。

本轮方法、质量/费用/时间结论和限制见[真实对照报告](research/evidence/collaboration-evaluation-20261004.md)。实验脚本可运行不自动代表质量提高；固定profile不等于原生动态产品策略，后续正式集成按[路线4.1及8.5](IMPLEMENTATION_ROADMAP.md)。

实测已结束：16次开发＋28次确认。确认single、六轮single_plus和team_parallel均找全14次已知根因、无误报；严格完整证据分别9/14、10/14、8/14。四个同分工串并配对运行耗时合计减少46.9%，但没有证实质量提升。这只说明本固定profile暂不推荐；新产品仍按用户要求保留原生动态auto及single基线，主Agent自由判断0..N，不因旧实验取消原生能力。

以下只运行本地检查，不调用付费模型：

```powershell
& $verifyPython -B -m unittest discover -s research/probes -p 'test_collaboration_*.py' -v
& $verifyPython -B -m unittest discover -s research/evals/coding-collaboration -p test_evaluate.py -v
```

真实重放可调用profile runner的`--live --packet <公开packet.md> --mode <模式> --outdir <新的输出目录>`；完整已用参数保存在[确认manifest](research/evidence/collaboration-confirmation-manifest-20261004-fixed-v1.json)。必须显式给相应的模型请求数、总输出、单请求输出和wall上限，并继续共用`research/evidence/collaboration-live-global-budget-20261004.json`。当前授权限这六份公开包及分析外发、累计USD3；不自动重跑冻结batch、重置账本或扩大发送资料。重放旧题是演示，不增加独立确认样本。密钥只由受限后端读取，不能写入命令、前端或证据。

</details>
