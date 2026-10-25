# 当前上下文

## 2026-10-25框架主线实施（以本节优先）

用户已批准同一灰塔项目使用LangGraph＋LangChain＋轻量项目记忆，撤回development固定Codex Runtime前提。已实现agent.py单Agent图、ChatDeepSeek工具消息适配、有限上下文、稳定模型决策落账、澄清/检查暂停与恢复、SQLite记忆及页面CRUD；候选、真实Docker Job、人工采用恢复继续复用。默认启动不要求SDK，旧Runtime/旧V1/Herta和封存结果保持原状。

本轮无新外部模型调用。新图已用明确标注脚本模型，在临时游戏clone完成资源6项FAIL→修订6项PASS、完整规则99项PASS、待确认记忆提案、采用/恢复；原游戏tracked clean。初次Docker因本机访问权限被判not_started，后续显式同Job恢复；Git跨账户safe.directory问题以单命令配置解决，原失败日志保留。

独立审查发现3项Important（所选run的scope混用、checkpoint有问题但结果未发布时丢失问题/非法resume、后准备的预览遮住待继续任务），已由失败复现覆盖并修复，同时统一畸形澄清和CLI放弃状态；32项图/服务/API回归通过。最终完整341项（337通过、4既有skip，250.418秒）、前端23项/构建通过，Windows PowerShell解析与启动复用通过；记录于local-data/framework-migration-20261025/final-after-review.log。已确认记忆在第二任务材料中召回，浏览器实际创建新候选与新增记忆通过。

当前方案见项目说明.md、开始使用.md和docs/superpowers/plans/2026-10-25-graytower-framework.md；过程与证据在开发记录.md。新scope为development-langgraph-v1、官方chat/completions，旧Responses批次不续用。新框架真实DeepSeek任务质量仍待用户页面确认新材料/预算后体验；不宣称多Agent、框架质量提升或通用游戏适配。本轮不自动推送GitHub。

## 2026-10-25最新：学习主线讨论与首次真实结果

三题已按原scope各尝试一次：34次已知DeepSeek调用、0未知，按封存峰价估0.038383104美元，未用14次关闭。资源候选一行修复，独立7/7和规则99/99通过，但16次额度耗尽、Runtime失败；可配置上限无修改、5/9未实现，11次后本地网关拒绝；护盾核对无修改、1/1和99通过，7次后网关拒绝、无完整解释。后两题仅有ValueError/通用400，末次请求接近128k限制，精确原因未定位，不把推测写成事实。原游戏未改，三题均无完整Agent交付；候选验收与流程状态分开。

用户明确项目用于学习、向面试官证明对Agent的理解，不再要求优于通用Agent；希望任务清楚、目标明确、结果直观，适合时尽量使用LangGraph/LangChain。当前在讨论整体方案，暂停继续编码与新增模型调用。现有development主线仍为Codex Runtime/官方SDK；旧verification已有LangGraph，models.py已有LangChain ChatDeepSeek，但尚未接入新development主路径。不要把待讨论方案当已实现，不重新启动旧收费批次。

## 2026-10-25：三题真实模型批次获准恢复

用户明确允许真实模型，恢复同一封存范围9a5a2bb28b6036f62ff8aa6075d378c4a85c0862a893abbf768131bb2b7989e9；三题standard各一次，16／24／8次、总48次/USD2.15，只改候选、不应用。保留昨日暂缓与零用量原件，新增authorization-approved-20261025.json；不创建替代目录或重置旧额度。代码6fb8935未变，准备先核对范围、账本与Docker，再一次执行；运行结果随后追加，不预设成功。

## 2026-10-24：优先真实任务，模型暂缓

用户面试临近，范围收缩为三题standard单Agent各一次，暂停领域工具对照与其他扩展。三题与独立验收已准备；真实Docker原游戏结果分别为资源4/7、可配置上限5/9、护盾正确行为1/1，原99项规则通过。已补精确片段替换并验证，SDK/Docker反馈冒烟通过但为脚本响应。

本批real-agent-tasks-20261024-v1的指纹9a5a2bb28b6036f62ff8aa6075d378c4a85c0862a893abbf768131bb2b7989e9，拟48次/2.15美元；用户明确回复“暂不调用模型”，当前0外部调用、费用0，authorization-decision.json已记暂缓。禁止自动执行或另建批次绕过；不得把准备和本地检查写成真实模型修复成绩。只读审查3项Important已按RED→GREEN修复，后续工程状态见开发记录末段。原游戏和旧V1未改，未推送本轮实现。新可选game工具是暂停的WIP，不是当前已证实收益或本批运行路径。

最终019完整回归301项（297通过、4既有skip），224.418秒；020三个账本均0调用、group未领取、原scope匹配。尚未完成真实模型验收与模型成功/失败案例。相关公开任务和准备说明在research/evals/game-agent-pilot-v1；不要为追求简历数字再次扩建或伪造结果。

## 2026-10-23：给简历撰写AI的事实资料

新增给简历AI的项目资料.md，列明主线、路径、源码入口、GitHub分支和证据边界。工作台当前代码79742ce已于2026-10-19推送至私密仓库theHerta27/mihoyo-agent-project的feature/reliable-game-agent分支，远端提交已核对一致；main仍为旧版。本次仅整理资料，未新增模型调用、代码实现或效果实验；新链路真实模型质量仍未验收。下方10月18日的未推送表述是当时状态，以本节更新为准。

