# 游戏底座与 Verification Agent 独立核查

核查日期：2026-10-03。范围为材料阅读、源码核查与离线技术验证；未改原项目产品源码或配置，未读取真实密钥、未调用真实模型、未启动 Unity Editor/Player。本报告的“推荐”属于下一阶段设计，不能当成已实现功能。

## 结论

推荐保留 **Python 唯一规则核心 + Unity 客户端**，把现有完整自动模拟循环提炼为可暂停在决策边界的 BattleSession。人类输入、Bot 输入和录制命令复现都调用同一核心；无头批量模拟也通过该会话推进。现有基础足以支撑“三人小队对三阶段首领”的可玩切片，首阶段的价值是玩家真正做决定、状态可保存与复现、Unity 与无头运行一致。当前 Unity 是可信的事件播放器，尚不是可玩的游戏。

Verification Agent 值得保留：它已有模型选择动作、澄清、锁定 Spec、候选修正、独立角色评审、预算与证据链，不能描述成单纯固定流水线。其目前的产品范围仍是“受限数值配置调整”，验证方法和种子/策略集合被 host 固定，尚不能承担完整策划/QA 验证规划。后续应扩展领域验证工具、需求到指标的可审查转换、独立保留集与统计解释，而不是先换一个 Agent 框架。

不推荐首阶段迁移 C# 规则。可玩需求并不要求规则必须在 Unity 进程内；当前 Python 规则、69 项 v2 核心回归、确定性 trace 和历史验证链条有直接价值。C# 纯规则库是合理备选，但需要重新验证分数运算、取整、随机数、阶段边界和双运行时兼容；目前没有证据证明这笔迁移成本能优先改善三个 Agent 的业务闭环。

## 1. 版本与证据口径

已完整阅读 `mihoyoJD.md`、`PROJECT_BRIEF.md`、旧项目 README/current_context/AGENTS，再沿启动入口、核心、工具、Unity 和测试核查。

| 项目 | 本次事实 |
| --- | --- |
| 仓库 | `D:/Desktop/combat-foundation` |
| HEAD | `fdb9e8387af696482bf2b57d1543484f8b08495c` |
| 最新提交时间/主题 | 2026-09-28 22:36:06 +08:00；`docs: record final acceptance and verified local delivery` |
| dirty | `?? current_context.md`。与该文件所写“工作区干净”不同；是现状变化，不影响已提交实现指纹。 |
| 实际 Python | 3.11.9；使用仓库已有 `.venv/Scripts/python.exe` |
| Unity 项目版本 | 6000.3.19f1，revision `7689f4515d75`；[ProjectVersion.txt](D:/Desktop/combat-foundation/game-unity/ProjectSettings/ProjectVersion.txt:1) |
| 当前 Player | `game-unity/Builds/CombatReplay.exe` 存在；本次只核查文件与历史回执，未重新运行。 |

`git status` 有读取用户全局 ignore 文件被拒的警告；本地仓库状态、HEAD 与本次检查的受跟踪源码指纹均成功读取。

**本次实测：** Python 181 passed / 47.61s；C# 播放控件 16 passed；18 场新模拟，9 组相同输入重复 trace 完全相等；历史 27/27 源文件指纹、7/7 回执哈希匹配；最终验收的 75 个任务各自的 artifact/hash-event/checkpoint 校验全部通过。

**历史声明且本次核验相关存档：** 75/75 真实 Provider 任务、4/4 组对照、200 场保留集、Unity 基线 1017/候选 929/旧版 365 事件一致。来源为 [交付验收](D:/Desktop/combat-foundation/docs/AGENT_DELIVERY_ACCEPTANCE.md:1) 和 [摘要](D:/Desktop/combat-foundation/docs/evidence/agent-delivery-acceptance.json:1)。75 个任务实为 25 个固定案例各重复 3 次，不是 75 个独立场景；[案例](D:/Desktop/combat-foundation/scripts/agent_v2_cases.py:10)、[运行器](D:/Desktop/combat-foundation/scripts/agent_v2_acceptance.py:140)。最终 handoff 复用了原 200 场，不能重复计数。

