# Unity 自动化最终交付门槛审查

日期：2026-10-04（Asia/Shanghai）。范围：独立审阅现行方案、路线、验证报告及旧 Unity 实现，核对 Unity 6.3 官方文档，提出交付合同；未改主文档或旧产品源码，未安装包、启动 Editor/Player、调用真实模型或读取许可/模型凭据。主文档引用使用章节与原文片段定位；旧源码保留此次审计快照的精确行号。

## 1. 必须落入主方案的结论

**Unity 自动测试是最终交付的必需能力。纯 C# 测试、离线 Python、历史 Player 回执、人工试玩均不能替代。** 最终链路必须真实运行：模型修改 Python/C# → 冻结候选 → Broker 授权与隔离执行 → Unity Editor EditMode/PlayMode → Windows Player tests → 构建可分发 Player → 独立 Player 的自动键鼠输入 → Python Game Host 权威状态核验 → 不可变证据 → 独立 Review → 人工采纳/发布批准。

自动化与人工审批不冲突：测试执行在已批准 profile 下自动完成；审批决定能否运行额外权限任务、采纳 patch 或发布。人工可以先配置合法 Unity 许可，或补充体验试玩，但不得在每次验收里替机器人点完一局再称自动闭环。

初审时必须修订的三处（以下引文来自修订前版本，不表示现版仍保留这些措辞）：

1. [总体方案](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md) 旧版第 9 节“Windows执行、依赖与交付”的“首版只提供手动引擎运行”只可保留为**诊断期间的临时工作方式**，不是最终接受条件。受限 Unity 无法运行时，G0-U 保持阻塞；M2 完整 Coding 闭环及 M5 最终交付不得完成。
2. [实施路线](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md) 旧版第 2 节“G0”的退出条件“Unity 链路通过，或标为阻塞”不能同时作为 G0 全部完成的退出条件。拆为通过的其他 G0 子项与未通过的 G0-U；允许并行做不依赖它的工作，不允许把被阻塞项折算成通过。
3. [总体方案](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md) 旧版第 7.1 节“产品流程与页面”的测试层级“EditMode/PlayMode 或 Player”应改为明确的 required profile；本项目跨 Python/C# 的最终代表任务要求各层齐全。[实施路线](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md) 旧版第 3 节“M1”的验收门槛“操作者用按钮选择行动并完成至少一局”可保留体验验收，同时增加自动真实输入一局，不能二选一。

建议最终布尔门槛：`delivery_ready = required_test_receipts_valid && real_editor_pass && player_tests_pass && fresh_player_build_pass && real_input_e2e_pass && authoritative_state_pass && isolation_pass && cleanup_pass && review_complete`。该门槛只允许进入 `ready_for_human`，不自动等同 `accepted/released`。

2026-10-04 复审记录：当前[总体方案](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md)第 7.1 节已明确跨 Python/C# 代表任务及联合 release 跑完整测试链路；第 9 节已明确真实 Editor/Player 自动测试、外部输入与 Game Host 对照、手工仅作诊断、不合格执行后端阻塞 M2/M5，并引用本报告的具体合同。未发现仍会允许最终交付降级的实质矛盾。实施时本报告关于禁用 Player batchmode、冻结前处理构建生成文件、同 revision 对照、清理与失效规则须随 referenced profile 一并执行。本次复审不包含正在由主控更新的实施路线。

## 2. 当前证据到底证明了什么