## 2026-10-18：新主线工程交付，真实模型留给用户亲测

- 用户要求先完成工程与中文说明，不授权single-agent-resource-v1；本轮0外部模型调用、费用0。保留原范围及零用量账本，不自动执行、追加或重封旧批次。后续由用户从新页面查看材料、明确确认费用后亲自开始。
- 代码位于 `D:/Desktop/mihoyo-agent-project-next`，分支 `feature/reliable-game-agent`；是同一Git仓库的隔离工作树。旧目录、V1、历史报告保留，未推送GitHub。基线4ad8c6d；主要实现14f14a7、06d7c1a、8bfdb6d、bb9aa89、a0ab122、36b4360及其后收尾修复。
- 新入口 **打开灰塔研发助手.cmd** → `http://127.0.0.1:18790/development`，首次为空，不依赖历史演示。React/Starlette/API/CLI共用DevelopmentTask：新需求、真实源码Diff、文件读取/编辑、可信检查、实际工具过程、人工采用、恢复与补丁导出。中文步骤见开始使用.md，过程见开发记录.md。
- 从灰塔提交5508730读取55份允许材料（49份文本）；允许修改Python规则和v2配置，可信测试/规则/脚本只读。版本、快照、SQLite幂等记录和Job receipt保护原项目；检查绑定候选、镜像和执行定义，未知作业不自动重跑，确定未启动可显式重试。
- 官方SDK/Runtime0.160.0一个线程、一个turn，动态工具回同一业务层；默认无Review、子Agent、宿主shell、A2A或旧MCP。真实Runtime＋Docker的FAIL→修订→PASS使用本地脚本响应，不算真实模型质量。
- Python3.11.9镜像已构建：完整游戏规则 **99/99通过**，旧7项环境差异已消除，未改源码/断言/金标。容器清理有真实回执。现存负数资源输入问题仍作为真实待修任务保留，额外6项为4PASS/2FAIL，不隐瞒或改标准。
- 人工采用备份原字节后写回，只在明确确认入口执行，模型没有采用工具；恢复遇到后续编辑或HEAD变化停止。基本崩溃对账支持prepared/restoring重放；页面显式提示可能部分写入，并区分已采用版本与当前候选。
- 真实浏览器在临时游戏clone走通创建→手工添加注释→99项检查→采用→恢复；原游戏和临时clone最后均tracked clean、HEAD5508730。证据local-data/delivery-browser-20261018/result.json；这是工程链路验收，不是模型修复实验。
- 最终收尾审查无Critical，4项Important均有复现与修复：PS5脚本BOM、失败原因展示、批次真实时间排序/活动run绑定、采用状态。Windows PowerShell5实际解析0错误；启动输出有进度与地址，新服务空任务、Key/SDK可用但无调用。完整最终回归结果见下方开发记录最新段，不沿用旧268当新成绩。
- 不宣称任意项目/恶意代码安全、Unity/C#修改或发布、多Agent收益、跨进程续跑模型会话及新模型成功率。独立验证Agent与效果对照仍是之后按实际体验推进的阶段，不因收尾而扩建协议或调度。

## 2026-10-18：求职主线收敛与Markdown项目说明（设计阶段）

用户明确说明文档用于求职，重点是业务、技术取舍、工程难点和个人理解，不需要操作演示或向面试官展示源码。NPC退出主线；用户未要求必须多Agent/A2A，并认可先做完整单Agent＋可信验证与人工采用、协作通过对照决定的方向。本轮新增项目说明.md，包含任务流程、技术职责、分阶段思路、评估和目标版简历；旧简历文档加入口提示，AGENTS记录最新优先约束。没有修改产品代码或执行新模型任务。旧V1事实仍以下文及原证据为准，不能把新目标算成已实现。

## 2026-10-17：中文说明书更新（仅文档）

按用户“赏心悦目、说人话”的要求，重写使用手册.md，并提供自包含的项目说明书.html：带章节导航、实际界面截图、分步体验、按钮释义、原始项目影响范围、玩家入口与常见问题。README统一当前18784入口，历史端口与阶段记录折叠保留。说明书对应现有可演示V1；没有把待批准的工作台改造方案当成已交付功能。此轮不修改产品实现、游戏源码或存档，不调用模型。

## 2026-10-08：可演示 V1 收尾，以本节为当前状态

已本地快进合回工作台 v1-business-acceptance（实现e73d09b，文件尾规范化b7c30dc）与游戏 m1-playable-session（5508730）；原启动器未提交修改及用户计划保留。本轮尚未推送GitHub。普通18784服务已启动，7任务与原报告可读；启动CMD实际退出0，回退后新开规则战斗实际倍率1.4。

按用户“快速完成闭环、先亲自测试”的要求，本轮停止追加收费实验。统一任务中心普通入口切到18784，默认模型关闭，中文手册已重写，页面提供两个直接体验按钮。Config可下载同源JSON/Excel、看独立QA、采纳配置、真实规则试玩和回退；代码使用正式CodingService与独立A2A/LangGraph/MCP QA，四项固定检查、补丁下载、独立源码版本采纳和回退。旧战斗继续保存的开场规则，新战斗才读取当前配置。