本次的哈希核验说明文件与既有记录一致，不证明历史模型调用身份，也不等于重新构建/运行引擎。没有重新运行 605 场历史核心验收、75 次模型任务、200 场保留集或 Unity 实机。

## 2. 底座已经有什么

| 能力 | 源码事实与位置 |
| --- | --- |
| 完整模拟 | `simulate(bundle, scenario)` 从初态运行到胜负/超时，玩家决策由两个 Bot 函数直接调用；[simulation.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/simulation.py:21) |
| 回合/行动值 | 用 `Fraction` 表示时间、速度和剩余行动距离；同时间按玩家/敌人、slot、ID 排序，死亡单位不行动；[scheduler.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/scheduler.py:4) |
| 三人队伍 | 合同固定 3 人，每人普攻/战技/终结技；当前元素为物理/火/雷；[contracts.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/contracts.py:10)、[队伍校验](D:/Desktop/combat-foundation/game-core/combat_core/v2/contracts.py:154) |
| 资源与窗口 | 普攻恢复 1 战技点，战技消耗 1 点，上限 5；终结技仅自身普通回合、正常行动前且满能量开放，每回合至多一次，释放后仍可普通行动；[合同](D:/Desktop/combat-foundation/game-core/combat_core/v2/contracts.py:91)、[动作合法性](D:/Desktop/combat-foundation/game-core/combat_core/v2/effects.py:129) |
| 伤害/生存 | 直接伤害、暴击、防御减伤与取整；治疗、净化、护盾 FIFO 吸收/刷新；资源溢出记录；[effects.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/effects.py:175) |
| 弱点/击破 | 只有匹配弱点才削韧；击破伤害、行动距离增加 2500、打断蓄力；敌方下次行动恢复韧性；[effects.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/effects.py:189)、[boss.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/boss.py:31) |
| 状态 | modifier、DOT、control，叠层/刷新、攻击快照、持续回合、净化与控制免疫；[effects.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/effects.py:81) |
| 三阶段首领 | 基线按 100%/70%/35% 生命切阶段，韧性 300/360/420；第二阶段召唤、第三阶段蓄力并控制免疫；有狂暴、召唤上限 2 和溢出时 fallback；[phase state machine](D:/Desktop/combat-foundation/game-core/combat_core/v2/boss.py:8)、[敌方动作](D:/Desktop/combat-foundation/game-core/combat_core/v2/boss.py:52)、[baseline](D:/Desktop/combat-foundation/configs/combat/v2/baseline.json:1) |
| Bot | balanced/survival/basic_only 三个确定性策略；读取当前状态，不读取未来或自行取随机数；[bots.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/bots.py:1) |
| 可审计 trace | 闭合的事件 payload schema；每事件完整 `state_after`、事件因果 ID、AV、随机数抽取、config/scenario hash、Python/规则/policy/RNG 版本；[trace.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/trace.py:7) |
| 指标 | 从 trace 派生胜负、胜利局 AV、阶段完成耗时、击破、伤害、能量、护盾、控制；比较时保留逐 seed 配对、胜负迁移与 win→win AV 差；[report.py](D:/Desktop/combat-foundation/game-core/combat_core/v2/report.py:34) |

这些机制足够构成玩家易理解的选择：现在消耗战技点治疗，还是保留击破角色技能打断下次蓄力；优先处理召唤物，还是压首领阶段。第一版不需要扩成开放世界、自由移动或实时战斗。

### Unity 的准确边界

启动时创建几何舞台，读取完整 JSON trace，再逐条将 `state_after` 写入 typed Unity 组件并导出回读；C# 不计算伤害和规则。[启动入口](D:/Desktop/combat-foundation/game-unity/Assets/Runtime/CombatReplay.cs:42)、[事件消费](D:/Desktop/combat-foundation/game-unity/Assets/Runtime/CombatReplay.cs:145)、[typed 状态](D:/Desktop/combat-foundation/game-unity/Assets/Runtime/CombatStateV2.cs:25)。这能验证“Python 状态正确传入并保留在引擎组件”，不能证明玩家动作、网络/session、规则在客户端重新计算都正确。