| 项目 | 本次可确认的事实 | 不足以声称的能力 |
|---|---|---|
| 现存版本 | [ProjectVersion.txt:1](D:/Desktop/combat-foundation/game-unity/ProjectSettings/ProjectVersion.txt:1) 固定 6000.3.19f1；此前本阶段只检查 Editor 可执行文件存在 | 未重新核验运行许可、Windows build support、受限账户兼容性 |
| 包与测试装配 | [manifest.json:2](D:/Desktop/combat-foundation/game-unity/Packages/manifest.json:2) 仅 physics/imageconversion/imgui/screencapture；本次只读枚举 Assets 下无 `.asmdef` | 没有已交付的 UTF EditMode/PlayMode/Player tests 套件；不能把 Editor 自带 UTF 误称项目已接入 |
| Editor 静态 harness | [test_showcase_editor.py:16](D:/Desktop/combat-foundation/scripts/test_showcase_editor.py:16) 用真实 Editor `-executeMethod ShowcaseRegressionTests.*`、退出码和 PASS 标记；[CombatV2RegressionTests.cs:11](D:/Desktop/combat-foundation/game-unity/Assets/Editor/CombatV2RegressionTests.cs:11) 操作真实场景组件、typed readback 与错误 trace | 有价值的真实引擎历史测试，但不是现成 NUnit XML 套件；不覆盖 live HTTP 输入 |
| 真实构建 | [CombatReplayBuilder.cs:38](D:/Desktop/combat-foundation/game-unity/Assets/Editor/CombatReplayBuilder.cs:38) 调用 BuildPipeline，校验 Succeeded，生成 build_id/版本/GUID 回执 | builder 会生成/修改 scene、material、PlayerSettings；必须在隔离工作区运行，不能对用户正打开的工程直接执行 |
| Player 历史验证 | [unity_v2_acceptance.py:39](D:/Desktop/combat-foundation/scripts/unity_v2_acceptance.py:39) 包含真构建、Player trace readback、独立复制目录与截图 | 本轮未重跑；旧 Player 读取离线 trace，没有待建的 Game Host 实时会话 |
| 控件 smoke | [ShowcaseSmoke.cs:30](D:/Desktop/combat-foundation/game-unity/Assets/Runtime/ShowcaseSmoke.cs:30) 直接调用 TogglePause；42 行 Restart；55 行 SelectSample；64 行截图 | 不是 OS 输入，不证明 EventSystem/按钮命中/焦点/键鼠到 HTTP 命令的链路 |
| 子进程管理 | [unity_acceptance.py:31](D:/Desktop/combat-foundation/scripts/unity_acceptance.py:31) 直接 Popen；42 行按自己 PID 调 taskkill /T /F | 这是历史进程所有权处理，不是安全隔离，也没验证 Codex command/exec 内部的回收行为 |
| 本阶段已跑 | [验证报告](D:/Desktop/mihoyo-agent-project/VALIDATION_REPORT.md) 第 3 节“本次实际运行的实验”V01/V02：181 Python、16 纯 C#；该节“V01—V04证据”说明历史 929 事件/200 holdout 仅 hash 核对 | 未新增一次真实 Unity 自动运行；16 项不是 EditMode/PlayMode；不能把“本机有 Editor”写成 G0-U 通过 |

本次补充只读检查：读取上述源文件；枚举 `game-unity/Assets/**/*.asmdef` 无结果；`git -C D:/Desktop/combat-foundation status --short` 仅 `?? current_context.md`，与既有审计一致。命令附带用户 Git ignore 路径读取权限警告，未读取或修改该配置。此次没有新增“测试通过”数值。

## 3. 官方约束与正确命令形态

### 3.1 固定版本与 UTF