D01护盾修复真实独立QA通过；D02战技点候选 ad0287674007ceb113b364d346d8e628c876a99b185ce36572aea80b72217649 首次QA失败：修改了函数接口，四项原接口检查均TypeError。失败候选/原生Review/报告保留且不可采纳，不修改标准。v1-close-demo-v1已关闭：17 Coding Responses＋2 QA Chat已知调用、0未知，峰价估合计USD0.030888576，0新模拟战斗。拟议修订批次未获授权，用户选择先交付亲测，已关闭且0调用。

最终分支审查3项重要问题均修复：代码QA目标与实际模型使用记录、重复激活后按真实前驱回退、页面丢响应沿原重放/回退ID恢复。Python230项（226通过/4既有skip）、前端15项及TS/Vite构建、游戏153项通过。实际容器限额/超时/清理探针通过，但不宣称通用恶意代码安全。配置两对样本仅描述，不证明总体平衡；自动子Agent实际spawn0，不声称多Agent质量提升。Electron、通用代码/build平台、额外修订与质量评测留待后续，不因本轮交付冒称全部路线完成。新本地交付记录见 research/evidence/v1-product-20261008.json。

## 2026-10-08：真实 Python 护盾修复与结果页面

收到用户明确授权scope d054c1a5e7f35103e13d8f9c9cf21ff438f0d59dc671a2a10406f8234a4d0d72后，执行一次D-01受控故障真实修复：官方SDK/CLI0.160.0、DeepSeek Flash、auto许可、只读源码MCP、主线程独占effects.py编辑、原生Review，冻结候选4eb6928f055347afff8d32627af8aed5a94bab9795d10fbd63386ba02db94cf1。原始2FAIL/2PASS、候选4PASS，重复读取相同收据，游戏主文件未变，容器/临时执行镜像已回收。7已知调用/0未知、峰价估USD0.013317168，未用11次关闭；0新战斗/0QA模型调用/不应用。实际自主spawn0；Review另记，不作协作质量结论。

新增profile复用同一Runtime worker，未另写Agent循环；single/auto真实Runtime脚本夹具、旧numeric Runtime夹具通过（零外部调用）。最新Python216项（212pass/4既有skip）、React12及TS/Vite构建通过。分支feature/code-runtime-p2的dad2f5d已快进合入本机v1-business-acceptance；未推送本轮GitHub提交。P1旧报告、封存费用与旧启动器修改保留。

本机任务中心18783新增 `/code-repair` 页面，按冻结Hash/原生Review/独立SQLite测试receipt核对后只读展示真实补丁、测试、Agent说明与费用；启动器自动配置已完成case路径。中文手册第八节说明体验。原始材料与46份当时实现源码snapshot在 local-data/python-coding-d01-v1；摘要 research/evidence/python-coding-d01-20261008.json。

这是首次真实Python修复切片，不是完整P2/P3关闭：统一代码Task准入/恢复、代码类型独立Verification委托、第二个独立Bug及本地采纳/回退仍待实现。当前容器只用于受控自有故障；异常清理/恶意候选与耗尽负例待补，不作通用安全认证。

## 2026-10-08：P0/P1 任务中心实际交付，P2 预验证

《计划文档.md》已获用户批准实施。工作树 feature/task-center-p1（基线1a80359）实现与一次独立审查已结束，34a0df0/cbf0eaf快进合入当前 v1-business-acceptance；保留此前启动器/上下文修改与未跟踪研究原始包。尚未推送本轮提交。

新入口 `打开任务中心.cmd` / http://127.0.0.1:18783/tasks ，默认关闭新模型调用；统一 Task 关联 Config operation、冻结候选、批准测试、QA request、Job receipt 和历史报告，下载同源 JSON/Excel。旧8767 Coding历史入口及玩家营地不改。历史报告明确标记零新执行；中断 QA 显式沿原参数恢复，未知 Job 不重跑。审查五项重要问题均已复现修复，裁决/延后项见 research/evidence/task-center-p1-rulings.md。

用户明确授权 scope 133d9145...bf95 后，C-01倍率1.4→1.6/C-02拒绝Boss血量/C-03冲突值澄清在真实页面完成；合法候选交独立 QA 实际4场，两个配对都两版获胜，AV差值-300/11、-600/7，结构PASS、总体INC。7已知调用/0未知，输入30704（缓存9472）、输出787，峰价估USD0.007370832；未用3次关闭。账本/授权/首调用前harness参数修正amendment在 local-data/task-center-p1-v1，原scope未改。不扩大旧批次，不宣称总体改善或协作质量增益。

DockerDesktop/WSL已启动；P2工程预验证真实Git worktree/冻结Python补丁/独立重建/非root无网络只读容器完成：受控护盾故障FAIL，人工参考修复四项PASS，重复取同一Job receipt，0模型。镜像固定sha256:224fc522...a9。原readonly容器docker cp失败及unknown Job保留，新v2结果在工作树 local-data/code-sandbox-preflight-v2。不算Coding Agent自主修复或代码Verification完成。异常清理/恶意候选与资源负例/可移植安装待补，不开放任意代码。

本轮Python214项（210通过、4既有跳过）、前端11项与TypeScript/Vite构建通过；新增真实模型调用仅上述7次，战斗仅4场。中文使用手册第七节已补任务中心步骤。下一步P2/P3接真实Codex Python修复→代码QA纵向D-01，再D-02和P4本地采纳回退；完整计划未完成。