HUD 当前只有基线/候选切换、暂停、重播、倍速与退出；没有技能/目标选择。[ShowcaseHud.cs](D:/Desktop/combat-foundation/game-unity/Assets/Runtime/ShowcaseHud.cs:130)。启动场景由 Builder 生成，未来手工场景和 NPC 营地不能沿用自动覆盖场景的方式而不调整入口；[Builder](D:/Desktop/combat-foundation/game-unity/Assets/Editor/CombatReplayBuilder.cs:1)。

Packages manifest 当前只有 physics/imageconversion/imgui/screencapture，未声明 UnityWebRequest 或 Unity Test Framework；[manifest](D:/Desktop/combat-foundation/game-unity/Packages/manifest.json:1)。选择 HTTP bridge 后需显式补验证联网模块；采用 EditMode/PlayMode 正式测试前需补测试框架。现有 Editor 回归是自定义脚本，16 项控制测试是独立 C# 可执行测试，均不能冒称已有完整 Unity Test Framework 覆盖。

## 3. 从回放升级为可玩：推荐的规则与接口边界

将现有 `simulate` 的顺序逐步提炼，不重新写第二套结算：

1. 规则包负责 `create_session`、推进自动阶段、返回当前观察和合法动作、接受一个命令、产出事件、保存/恢复会话。它不依赖 Unity、模型或 HTTP。
2. 人类、Bot、录制脚本只提供 `ActionRequest`。Python host 验证轮到谁、技能所有权、资源、目标和版本，再调用现有效果/阶段逻辑。Bot 批量模拟也调用这条路径。
3. Unity 展示权威观察，在 `awaiting_player_action` 显示技能、可选目标、能量/SP、行动顺序与首领蓄力提示；发送命令后禁用重复输入，播放返回的事件批次，到下一个决策点再开放输入。
4. 本机启动器启动规则 sidecar 与 Unity Player。建议先用 loopback HTTP 的版本化 JSON 命令接口，按动作拉取事件批次；回合制首版无需持续高频推流。随机端口/会话令牌、启动就绪检查、超时、进程退出与关闭清理由 host 负责。传输协议本身不携带规则计算。
5. 原完整 trace 保留作证据与历史回放；live 会话按命令返回增量事件和决策边界快照，避免每次传整场多 MB trace。需要断线恢复时按 `last_event_seq` 拉取未消费事件并检查 revision。

接口至少需要：`session_id`、`command_id`、`expected_revision`、`actor_id`、`skill_id`、`target_ids`；返回 `accepted/rejected`、权威 `revision/state_hash`、事件 seq 范围、公共观察、`legal_actions`/不可用原因、终局结果。合法动作由 host 派生，客户端不能用禁用按钮代替权威检查。为跳过可选终结技而进入普通动作应有明确命令或阶段转换。

### 当前不能直接拿 BattleState 当可恢复存档