Unity 6.3 手册把 UTF 列为随 Editor 分发的 core package；该版本包入口指向 1.6 系列，用户手册已迁到 Unity Manual。实施时记录 **6000.3.19f1 实际解析的包版本与 packages-lock.json**，不要从网页的最新补丁推断本机已经安装/接入。[Unity 测试介绍](https://docs.unity3d.com/6000.3/Documentation/Manual/test-framework/test-framework-introduction.html)、[6.3 包说明](https://docs.unity3d.com/6000.3/Documentation/Manual/com.unity.test-framework.html)

UTF 的 `EditMode` 在 Editor 编辑模式运行，`PlayMode` 在 Editor 播放模式运行，`StandaloneWindows64` 则构建并在 Windows Player 中跑 PlayMode tests；后者不等同可分发产品的真实输入验收。`-testResults` 输出 NUnit XML；`-runTests` 不支持附带 `-quit`。`-runSynchronously` 会过滤多帧 UnityTest，不能为省事全局添加。Player heartbeat 默认 600 秒，仅是心跳等待而非总作业上限。[UTF 命令行参考](https://docs.unity3d.com/6000.3/Documentation/Manual/test-framework/reference-command-line.html)

以下仅是**待实现 Broker 参数模板**，`{...}` 是受信任 profile 解析后的绝对路径，不是本轮执行记录。Broker 使用 argv 数组，不接收模型拼接 shell 文本；所有输出目录先由 Broker 创建成当次唯一目录。

```text
{Unity.exe} -batchmode -projectPath {isolated_project}
  -runTests -testPlatform EditMode
  -testResults {run_dir}/editmode.xml -logFile {run_dir}/editmode.log

{Unity.exe} -batchmode -projectPath {isolated_project}
  -runTests -testPlatform PlayMode
  -testResults {run_dir}/playmode.xml -logFile {run_dir}/playmode.log

{Unity.exe} -batchmode -projectPath {isolated_project}
  -runTests -testPlatform StandaloneWindows64 -playerHeartbeatTimeout 120
  -testResults {run_dir}/player-tests.xml -logFile {run_dir}/player-tests.log

{Unity.exe} -batchmode -quit -projectPath {isolated_project}
  -buildTarget StandaloneWindows64 -executeMethod CiBuild.BuildWindows
  -logFile {run_dir}/build.log
```

`CiBuild.BuildWindows` 是建议新增的受审查构建入口，不是已有类；它接收被验证的 run_id/output path、固定场景/后端/profile，输出 BuildReport 摘要。真实入口也可从旧 CombatReplayBuilder 演进，但不能继续把离线回放场景当 live 产品。Unity 支持命令行 build/profile 或 executeMethod；BuildPipeline 返回 BuildReport，应校验 summary.result 并记录 errors/warnings/产物。切目标必须在正确编译目标下完成，不能只改 BuildPlayerOptions 后假设条件编译符号已更新。[命令行构建](https://docs.unity3d.com/6000.3/Documentation/Manual/build-command-line.html)、[BuildPipeline.BuildPlayer](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/BuildPipeline.BuildPlayer.html)

Editor 同工程不能双开；batchmode 异常可返回 1；完整日志须落文件。`-nographics` 不初始化图形设备，只给明确无需图形的 profile；`-quitTimeout` 默认 300 秒用于 quit 等待异步任务，不是通用 job timeout。测试模板故意不加 `-quit`。[Editor CLI](https://docs.unity3d.com/6000.3/Documentation/Manual/EditorCommandLineArguments.html)

独立产品 Player 的真实输入阶段**不能带 `-batchmode` 或 `-nographics`**：Unity 官方明确 Player batchmode 不显示画面且不接受用户输入。按窗口模式、固定分辨率启动，记录 GPU/图形 API/DPI/焦点与 Player.log；不能把 headless 成功冒充点击成功。[Player CLI](https://docs.unity3d.com/6000.3/Documentation/Manual/PlayerCommandLineArguments.html)

### 3.2 退出码、XML 与成功判定

官方明确各 Unity 被测组件没有统一退出码定义，应结合错误与堆栈定位；故不硬编码“某个非零值一定仅代表测试失败”。[UTF 命令行参考](https://docs.unity3d.com/6000.3/Documentation/Manual/test-framework/reference-command-line.html)

以下是本项目自己的严格门槛：必须有本次进程完成记录、预期正常退出、新目录中的完整 XML、预注册测试 ID 实际被发现且执行、required tests 全通过。零测试、全 skipped/inconclusive、XML 缺失/截断/旧 run_id、进程超时，即使 exit=0 也不得 PASS。发现编译失败/引擎崩溃时分类为 compile/infrastructure failure；有有效断言失败时为 test failure。不能用日志中单个 PASS 文本代替以上判定。

XML 本身一般不含我们的候选 hash，所以由外部 Broker 的 envelope 绑定 `candidate_hash/run_id/test_profile_hash/actual_test_ids/xml_sha256`；不能要求 Unity 自动生成它未承诺的字段。每层默认禁止自动 retry-until-green；一次基础设施重试须新 attempt_id，保留首次失败并可见。构建成功另需新 BuildReport、产物完整性及真实启动，不以旧 exe 仍存在代替。

### 3.3 许可、包下载与项目锁

Editor 需要已激活许可。Unity Personal 激活/返还走 Hub；不能通用地承诺通过传 username/password/serial 自动激活所有许可。CLI 激活还涉及许可文件目录可写。许可配置属于操作者/管理员的环境准备步骤，模型不得读取或接收凭据。[许可方式](https://docs.unity3d.com/6000.3/Documentation/Manual/LicenseActivationMethods.html)、[CLI 许可管理](https://docs.unity3d.com/6000.3/Documentation/Manual/ManagingYourUnityLicense.html)

G0-U 明确检查：合法许可在**实际 runner 身份**下可用，Windows build support、Test Framework、UnityWebRequest 相关模块、图形设备和必要包均就绪。不能在候选执行时临时开放全网下载安装。可信准备阶段下载/锁定依赖，候选阶段按批准的网络权限运行；许可服务所需访问、UTF Player 连接与 Game Host loopback 必须分别验证，不能因为“网络受限”把这些路径也意外切断。

每个 task/attempt 独立工作树、Library/Temp 与输出目录；同一个 Unity project path 串行排他执行。锁带 owner PID/start-time/job generation，启动前识别占用，不能删除正在运行项目的 UnityLockfile 或结束操作者的 Editor。只有确认拥有者已退出并完成对账才释放 Broker 锁。可复用经过版本/包/候选映射校验的缓存，但缓存不是可共享写入的第二工作区。

## 4. 最终自动链路及其权限合同

| 阶段 | 必需自动行为 | 受信任判定与证据 |
|---|---|---|
| A 任务与候选 | 真实 Coding 模型读游戏仓库并修改 Python/C#；任务独立 worktree；至少覆盖 Python 缺陷、Unity 消费缺陷、跨契约“战前支援护盾”三个代表任务 | 记录实际 provider/model、task/turn/tool、基线/完整 diff/hash；缺陷若人工注入必须明示；fixture 可开发调试，不算最终模型验收 |
| B 冻结与授权 | 停止写候选；Broker 解析固定 profile/argv/路径，核验工作区、权限与预算后派发 | 候选 hash 与请求、审批、profile 绑定；开始测试后代码再变则失效重跑；模型不能自行扩大执行范围或修改通过标准 |
| C 快速层 | Python 规则/契约与纯 C# 快速测试 | 用于早反馈，失败则早停；通过后仍进入真实引擎层 |
| D 真实 Editor | fresh import/compile、UTF EditMode 与 PlayMode | 新 XML、测试 ID/计数、日志、版本；覆盖 DTO/资源/场景引用/组件生命周期/事件消费/重连/错误展示；不得只有 DTO 镜像测例 |
| E Player tests | UTF StandaloneWindows64 构建运行 Player tests | 验证目标平台/运行时/程序集差异；独立 XML/日志；与产品包构建分开记账 |
| F 产品构建 | 从冻结候选构建实际 live 游戏场景，打包锁版本 Python Game Host sidecar 与内容 | BuildReport、build_id、完整文件 hash、Game Host wheel/内容/schema hash；复制到新的运行目录，脱离源代码工程启动 |
| G 自动真实输入 | 外部可信 harness 找到该 Player 的窗口、确认焦点和布局，产生实际 OS 键鼠输入完成选择/行动/结算等 | 自动操作须经过 Player 自己的输入/UI→客户端命令→loopback HTTP；输入时间线、窗口/PID、视频/截图、Player 收包/显示记录 |
| H 权威核验 | 从 Game Host 的受限只读观测获取已接受命令、revision/event sequence、权威 snapshot；读取真实 Unity 场景 typed 状态 | 将对应 revision 的 UI/组件状态与权威投影比较；将**实际玩家命令日志**投入同候选 headless 规则重放，核验规则事件/终态/RNG；另用批准 Spec 的独立断言防止两端同错 |
| I 收尾封存 | 停止 Player/sidecar/测试子进程；确认无遗漏进程和端口；外部 Broker 汇总并封存 | 完整/失败证据都保留；cleanup 未验证不能完成；封存后候选无写权限，hash 可核查 |
| J Review/采纳 | 独立 Reviewer 读 diff、有效证据及失败记录；用户决定采纳或拒绝 | `findings=[]` 合法但需结构化完成、候选 hash/范围；采纳/发布批准绑定当前 envelope hash，修改后旧审批不可重用 |

Broker 执行服务与模型/业务服务分进程、无模型凭据，独立配置/数据目录，不加载用户插件、MCP 或登录；启动环境先清理，再配置继承规则。`command/exec` 请求 env 的 merge 语义不是环境白名单。Candidate code、Unity 编辑器扩展/测试/static initializer 都是执行面，固定 exe/argv 不能代替 token/ACL/网络限制。权限测试要从实际 Unity/Player/C# 子进程内部验证，而不仅从 PowerShell 外壳验证。

测试 oracle/profile/审批服务不在模型可编辑范围；候选自己输出的 PASS/JSON 只是待验证材料。Broker 控制独立输出路径、实际启动与退出事实、测试计划及最终封存；正常产品运行不能自己写 `accepted`。这提供可追踪的工程验收，不宣称能够从不可信进程自报数据证明任意恶意代码绝对正确。

旧 builder 会写 scene/material/PlayerSettings，迁移时应把这些确定性生成步骤移到候选冻结之前，或将明确生成目录按受审查 profile 单独建模并绑定输入/产物 hash。测试与构建前后检查受版本控制的源码、资源与设置指纹；未计划的变化使结果失效。Library、Temp、日志等可写产物不能混入 source hash，也不能借“Unity 会自动改文件”豁免实际代码/场景变动。

### 4.1 真实输入与权威状态的最低覆盖

输入自动化推荐一个很小的受信任 Windows harness，以 Win32 SendInput 产生鼠标/键盘事件。它仅操作登记 PID 对应窗口、固定允许控件/坐标，记录注入数量与响应；不向模型暴露任意桌面控制。Microsoft 说明 SendInput 受 UIPI 限制，只能注入相同或更低完整性级别目标；因此焦点、窗口、桌面会话和实际 runner 级别都属于 G0-U 实测，不能靠 API 存在推断成功。[SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

真实输入要求指程序化 OS 输入通过正式 UI 路径，不要求真人替自动化操作。允许仅用于观测的控件位置/可用状态/typed scene 导出；不允许主验收 harness 直接调用 OnClick/SelectAction、给 Game Host POST 行动、直接写 HP 或预置完成 trace。准备场景可走可信测试 setup，进入被验收步骤后行动必须经输入路径。

最低场景：

1. 一局正常胜利与一局失败，操作技能、目标及“使用/跳过终结技”，观察 UI 提示与权威结果；保存输入/命令时间线。
2. SP 不足/非法目标：按钮状态与错误说明正确；若命令被提交也必须由 Game Host 拒绝，状态/RNG/revision 不产生不该有的变化。
3. 重复请求、迟到响应、事件重复/缺口：用可信网络故障 fixture 施加故障，正式 Player 执行输入；权威只执行一次，显示不回滚到旧 revision。
4. 中途 sidecar 断连后恢复；明确暂停/重连 UX；继续时拉取正确快照，不能靠 Player 推算规则。
5. 保存/退出/重启后恢复同一决策点，实际输入继续；headless 重放实际已接受命令得到相同规则结果。
6. 新“战前支援护盾”从 UI 可观察，来源/持续回合与权威事件一致；至少含旧 Scenario 默认兼容和一个错误新输入负例。

先比较同一个已消费 revision 的权威投影与场景状态，不能把网络延迟期间的不同时间点直接比较。每个输入等待可观察前置条件，超时明确失败；不靠固定 sleep 的总时长作为已操作证明。画面证据与 typed readback互补：前者证明可见交互，后者证明量值；最终受信任 Spec 断言仍须独立于候选实现。

## 5. Windows command/exec 限制与 G0 失败后的有界处理

### 5.1 已知边界

参考源码 [command_exec.rs:178](D:/Desktop/codex-main/codex-rs/app-server/src/command_exec.rs:178) 的 WindowsRestrictedToken 分支拒绝 tty/streaming，184 行拒绝非默认 output cap；199 行存 UnsupportedWindowsSandbox，203 行独立 spawn 并等待 execute_env；[437 行](D:/Desktop/codex-main/codex-rs/app-server/src/command_exec.rs:437) 明确拒绝 write/terminate/resize。**协议具有 terminate 方法不等于这个 Windows 分支可用。** 参考树和已装 alpha 不是同一构建，最终必须按锁定版本实测。

第一实现可以是有限时长 buffered job，不要求流式 stdout，但必须真实兑现最迟停止时间。取消模型 turn、断开 RPC、关 UI、请求超时均不能作为“Unity 已停止”凭据。UI 应显示 `cancel_requested → stopping/awaiting_deadline → terminated_and_reconciled`；超出清理时限为 `cleanup_failed`。在途资源存在时不删除 worktree、不启动冲突的新 Editor、不标业务完成。

### 5.2 G0-U 的试验和失败升级预算

建议把下面预算写入路线，作为实施控制而非声称已测出的性能：

1. **首轮固定矩阵**：一个真实最小游戏工程/测试集和锁定 CLI；先成功 Edit/Play/Player tests/构建/图形 Player 输入；再跑权限拒绝、强制超时、断连、子进程残留、项目锁。首次包准备单独记账，不混入测试耗时。
2. **至多两轮定向修复、累计不超过 G0 预留 2 个工作日的 Unity 兼容排障预算**。仅处理具体许可身份/路径 ACL/依赖/图形/loopback 配置；每轮换 attempt_id、重跑受影响正例及权限负例。不能循环无上限重试或逐渐放宽成全权限。
3. **若失败仅在进程生命周期**：执行一次有范围的最小 Windows runner/窄 Rust 补丁实验，建议另限 1 个工作日并显式登记决策。目标是让可信 supervisor 拥有受限进程 Job Object/句柄，保留原 token、ACL、网络限制，证明超时/断连时整组 owned processes 回收。不是增加新的模型循环。Job Object 可统一管理/终止进程，kill-on-close 可用于宿主失败回收；它本身不施加安全 token，子进程 breakaway/其他创建方式还要验证。[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
4. **仍不通过则 G0-U=BLOCKED，停止该 profile 自动执行**，保留失败证据和专用目录；不给 M2/M5 完成标记。架构决策只能选择继续实现可隔离的原生后端，或另立有期限的专用 Windows VM/runner 实验（仍须合法许可、图形桌面与同一验收合同）。没有经过验证的可运行后端就没有最终自动交付；手测/纯 C# 不是第三条成功路径。任何新增基础设施安装、许可或权限变更须依实施授权范围办理。

该预算意味着“有界诊断后作明确阻塞/路线决策”，不意味着到了日历期限即可免除用户要求。M1 可继续完成不依赖该 Broker 的领域逻辑和界面；不应把 G0-U 未解决藏到最终联调。

### 5.3 每个作业的终止合同

建议初始 profile 上限：预备导入/产品构建各 15 分钟，EditMode/PlayMode 各 5 分钟，UTF Player tests 10 分钟，单个产品 Player E2E 场景 5 分钟；进程回收额外最多 30 秒。它们是待真机校准的初值，首次锁定后写入 profile hash，操作者可显式调整预算，模型不得自行延长。

这些上限由可信宿主/runner 计时，不能只写在 Unity 测试里；测试卡在静态初始化时也必须生效。普通用户取消可在 buffered 已批准上限内等待，界面明确剩余最大等待；若交付要求几秒内停止，则当前分支不满足，必须先完成上面的窄生命周期能力，不能宣称“有取消按钮”等于达标。高危权限探针异常时应立即停止派发并使用已验证宿主回收手段，不等待长构建自然结束。

清理验收需确认 owned process group、Player、Python sidecar、编译子进程和占用端口已回收，且与本任务无关的 Editor/Hub 没被杀。不能用 `taskkill /IM Unity.exe`。Unity Licensing Client/缓存等共享服务要有明确所有权分类：不能因名称像子进程就全杀，也不能允许任务继续借共享服务写工作区；验证实际需要保留的服务作用域与无残留作业。

## 6. 必须注入并保留的负例

| 负例 | 应有结论/证据 |
|---|---|
| C# 语法或缺模块导致编译失败 | compile_failed；没有有效测试 XML 也不能空集 PASS；原始 Editor 堆栈保留 |
| EditMode、PlayMode、Player tests 各注入一个断言失败 | 三层均能独立阻断；显示失败用例/stack，不以最终模型文本覆盖 |
| filter 错误导致 0 tests、required test 被 ignore、XML 缺失/截断 | validation_incomplete/failed；拒绝绿色回执 |
| 把旧 XML/旧 build_receipt/旧 Player 复制入新 attempt | hash/run_id/候选绑定不符而拒绝；文件存在和 mtime 不足以通过 |
| 候选改动后引用旧结果或旧批准 | 全部相关收据/审批失效；重新冻结、验证、审批 |
| Editor 或其测试代码 hang，并派生 child/grandchild | 到 hard deadline 后全部 owned 作业回收；记录 cleanup 时间和无残留证明 |
| UI 取消、RPC 断开、执行服务崩溃、Broker 重启 | 不谎称已停；恢复先对账，不自动重放未知副作用；清理未证实则 blocked |
| 工程已被 Editor 打开、同工作区第二作业 | 排队或明确 project_locked，不能删锁或终止无关 Editor |
| 许可不可用、构建模块缺失、包解析/图形失败 | environment_blocked；不回退全权限、不降级手测通过；不记录账户密码 |
| 从实际 Unity C# 尝试任务外写、读取凭据诱饵、外连、启动越权子进程 | 在批准边界被拒绝；使用合成诱饵，绝不读真实密钥；失败即隔离不合格 |
| Player 输入未命中/失焦/UIPI/窗口最小化或会话不可用 | input_environment_failed 或业务超时，不能直接调用 action 方法补过 |
| 按钮错绑、UI 状态旧、丢/重复/乱序事件 | 真输入的期望命令/权威 revision/typed 显示不符，E2E 失败 |
| Game Host 返回错误版本、重复命令或断线重试 | schema/幂等/revision 契约生效，无重复扣资源/推进 RNG/奖励 |
| 候选只伪造画面/typed state、无真实权威命令 | 外部 Game Host 命令收据与实际 headless 重放断言失败 |
| cleanup 失败、输出截断/磁盘满、未知进程状态 | 不封存为 passed，不开放采纳；保留隔离目录和人工处置入口 |

允许开发时把故障注入测试本身判为“预期拒绝行为通过”，但被注入的业务 run 仍显示 failed/blocked，不能把负例测试通过与产品功能通过混成一张绿色卡片。

## 7. 阶段落实与最终验收清单

**G0-U** 交付可复现的 engine runner、固定权限/环境/profile、真实 Editor 与 Windows Player 最小正例、回收/隔离负例以及全部日志。纯 API/fixture 验证不能退出 G0-U。

**M1** 交付 live Game Host+Player，真实 UI 输入自动化、权威状态/命令重放和重连存档测试；真人试玩是补充体验检查。G0-U 可并行研发，但依赖它的自动化退出条件未通过时必须标明未完成。

**M2** 把三个真实模型代表任务经过上述完整链路；任务影响范围可以帮助开发阶段选择快速测试，但三个最终代表任务不得只跑 Python 或纯 C#。跨契约任务必须触及真实产品 Player 与 sidecar；提交无结构化 review、证据过期或 cleanup 失败均不能进入待采纳。

**M5** 对锁定最终 release 再跑完整自动链路；至少一次全新输出/工作区（可使用已预备的可信依赖缓存）和一次普通重复运行，核验可复现与不会读旧产物。演示包在独立运行目录启动，无源工程/Editor 依赖；自动化构建验证环境本身仍需 Editor。保留成功与必需负例证据，声明确切测试版本/范围，不声称任意平台普遍兼容。

最终证据包最低包含：基线/候选/工具链/包锁/profile/oracle hash；实际模型调用元数据与工具事件（脱敏）；每层请求与进程起止/退出码/超时/清理结果；UTF XML 与实执行用例清单；BuildReport 与 Player/sidecar 全包 hash；独立 Player 输入记录、视频/截图、typed scene readback；Game Host 已接受命令、revision、权威快照与 headless 比较；失败尝试；Review；与当前 envelope 绑定的人工决定。

**当前状态结论：** 本报告完成文档与源码核对，确认可行的官方自动化入口及不可忽略的 Windows 限制；没有把待实现流程当作运行成功。真实 UTF 集成、受限 Broker→Unity、自动 OS 输入→live Game Host、超时整树回收及完整模型修改链路全部仍待交付。上述任一 required 项缺失，都不得宣称“Unity 自动测试链路已完成”或“项目最终交付已完成”。