## 2026-10-08：研发工作台启动提示修复

复现原 CMD 命令无输出但 HTTP / 与 /api/status 均200，原因是脚本缺提示/浏览器入口，Uvicorn正常日志关闭。当前本机打开研发工作台.cmd 显示中文地址、模型默认关闭和启动提示，检查解释器/前端；检测已运行的同profile工作台时直接打开浏览器，避免重复启动。实际执行 CMD 已验证复用分支和中文输出，页面/状态200；未新增模型或战斗。修改当前仅本机，尚未提交/推送GitHub。


## 2026-10-07：GitHub 私密仓库交付

用户已明确授权上传两仓库并要求中文连接手册。GitHub 登录账号 theHerta27；沙箱最初误报无效，正常权限核实可用，已创建两个 Private 仓库。源码导航整理与精选研究源码/方法/摘要纳入提交，原始批量运行目录仍本地。旧游戏 origin 改名 local-baseline，GitHub 为新 origin。固定验证基线通过游戏历史 fdb9e838 还原到 local-data/verification-baseline，明确源文件换行可导致新字节身份，旧证据不复用；本机旧 checkout 不变，新机器不必克隆第三仓库。demo_v1 不再读取旧项目 .env，改用本机环境变量。203 tests（2 skip）与最终候选模块8 tests（1 skip）通过，独立基线 describe/create 通过。GitHub使用手册.md 记录安装与同步操作；两个仓库已成功 push main，GitHub API确认均Private；实际从GitHub clone后还原/安装固定基线，使用克隆源码完成describe/create与CLI help。克隆验收复用工作台既有解释器，未重新构建Unity/运行LLM，不冒充全新机器完整产品验收。详见research/evidence/github-upload-20261007.json。


## 2026-10-06：源码导航整理

工作台 Verification 主实现由 `qa.py` 移至 `verification/agent.py`，旧模块仅重导出 Decision/State/VerificationAgent，保持既有脚本兼容；CLI/工作台使用新路径。四个 Agent 目录新增中文 README，根 README 提供入口。此次只整理源码与说明，不改变业务流程、不重新执行封存模型实验，也不修改历史证据。Codex Runtime 仍为官方 SDK 启动的外部依赖进程，未复制 Runtime 源码。本轮显式 .venv 执行 unittest discover：203项、2项跳过，其余通过；新旧导入身份一致，CLI --help 与 git diff --check 通过。


## 2026-10-05：可直接演示的营地闭环

按用户“优先快速闭环，不扩复杂严谨度”的最新要求，本轮交付本机演示：React营地→真实LangGraph离线对话/玩家选择→世界支援→Unity实际按键→同规则结算→分享战报→角色记忆隔离。入口 http://127.0.0.1:8780/camp ，双击 `开始剧情演示.cmd`；中文步骤见[使用手册](使用手册.md)。研发真实历史结果仍在8767。当前演示NPC是明确标注的离线台词，0新增模型调用，不冒充真实DeepSeek自由对话。

Unity升级官方6000.3.21f1后，同原存档、UIA读取和Alt+F4退出已正常exit0；新键盘5项PlayMode/Player均通过，构建02完整封存。当前真实营地首场85条命令胜利：1条由原生Enter两次提交，其余84条由页面明确标注的固定策略完成；战报实际分享后岚知道、砾仍0来源记忆。不能将固定策略等同OS自动操作。新NPC4项unittest、前端8项测试与build通过。

本轮先保证正常展示，暂不扩分布式保障、完整故障矩阵、Electron和大型协作对照。NPC真实模型/代码build隔离Worker等仍待后续，四能力完整发布未宣布完成。下方早期失败/预算记录保留为历史，最新运行入口以上文及手册为准。


## 2026-10-05 M1 玩家现场与正式启动器：最新继续入口

- 续行中：Unity6000.3.21f1官方包签名/官方MD5/SHA256已核验，并列安装成功，旧19保留。一次准备导入正常退出且源码/包/DLL无改变；新root的EditMode2/2、PlayMode1/1已通过，Windows Player测试/产品构建/实际UIA后退出仍在验，尚不能称修复已验证。精确记录在game/local-data/unity-toolchain-6000.3.21和unity-live-6000.3.21f1-v1。
- 两个新增隔离实现：游戏`local-data/worktrees/m1-keyboard-ui`只改Hud/Client和键盘测试；工作台`local-data/worktrees/npc-agent-v1`只实现NPC领域/图/CLI，均未合并主仓。键盘前两次旧19 PlayMode因测试夹具关闭EventSystem而失败，不算业务TDD证据。M4世界HTTP前两次入口/脚本路径失败保留，v3真实2场（盾战胜、SP场固定短上限超时）和跨进程同收据恢复已运行；仍待最终审查/合并，不称完整NPC交付。