- [BattleState](D:/Desktop/combat-foundation/game-core/combat_core/v2/state.py:60) 有 `rng_count`、当前 actor 和动作标志，但没有 `rng.getstate()`、明确待决策子阶段、事件 seq/recording cause、命令去重表或 session revision。`simulate` 内部局部变量还掌握当前循环位置和终局判断。
- [随机入口](D:/Desktop/combat-foundation/game-core/combat_core/v2/effects.py:40) 使用 `random.Random.random()`；`rng_count` 是抽样次数，不是可直接 `setstate()` 的状态。虽然可由 seed 重放已有命令重新生成状态，但目前没有该恢复入口；也没有保证随机算法或规则版本变化后还兼容的迁移策略。
- 快照应只在定义好的命令/决策边界生成，包含 rule/config/scenario 版本与 hash、BattleState、RNG state 及格式版本、待决策阶段、事件序号和命令幂等信息；恢复后必须先验证版本/完整性。首版支持同一构建恢复，跨版本先明确拒绝。
- Python 官方提供 `getstate/setstate` 支持恢复；其随机数可复现保证有兼容 seeder 等条件，不能据此推导整个游戏跨版本必定一致。[Python 官方 random 文档](https://docs.python.org/3.11/library/random.html)
- 当前事件快照包含内部信息，不应直接给 NPC 当知识。需要独立 `PublicObservation`/角色可知投影；不向 NPC 暴露 RNG 内部状态、未来 Bot 行动或其他玩家存档。

**一致性验收**应包括：同一命令序列分别在人类录制、Bot、无头回放路径得到完全相同的终态与规则事件；在终结技前/后、阶段切换、DOT 致死、蓄力、召唤边界保存后恢复仍一致；非法/重复/过期命令不改变状态与 RNG；Unity 实际技能按钮输入能驱动权威核心并回读一致。当前已有非法动作原子性测试，验证 SP 不足时状态、随机数和事件均不变化：[test_effects.py](D:/Desktop/combat-foundation/game-core/tests/v2/test_effects.py:54)。它已包含在本次 181 项实测中，因此未另写重复测试。

### Python 与 C# 的选择

| 方案 | 推荐与取舍 |
| --- | --- |
| Python 唯一规则 + 本机 sidecar | 首选。最少丢失现有可信行为；Python 编排/规则工具直接复用；规则与可视化隔离清楚。代价是交付要带受控 Python 环境/打包产物、两进程生命周期与 IPC。其启动、打包、实际 Player 输入延迟仍需首阶段实测。 |
| C# 纯规则库 + Unity/独立 headless 共用 | 如未来明确要求无 sidecar 独立 Player，或实测 Python 批量性能不足，再迁移。核心不引用 UnityEngine，需同时覆盖 Unity 支持的 API profile 与 headless runtime；不能把任意 .NET 8/10 DLL 当作 Unity 可直接加载库。Unity 官方说明可用 API profile 和 managed plug-in 兼容范围；[官方文档](https://docs.unity3d.com/6000.0/Documentation/Manual/dotnet-profile-support.html)。 |
| Python/C# 同时维护两套结算 | 不采用。协议相同不等于规则相同，长期数值/随机/取整漂移难排查。若迁移 C#，Python 只作冻结对照实现，完成差分验收后 C# 才成为唯一生产权威。 |
| Unity 专属物理/帧循环承担规则 | 当前回合制业务没有必要。会让自动验证依赖引擎进程，削弱短迭代、可复现与工具复用。 |

迁移真的发生时，要在同一命令/随机序列语义下做全量差分；先明确 `Fraction` 的替代（精确有理数或定义好的定点规则）、浮点 JSON 到分数的规则、取整方向、MT19937/seed 映射或新版显式 PRNG。若改变语义必须提升规则版本，不能悄悄把历史 hash/evidence 解释为新核心结果。

## 4. Verification Agent：真实能力与边界

### 已有闭环

授权 → 模型选 `clarify/set_spec` → 锁定 Spec → 提议候选 → 四层验证 → 固定场景对照模拟 → 模型读取观察/证据并选择修正或评审 → 独立 Reviewer → host 限制最终建议 → 人工决定。核心循环在 [loop.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:98)。动作只有八类；[models.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/models.py:61)。

模型有实质选择：是否澄清、如何将需求写成 Spec、在哪些已授权数值上提出什么候选、工具顺序、读取哪些证据、根据 FAIL 修改什么、何时结束。它不只是填参数；历史 R01 有根据真实失败报告从 1.81 改为 2.7 的修正证据。但它不能新增规则、改代码、选新测试工具、自由选择采样计划或选择用户操作。

确定性 host 承担：字段 whitelist、授权/Spec 交集、数值边界、schema/reference/rules/safety 四层检查、模拟、指标判定、预算、证据权限、review 引用核验。授权只允许至多 10 个字段，默认平台边界为基线 ±50%（零值 ±0.25）；[policy.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/policy.py:27)。候选从基线副本产生，始终不覆盖基线；[tools.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:66)。

`run_simulation` 不接受方法参数，必跑授权 seeds × policies × baseline/candidate；初始能量、SP、上限使用 `Scenario` 默认；[tools.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:79)。因此“Agent 选择验证方法”是待扩展能力，不能将当前固定模拟描述为已具备。

### 值得保留的权限和恢复设计

- 预算在模型/候选/模拟副作用前扣除并落盘，错误不返还；[loop.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:33)。
- 模型没有 shell、任意路径读写、baseline 写入工具；证据读取只能用任务可见 ref；[tools.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:46)。
- Reviewer 是不同 prompt/调用的同一 Provider 模型；其数值 claims 要能解析当前候选的 JSON Pointer、值必须相等；accept 不能覆盖 Evaluator FAIL；[tools.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:106)。
- 明确授权与最终人工决定仍是必要边界，审批只记录候选采用意愿，不应用配置；[loop.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:160)。后续若增加“发布配置”，应是另一个只对指定 hash 的显式动作。
- evidence 是本机 append-only artifact + hash 事件链 + 最新 checkpoint 与预算账本核对；[evidence.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/evidence.py:69)。它不是外部签名或多人鉴权。

恢复仅支持 `awaiting_input` 澄清任务；崩溃中断的 `running` 不恢复，[loop.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:148)。当前 `.lock` 在硬退出后可遗留。新 Web 任务服务需要区分 cancelled/failed/interrupted、任务租约与清理、工具幂等键、持久进程/作业状态和恢复策略；不应直接把 CLI 内存对象挂到 HTTP 后宣称完成服务化。

### 当前质量、统计与业务缺口

1. **需求到指标的正确性不完全可由 host 校验。** 程序能验证格式、授权和 required_criteria 不能删，却不能自动证明自然语言中的所有目标都进入 Spec。模型可能漏写或弱化目标；历史验收已有此失败。需要面向策划的“原句→字段/指标→允许变化”可审查表，明确未映射项与冲突。用户已明确数值时直接执行，不为流程额外澄清。
2. **固定基线、小样本和固定策略限制外推。** 默认 3 seeds、2 policies、最小样本 3；[models.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/models.py:31)。历史 50-seed 保留集在两个策略上，baseline/candidate 都是 50/50 胜，胜率指标已经饱和。应加入困难度、起始资源和机制边界场景，而非只增同一简单基线的 seed。
3. **当前 PASS 是描述性门槛。** Evaluator 自己标记 `statistical_significance_tested=False`；[evaluator.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/evaluator.py:6)。胜利局耗时会受胜负样本构成变化影响；当前先要求足够 win→win 配对，再比较各自全部胜利局分位数，并非只在同一配对子集上计算分位数。应明确报告全体胜负变化、同配对胜利耗时与阶段完成率，避免生存者选择偏差。
4. **采样规划还不存在。** 探索可见 seed 多次调参容易过拟合；保留集现在是脚本独立执行，并未纳入 Agent 产品工具/状态流。新增分层场景矩阵、固定封存保留集、置信区间与预注册停止规则后，证据不足要返回 INCONCLUSIVE。模型可以在已授权实验菜单与预算内选择追加验证，但不能在看到结果后删除失败 seed。
5. **同 seed 不保证同一随机事件配对。** 当前只按顺序消费 `random()`；候选改变击杀/状态次数后，后续随机抽样对应事件可不同。现有配对在“同 seed+policy”层面成立，不能声称所有关键暴击完全相同。后续评测需要记录此语义，必要时设计按事件键的独立随机流并提升规则版本。
6. **Reviewer 不是独立统计裁判。** 相同模型的两次调用可能共享偏差；claims 检查只保护结构化数值，自由摘要仍可能误解。有效动作率也不等于需求达标率、工具效果或可靠性。新评测应分别度量需求映射正确、越权拦截、目标完成、工具经济性、证据引用与人类可理解性，并设置未见措辞/组合的测试集。
7. **取消与资源限制粗粒度。** active_seconds 在循环/每场前检查，不能硬中断一次阻塞 Provider 或单场模拟；当前也未记录整轮 token/费用硬上限。独立受控 worker 应负责硬超时、取消与资源上限；模型的预算理由不能代替进程约束。
8. **业务入口只覆盖数值。** 机制逻辑变更应由 Coding Agent 出产受审查代码版本，再由 Verification Agent 针对该版本跑回归/场景/差分。不要给 Verification Agent shell 权限来模糊两个产品职责。

## 5. 推荐主场景、用户流程与展示

**主场景：策划调整“三阶段守卫”第二阶段节奏，同时保护第三阶段打断与生存体验。** 示例需求：“第二阶段太拖；允许第二阶段韧性在 288–360 内调整，希望 balanced/survival 的已完成配对阶段耗时中位数至少降低 5%，整场胜率不得下降；先按 288 试验，未达标请解释，不改其他阶段。”这是推荐场景，不保证当前基线数值恰好满足；实施时预先测定成功、无法达到和副作用三个 fixture。

策划看到结构化目标与授权范围；Agent 先做字段/机制合法性，再选小批对照观察耗时、阶段完成率、击破与召唤频率。若发现节奏没改善，则定位阶段事件与策略行为，提出范围内新候选或解释约束不足；不能通过偷偷降低验收线结束。QA 可查看种子矩阵、失败样例、事件时间线和可复现命令。封存候选进入独立保留集；最终报告展示 diff、目标/保护项状态、副作用、样本限制与可点击的重放证据，交给用户决定是否发布。

关键页面：任务/授权与 Spec；候选 diff/实验选择；运行中事件和预算；结果矩阵与双方同步回放；review/人工决定。第一阶段先交付可玩游戏，现有 CLI 仍可验证候选；这些页面和 Agent 新工具属于后续 Verification 产品阶段。

对应 JD 主能力为职责 1 的规划/工具/状态与评测，职责 3 的自动测试/配置生成，职责 4 的策划需求抽象，职责 5 的调试/回放/观测，职责 6 的边界/质量。与 Coding 的真实代码更改和 NPC 的玩家交互形成互补，不以三个聊天框替代业务产品。

## 6. 保留、重构、归档与首阶段

| 处理 | 内容 |
| --- | --- |
| 保留为实现基础 | v2 合同/规则/效果/首领/Bot/报告，已有边界测试、trace 对比器、四层校验、授权与证据协议、真实历史失败案例、Unity typed 状态/事件展示和 Player 构建验收方法。 |
| 重点重构 | `simulate` 到逐步会话；会话公共状态/存档/RNG/命令与增量事件；Unity live 输入/事件批次适配；Python sidecar 启动与打包；后续把 Agent CLI 划分成任务服务与领域工具。 |
| 后续替换产品体验 | 几何舞台与 IMGUI HUD 可保留调试模式，正式演示需清楚的技能目标选择、行动顺序、蓄力/击破反馈与结算。不要一开始引入大规模美术系统。 |
| 归档不删除 | 1.0 核心/workflow 与旧协议回归、UE 草稿、冻结旧 `game-change-verification-agent`。新任务只走明确的新入口；历史证据保持原文件/hash。待新版稳定后缩小旧版维护范围。 |
| 不纳入首阶段 | C# 规则全面迁移、UE 扩展、自由探索世界、Agent 新框架重写、多人大服、实时帧同步。 |

**第一个可交付阶段：可玩的单场战斗与同规则无头复现。**

- 固定现有三人、三阶段首领、技能与元素；提供玩家普攻/战技/终结技和目标选择、行动顺序、资源与关键事件提示，能完成一局并重新开始。
- BattleSession 与 Bot simulate 共用推进代码；定义保存/恢复、非法/过期/重复命令、取消、sidecar 崩溃的行为；不改变旧规则语义。
- 单一 Windows 启动入口负责就绪、进程与日志；准备无需用户手动开多个终端的分发包；打包依赖与首次启动实测作为验收项。
- 运行旧 181 项回归；增加有意义的会话边界、录制命令复现、断线/存档恢复测试；至少覆盖终结技、蓄力打断、阶段切换、召唤、DOT 致死等分支。
- 真实构建并启动 Unity Player，实际玩家按钮动作触发 Python 权威状态；录制该局命令，在 headless 重跑得到相同终态/事件，Unity 回读一致。录屏/截图只能说明表现，不能代替状态校验。
- 留一个明确失败演示：过期命令或进程断开后 UI 进入可恢复状态，不重复扣 SP、不悄悄伪造成功；成功与失败均产出证据包。

本报告没有实现 BattleSession、IPC 或新增 Unity UI，也没有验证打包和输入延迟；这些是首阶段明确待完成的工作。

## 7. 本次离线实测与复现

输出均位于 [game-verification-evidence](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence)。核心结果为 [audit-results.json](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence/audit-results.json:1)，测试日志为 [pytest.log](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence/pytest.log:1) 与 [JUnit XML](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence/pytest-results.xml:1)。

### Python 回归

在 `D:/Desktop/combat-foundation` 执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  --basetemp 'D:\Desktop\mihoyo-agent-project\research\game-verification-evidence\pytest-tmp' `
  --junitxml 'D:\Desktop\mihoyo-agent-project\research\game-verification-evidence\pytest-results.xml'
```

结果 **181 passed in 47.61s**，exit 0。按 JUnit 实际条目统计：旧核心 32、v2 核心 69、旧 Agent 20、v2 Agent 40、契约一致性 20，总计 181。Provider 相关测试使用 mock/fixture，不会调用真实模型；契约测试含人工构造的引擎输出，不能因此宣称本次引擎测试通过。临时文件与 pytest 输出定向到 research，禁用了 bytecode/cache 写入原仓库。

### C# 控件

执行 [run-controls.ps1](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence/run-controls.ps1:1)：复用现有 `ShowcaseControlTests.cs`、`ReplayOptions.cs`、`ReplayClock.cs`，只把原脚本的输出路径改为 research，使用本机已安装 Unity 自带 Roslyn/.NET runtime 进行编译和执行。结果 **Showcase control tests: 16 passed**，exit 0；[日志](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence/controls.log:1)。没有启动 Unity 引擎。

### 确定性与存档核验探针

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'D:\Desktop\combat-foundation\.venv\Scripts\python.exe' `
  'D:\Desktop\mihoyo-agent-project\research\game-verification-evidence\audit_probe.py'
```

[探针源码](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence/audit_probe.py:1) 只导入现有规则与 EvidenceStore：

- baseline，seeds 7/11/19，balanced/survival/basic_only，每个组合运行两次，**18 场实际新模拟、9/9 组完整 trace 相等**，输入配置全部未变。
- 首遍每场模拟 0.17393–0.29449 秒，完整 canonical JSON 2,368,474–3,236,031 字节，817–1030 事件；该测量包含 trace 生成，不包含进程启动、JSON 序列化、网络和 Unity，不能当 live 延迟基准。完整 trace 的 SHA256、每场指标与耗时保存于结果 JSON。
- 本次 balanced/survival 共 6 组都是 win；basic_only 3 组都是 loss。这验证了不同策略会影响结果，也说明胜率保护需要更丰富场景才能评估边界。
- 历史 source fingerprint **27/27** 匹配；acceptance/contrasts/unity/holdout/final_handoff/Python test log/integration 共 **7/7** 回执 SHA256 匹配。
- 最终验收目录 **75/75** 任务 EvidenceStore.verify 通过：45 `ready_for_human`、15 `awaiting_input`、15 `rejected`。校验读取各任务 manifest/indexed artifacts/events/checkpoint，并核对本地 hash 链与预算；没有重跑 Provider。

尚未验证：Python sidecar 分发、玩家动作往返、决策边界快照恢复、增量流断线续传、跨构建复现、真实新 Player 输入与 UI、统计计划/新机制测试工具。现有证据能够支持保留底座和设计方向，不能替代这些新功能的验收。