- 用户已完成破盾战技与丢响应重试。`graytower-game/local-data/unity-live-business-v1` 同一命令2次POST，原始请求字节相同，完整收据语义相同；SQLite为revision1/1命令/11事件。完整14全局字段/4单位组件与权威状态一致。用户截图保留，不能冒充自动战斗输入。
- 检查器首轮误把响应JSON键序作为字节身份，原失败保留；现比较完整字段/类型/数组顺序并拒绝重复key，新business-check-02通过。默认launcher使用D3D11，可选--evidence，默认关闭。父本轮定向37 tests通过，未重跑旧战斗/模型/引擎测试。
- Player单独重启读回成功，但探针90秒超时并回收，不算正常退出。正式CLI用逐字节存档副本实际启动，恢复同一状态；Alt+F4后Player exit0xC0000005，launcher正确报告失败并清理Host。Windows事件证实18:24旧Player、18:33正式Player均UnityPlayer.dll+0xc2ecc9。不能仅凭Shutdown日志断言正常退出；原C#和236文件构建未改。
- 原现场Host20868/子5664与代理6112/子30148已按完整命令/创建时间核对后回收，旧Player41724已退出；不再向用户请求同一轮手工操作。旧原始存档/日志保留。正式副本local-data/launcher-restore-v1，服务与Player当前已结束。其他工作台8765/8766/8767保持原样。
- 当前先定位退出崩溃；自动窗口采集持续超时，完整自动OS战斗输入、pending跨重启、胜负/分发仍待完成，M1/G0-U不关闭。NPC领域与图可独立推进。真实模型批次均已关闭，本轮无模型调用；最终完整手册用中文。
- 本轮报告：research/evidence/m1-player-interaction-20261005.md。旧M1引擎/runner记录仍在m1-game-unity-20261005与graytower-game/docs/evidence，历史seal不改。游戏当前提交18b2d00，本轮checker/launcher修改待独立收尾提交。
- 退出故障后续：两份已有dump直接定位PlatformAccessibilityManager清理时GetScreenManager为空，高度吻合官方UUM-146676；6000.3.21f1已修。官方包下载到game/local-data/unity-toolchain-6000.3.21，旧19不卸载，计划并列安装E:/Unity6/6000.3.21f1。新runner root为unity-live-6000.3.21f1-v1，保留旧attempt预算/记录；源码与同一rev1存档对照不变，再跑完整引擎及UIA后退出。仅省略显式UIA查询的控制组仍崩溃，不能声称该调用是唯一触发源。
- 下载期间并行M4.1：独立Git worktree `D:/Desktop/graytower-game/local-data/worktrees/m4-world-support`（branch同名、base18b2d00）由qa_next_acceptance实现版本化初态支援/SQLite世界收据/真实HTTP演示，禁止改主游戏仓/Unity/模型。范围和接缝见路线第6节新增实施包；完成后父审并合并，不把领域切片当NPC已交付。

## 2026-10-05 Coding真实验收与M1实施：最新继续入口

- 用户明确授权scope bd9ff502...e1c48后，真实单次批次成功交付：single/auto均只改1.4→1.58并原生Review；固定auto候选同A2A QA实际4场、两对均两版胜，AV分别减少100/7与600/7；结构PASS、总体INC。自主spawn0；另有2个原生Review子线程。不是多Agent质量或速度比较。
- Coding16＋QA4调用全完成，0未知，峰价估USD0.021308352；未用8次关闭，不重新执行本批。保留single首次LF/CRLF编辑失败与QA一处不支持的机制关联。功能完成不等于机制解释全通过；独立助手复核和原文在local-data/coding-runtime-demo-v1，33源文件保存在research/evidence/coding-live-source-20261005。
- 新CodingService/工作台接持久run、固定授权任务ID、独立Responses账本、已有完整receipt零模型收尾。默认web不开放收费Coding；缺完整receipt不重跑。原生Review不冒充QA。独立审查修了前端随机ID不匹配授权、导入crash后卡住两项。
- 真实页面副本local-data/coding-workbench-v1，http://127.0.0.1:8767（PID9360）；原记录不改、两候选可查，auto原确认和QA报告保留。浏览器已核文件任务→候选→原报告、390px无横溢出；模型均关闭。截图coding-desktop.jpg。199 Python tests（197pass+2既有skip）、8前端tests、TypeScript/Vite build通过。
- 已新建独立游戏repo D:/Desktop/graytower-game，源自旧fdb9e838...（旧路径仅未跟踪current_context，保持不变），branch m1-playable-session。新.venv Python3.11.9及Host依赖已备。qa_next_acceptance实现BattleSession/同Bot路径；workbench_api实现SQLite/HTTP Host；candidate_domain_v1做Unity隔离smoke。不要重复派工或覆盖并行文件。
- Unity6000.3.19f1已安装：受限用户首跑许可198；经正式审批的宿主用户许可可用，补齐非敏感Windows路径环境后真实UTF EditMode/PlayMode各1项PASS。Windows Player构建/运行仍在验；不把host smoke当受限代码Worker或产品完整引擎验收。
- 用户要求最终全部完工后提供简单易懂的**中文**使用手册，按实际全流程讲操作、结果、故障处理；现在不把未交付Unity/NPC写成可用功能。其他M2/M4/M5门槛继续。

## 2026-10-05 Coding 正式 Runtime：历史准备入口

- 已固定官方发布 openai-codex==0.160.0＋默认 CLI==0.160.0，独立 research/.venv-coding；主循环/原生子调度/Review 均复用，不改SDK。新增 single/auto 文件业务入口，原生只读MCP共享给子，主thread独占动态edit_text。namespace仅在DeepSeek边界无损映射，shared SQLite按全部父子/Review调用计额。
- CodingWorkspace导入完整实际文件与目录，绑定精确bytes/hash/diff、来源artifact和Review最终树；author=coding、kind=numeric_config，同A2A QA已扩准入；仍拒code/build。旧manifest环境drift保留，旧报告收据可读，不重封或放宽旧hash。
- 正式SDK probe最终3/3、本地脚本化产品single/auto分别5/10请求全链通过；actual auto创建1原生子，不能当真实DeepSeek或协作质量成绩。189 tests=187 pass+2既有opt-in skip；0新增模型/战斗。硬退出临时文件、Review/候选绑定、授权前领域漂移等审查问题已修；早期失败原样保存。见research/evidence/coding-runtime-integration-20261005.md/json。
- 新真实批次已准备、正在等待本轮授权：local-data/coding-runtime-demo-v1/outbound-scope.json，sha bd9ff50285c0757d777932617f3e1ce9d01648e1d90b08d82fcac598d70e1c48。single→auto，同需求功能验收后固定auto候选同QA；DeepSeek官方responses最多24次＋chat最多4次、4场、总USD0.85，保守USD0.743616。此前额度均关闭，不能沿用；未读key、无execution-started。
- 授权后命令：PYTHONPATH=src;tests;scripts、PYTHONUTF8=1；.venv/Scripts/python.exe scripts/run_coding_demo.py --data local-data/coding-runtime-demo-v1 --authorization-sha256 bd9ff50285c0757d777932617f3e1ce9d01648e1d90b08d82fcac598d70e1c48。运行前验证scope/source/SDK/领域/prepared；单次执行不自动重跑。所有实际失败/未知占额，完成即关闭未用额度。
- G0-C/M2尚未关闭，必须以真实模型业务演示结束。Coding页面、任意代码build worker、完整取消/Runtime跨进程恢复、Unity/NPC仍未完成。新的同任务双模式只是功能验收，不是效果对照；公平质量对照仍按原路线另用独立任务。

更新：2026-10-05，Asia/Shanghai。工作目录D:/Desktop/mihoyo-agent-project，已初始化Git（基线321ae64）。用户已批准进入实施，V1限定单机、本地服务、SQLite。旧游戏、旧Coding、Codex参考树、旧verification源码及封存实验保持原样。新产品CLI切片已实现并实际演示；四能力完整产品仍未完成。

## 2026-10-05 JSON 决定与 Config 首次确认：最新继续入口

- Config/Verification默认JSON mode。LangChain ChatDeepSeek公开generate保留全部choice；适配层严格拒绝多choice、非stop、截断、重复key、多个对象/数组/混合文本、非有限数和非法Schema。SDK length/filter抛异常时保存completion/usage，原始失败不丢；显式function_calling仅兼容选项，无自动fallback，无SDK fork。
- 用户授权master scope `8f1aaf8c5f795f35283dcbb7c0ddf6ef5709df68dc868630028e67cd90eb3ed3`，最多28次/USD1.10/0新battle。4次已知QA异常输入回放全部合法单决定，仅协议回归无工具；随后12题Config首次确认各1调用，4候选/4澄清/4拒绝。
- 独立开发助手逐题24项冻结标准复核12/12通过，父另跑冻结评分器核验；非盲非真人，不是总体成功率。全confirmation包15题为12 PASS+3合成QA解释NOT_RUN。c01预检/确认顺序文案含混保留为非计分可用性问题，不改原文或评分标准。
- 两个新账本16completed、0failed/unknown，0新战斗/确认/应用，峰价估USD0.018343908；未用12次关闭。原旧账本一律不复用。v1仅执行前准备，因代码审查修复改为v2；v2源hash/预览先封存授权，再执行，未依确认结果调参。
- 工程149 tests（147 pass+2既有opt-in skip）、pip check通过；前端无改动。真实候选只读副本工作台 `http://127.0.0.1:8766/`（PID见local-data/config-confirmation-demo-v1/web.pid），模型关闭，已读取首题1.4→1.48、待确认；原8765保留旧QA工作台。scope/关闭在local-data/json-config-acceptance-v2；原始回归在json-decision-regression-v2；Config观测/逐题复核在config-confirmation-v2。
- 完整报告research/evidence/json-decisions-config-confirmation-20261005.md及对应JSON seal。这个小步已完成，M3整体、QA新版全链、稳定Coding SDK/Runtime正式入口、Unity/NPC仍未交付。后续优先推进G0-C/Coding正式接入并复用同QA，在集成批次确认QA全链，避免反复追加同类窄示例。当前现场只读可展示，无收费任务待运行。

## 2026-10-05 React 工作台与新 QA 验收：当前继续入口

- React/TypeScript 工作台和 Starlette 同源 API 已落地，复用现有 Config/候选/A2A/MCP/独立 QA；候选确认、验证目标/预算、持久操作、程序事实/原错误/Trace 都可浏览器操作。入口 `http://127.0.0.1:8765`，当前以 `local-data/workbench-v1` 启动且关闭模型；启动命令见 README。Electron、Coding Runtime、Unity/NPC 仍未完成。
- 用户授权新两题到 DeepSeek 官方 chat/completions，仅 flash、8次/8场/USD0.40。初次离线容量测得双Trace超过18k，在任何调用前保留旧准备，改32k并重新授权；题目/评分不改。实际通过页面确认1.52、1.68候选并运行，共7次/8场，峰价估USD0.00663312、0未知。剩余1次已关闭，不补题或额外解释。
- 新两题独立助手逐句复核9条原始reason/29子句，语义目标均完成、未发现无依据主张。1.52样本7 AV不变、样本11减少600/7；1.68两样本减少2300/11、600/7，均两版胜。第二题实际读取两版本部分Trace、准确引用伤害并指出因果缺口。总体仍INC/结构PASS；固定2种子不证明总体收益，也不证明多Agent相对性能。
- 原wire两次违规给双Decision，LangChain当时仅取首个，故每题first_attempt_clean=false，不声称无故障通过。原账本/输出保留。新网关已先红后绿补恰好一条合法调用检查，保存raw/usage并拒绝多条；该修复尚未真实模型复测。原运行models/workbench分别保存在新批次live-models.py/live-workbench.py，另有live-source-hashes。
- 页面POST丢失后的永久等待、报告读取失败后刷新不重读已修；同ID/原内容重试不会另建任务。已准入请求允许在模型额度0时从已存决定/checkpoint收尾，未知Job无receipt仍停止。2题服务重启关闭模型后重放均0新调用/战斗，原报告不变。
- 最终132 Python tests（130 pass+2既有opt-in skip）、5前端tests、TypeScript/Vite build、pip check通过。独立代码审查发现的零额度恢复P2已复现修复。真实浏览器测试了窄屏/桌面、候选确认、报告/Trace、运行中刷新与已完成重读。
- 完整记录见 research/evidence/workbench-qa-20261005.md/json；原始新批次在 local-data/qa-independent-v1-32k，独立语义复核为 independent-review.json。下一步先解决provider单决定输出兼容并独立确认，再完成Config确认集/M3退出；原G0-C、M1/Unity、NPC路线不变，不扩生产部署。

## 2026-10-05 前次续验（历史记录）

- 本轮报告/预算/失败边界已修：中文显示胜→负/超时和无收据；已准入检查不可用交付INC；QA每次读取最新战斗/模型余量，额度耗尽正常停止；未知模型预留仍占额度。策略Schema明确枚举balanced/survival/basic_only，非法种子/策略/预算与无效模型输出分别诊断。
- 旧授权8次已用尽：从原6次精确字节账本续用2次，新QA实际4场，模拟成功后模型提出额外8场被拒，随后触顶；原报告错误不改。累计8完成/0未知，估USD0.004608756。不是干净验收。
- 用户另授权6个新Config开发需求＋固定dev-c01 QA，16次/USD0.50/最多4场。首轮Config6次，独立复核5/6；冲突值需求文案追问正确但status为rejected，按冻结needs_input标准失败。QA4次/4场：首次误将版本baseline/candidate当策略，被拒后改正；预算提示生效，读Trace后结束。模型只读candidate片段却声称确认倍率路径，解释仍计失败。总体INC/结构PASS，重复A2A委托0新调用/0新战斗。
- 修改Config通用状态定义后，用同批剩余6次对完整6题做一轮已知开发回归，每题一次、无新增战斗；独立助手复核6/6，不当独立确认，不覆盖首轮。新批累计16完成/0未知，66377输入（10112缓存）＋2356输出，峰价估USD0.019767372。两批调用额度都已用尽，不能再以本批授权追加模型。
- 首轮26源码/输入精确快照在local-data/config-development-v1/round1-source；上次b45c925的38源码快照在research/evidence/v1-implementation-source-20261005。旧91文件seal逐一核验未变；新代码/报告另封存，不改旧证据。
- 23题窄profile包已冻结：6+12 Config、2+3合成解释；当前只运行6 Config开发题，确认集和合成解释未收费运行。状态/关键词不自动给语义分，独立助手复核绑定原文/hash/理由并注明非真人。详见research/evals/config-qa-v1/README.md。
- 最终117 tests（115 pass＋2 opt-in skip），旧跳过项上轮已单独执行。Trace只读压缩真实974事件为19个/5978字符，保留hash/单版本部分视图限制；新模型效果未复测。原文件和新代码封存见research/evidence/v1-followup-20261005.json。
- 本轮结果和下一步见research/evidence/v1-followup-20261005.md。M3尚未完成：下一步用新的独立任务验证修复后的QA工具选择与证据解释，再把React页面接现有领域服务。Coding稳定Runtime、Unity真实测试/玩家输入与NPC世界链仍未交付；不扩生产级部署。

## 首次实施结果（历史，费用以顶部累计为准）

- 新Config为真实LangGraph＋LangChain DeepSeek结构化输出，确定性领域层负责Schema/范围/引用校验和冻结；支持击破手战技倍率1.4–1.7。Verifier独立LangGraph决策，经标准A2A接任务、MCP查候选/模拟/读Trace，候选只读。
- SQLite确认/不可变请求/Job receipt；同请求或同作业重放不重复执行。图checkpoint与完成receipt间硬退出跨进程恢复成功；running无receipt保留未知，禁止换参数绕重跑。未做多实例/OAuth/生产级outbox，也未实现跨revision自动优化总grant。
- 真实业务：Config生成1.4→1.7，确认后4场配对模拟，2个seed均两版本胜，AV均减少；总体INC。首跑MCP日志locals捕获闭包对象，receipt完成后返回失败；日志已修，真实MCP重放正常且0新battle，QA新增exact-operation receipt恢复。原4错误/报告不改。
- DeepSeek6次已完成/0未知，11297输入（3840缓存）＋1168输出；按峰价估算USD0.00366174，小于新授权USD0.50/8次。第6次是只读解释附录，出现seed11负AV被说成更长的质量错误；保留输出，程序中文report负责数值事实，草稿不可信为裁决，不刷更多调用。没有修复后收费完整新任务重跑，不把恢复/工程成功算首跑无故障。
- 父最终suite84项，82通过、2个真实战斗opt-in默认跳过；这2项已分别单独跑过4场领域、2场硬退出恢复。本轮已知实际battle共10（上述6＋live4），恢复重复0新增。新项目.venv依赖锁requirements-v1.lock.txt，pip check通过。
- 官方Hello World复现A2A终态再发问题，最新发布1.2.1及核对main尚有同路径；未改SDK/无fork。产品公开准入限制新Task/终态Get，cancel不支持。完整本机V1失败/限制见research/evidence/v1-implementation-20261005.md和对应JSON seal。
- 直接演示：`.venv/Scripts/python.exe -m agent_workbench.cli --data local-data/v1-demo report v1-live-demo`（需PYTHONPATH=src），无模型/战斗。下一步先扩展Config/QA独立需求评测与干净新任务端到端验收，再将React页面接相同CLI背后的服务；M3阶段尚未整体完成。之后Coding稳定Runtime及同QA接入、BattleSession/Unity、NPC按既定路线推进。

## 当前有效的产品边界

1. Coding：Codex Runtime＋官方Python SDK＋业务Adapter；保留主Agent动态0..N原生子Agent，按任务选择人数/分工，正式入口auto/single。旧规则/契约/反例1＋3仅benchmark，不固化；负面profile结果不取消原生动态功能。
2. Config：自然需求→schema/config/规则查询→结构化候选→确定性预检/diff→策划确认；默认不是自动数值优化。先冻结完整Manifest，再确认其hash，包含baseline/candidate/scenario/规则/schema及diff来源。
3. Verification：独立QA Agent，只读Author给定候选，理解意图、计划/执行检查、调查失败、核验证据、交付PASS/FAIL/INCONCLUSIVE；不修改候选。失败回Config/Coding，由Author产生新revision、新请求，延续总预算。
4. NPC：独立LangGraph＋LangChain，Memory/RAG/角色状态、多轮与合法世界行动；不因其他能力协作而拆多Agent。

只有Config→Verification、Coding→Verification两条跨产品边。一个标准A2A Card/verify_candidate能力，同一客户端schema；不造Config↔Coding。MCP是研发Agent→工具的复用边界，不把Verifier包装为verify_everything。内部程序节点可直调领域接口。成品LLM全部DeepSeek，包含Review/子任务/辅助；不要求当前开发助手更换模型。

## 前次架构审计完成与发现（历史记录）

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

## 架构审计时的下一步（已开始；以顶部最新结果为准）

按路线M3-A/B先交付Config生成/预检/确认→A2A独立Verification计划/调查→证据报告回Author。先trusted config，独立QA入口可选现有候选，不等待完整Unity；把协议/领域两条probe接成真实模型链还未做。产品实现前建Git、锁版本和输入/报告schema，接跨revision总grant、真正身份、持久Job与失败证据、工作台页面。

并行M1 BattleSession/真人输入/同规则复现、G0-C稳定SDK与动态Runtime、G0-U真实Unity。M2再接代码/build冻结候选到同一QA；M4 NPC接版本化世界支援；M5四能力独立入口与联合演示。旧三产品人日估计不继续当承诺。

Unity最终必须真实Editor EditMode/PlayMode、UTF Player tests、产品Player、OS输入、权威状态与进程回收；本轮未启动引擎。游戏尚是模拟/回放底座，完整可玩输入未交付。NPC拟120盾/各自3普通回合、SP+1二选一未实现。撤销默认5%/2pp/314160场；先描述性与机制检查，概率声明按独立pilot和业务/预算预注册。

## 历史冻结证据与费用授权

2026-10-04固定协作16开发＋28确认已结束，不重复启动。single/A+/parallel各14/14已知根因、0FP，完整证据9/14、10/14、8/14；四串并对Runtime墙钟少46.9%，非全产品端到端或质量等价。结果只适用于该profile。报告research/evidence/collaboration-evaluation-20261004.md；原始packet/oracle/manifest/wire/events/盲判seal保持原样。

共享账本352预留/350已知/2未知，峰价已知实耗＋未知预留USD1.022392；100万输出总cap内。用户明确授权仅六冻结公开包及Agent分析到DeepSeek responses、累计USD3，不能重置账本或扩展为新源码授权。本轮无收费调用；新真实模型批次先确定材料范围与总cap。

历史Verification16 tests、最终12正常＋4故障恢复、212场业务探索、检索结构探索；游戏181 Python/16纯C#，旧Coding206/13skip/167subtests及React24均按原日期引用。不是本轮全面重跑，也不能当四能力/引擎验收。详细证据与限制在VALIDATION_REPORT.md。
