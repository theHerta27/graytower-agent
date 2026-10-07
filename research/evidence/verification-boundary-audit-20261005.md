# Verification 职责边界审计

日期：2026-10-05（Asia/Shanghai）。审计者：独立源码审计子任务。本文依据本轮新要求：Coding 产出 Candidate Change，保留 Codex 动态原生子 Agent；Config 从自然语言、schema/config 产生 Candidate Config，经确定性检查和 diff 交策划确认；Verification 只验证上游冻结候选，失败证据回 Author；NPC 独立。新要求优先于旧文档。未修改旧树、现有 src、测试或封存实验，未新增模型调用。

结论：旧服务包含可复用的领域校验和证据机制，但其服务职责是“配置作者＋实验＋评审闭环”，不能直接改名为独立 Verification。当前 LangGraph 切片改善了批准和恢复边界，却仍在 worker 内构造候选。应将作者功能迁往 Config，把 Verification 收敛为冻结输入的执行、证据及结果服务；现有数值实验暂作适配器参考，不代表代码候选验证产品已完成。

## 事实、判断与待验的使用方式

- **事实**：从本次读取源码可直接确认，附路径和行号。旧历史结果标明日期，不算本轮重新执行。
- **判断**：按本轮四能力边界作出的归属及迁移建议，不声称已有实现。
- **待验**：代码或历史样本尚不足以证明的能力，作为后续验收条件。

本次完整读取了 combat-foundation README/current_context、两树 AGENTS、旧服务根层与 v2 的全部运行模块和 prompt，以及当前 verification 全部模块和 test_verification.py。定向阅读旧边界/Loop/交付回归测试、旧交付验收、当前验证报告、恢复 probe 及原始结果。没有按 README 的历史成功数推断新的四能力已完成。

## 旧实现究竟在做什么

| 事实 | 精确依据 | 对新边界的判断 |
|---|---|---|
| README 明写 Game Change Agent 理解需求、Spec、候选及下一动作，Reviewer 独立审查；“Tuner 暂未增加”是没有单独命名组件，不能理解为没有自动调候选 | [README](D:/Desktop/combat-foundation/README.md:48)，[current_context](D:/Desktop/combat-foundation/current_context.md:5) | 旧包名 verification-agent 不等于其职责仅验证。不得按目录名照搬能力归属 |
| 根层 WorkflowService.create 调 RequirementAgent 后保存 candidate/diff/validation；RequirementAgent 直接将模型 changes 应用到 baseline | [workflow.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/workflow.py:56)，[agents.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/agents.py:68) | 需求理解与候选生成迁 Config。它们并非 Verification 的独立检查 |
| 根层 run 遇 review=repair 会计算 0.9×韧性或 Boss ATK，并 apply_changes 后继续循环 | [workflow.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/workflow.py:168)，[quality_review.md](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/prompts/quality_review.md:6) | 明确违反新的“验证失败只能回 Author”。从新默认路径淘汰固定 repair 动作，不删除历史源码/证据 |
| v2 set_spec 首次设置后锁定；同一 Loop 可反复 propose_candidate，每次从 immutable baseline 建候选，并替换 current_candidate；原候选 artifact 保留 | [tools.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:30)，同文件 66–72；[policy.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/policy.py:59) | 这是受控 Author 的自修，而非写坏原基线。迁移后由 Config Author 创建新 revision，Verifier 不能持有该工具 |
| 模拟、校验、review 摘要经 context/observations 返回 game_change 调用；prompt 明确要求根据 FAIL 修正候选 | [loop.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:45)，同文件 98–110；[game_change.md](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/prompts/game_change.md:3) | 整段自主优化 Loop 降为显式授权实验。Config 默认完成用户指定修改、确定性检查、diff 和确认即可，不能把模糊“调整配置”当自动搜索许可 |
| v2 Reviewer 是独立 prompt/调用，同一 Provider；它不执行工具。返回 claims 要引用当前候选 diff/Evaluation，host 逐项核验 JSON Pointer；accept 不能覆盖 Evaluation FAIL | [tools.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:106)，[verification_review.md](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/prompts/verification_review.md:1) | 保留“解释与事实核对”的模式，但它只是可选解释层；不等于独立服务、独立模型训练或多用户权限隔离。自由文字不受 claims 完整约束 |
| 原最终人工 approve 仅记决定，不改 baseline；根层 accepted/rolled_back 同样注明 baseline_overwritten=False | [loop.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:160)，[workflow.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/workflow.py:210) | 保留人工采纳与应用分离。不要把历史状态名 approved_candidate/rolled_back 说成部署、回滚已实际完成 |

旧 Author 需求理解已积累可迁移经验：中文名称和稳定 Identifier 对照、精确 baseline 值与类型预览、百分比参数约束和效果指标分离、原始需求不能擅自添加验收阈值，见 [game_change.md](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/prompts/game_change.md:5) 第 5、9、22–26 行。这些属于 Config 能力设计输入，不代表旧工具已经能通用检索任意 schema/config。旧 context 只提供特定战斗 baseline、catalog 和授权字段；新 Config 的 schema 查询、跨表依赖和选择适用版本仍待实现。

## 保留的确定性领域能力与限制

**事实：** v2 [policy.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/policy.py:90) 区分 schema/references/rules/safety 四层；授权范围、字段白名单、有限数值、平台上限由代码判定。`apply_changes` 深复制 baseline，不直接写文件。`validate_spec` 不允许扩大授权或删除 host required criteria（38–50 行）。[evaluator.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/evaluator.py:6) 按锁定指标计算 PASS/FAIL/INCONCLUSIVE，少样本/无配对胜利等返回不确定，scope 明确为 descriptive_authorized_sample、statistical_significance_tested=False。

**判断：** 保留确定性校验、领域 diff、结果指标计算；抽离为游戏领域库/适配器，Config 可做预检、Verification 可独立复检，双方共用版本化规则。`apply_changes` 只归 Author/Config，Verifier 可计算实际 diff 作校验，但不能应用变更。数值白名单、最多 10 项、±50% 是这个战斗域的编辑政策，不是 Coding Candidate Change 或所有游戏的通用约束。旧 TaskSpec 强制至少一个 acceptance criterion（[models.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/models.py:53)）不应迫使“只改指定字段”的 Config 自动发明效果目标或必跑优化实验。

**待验：** 保留“确定性 Evaluator”不等于所有需求已有可计算 Oracle；结构合法、行为符合验收、样本效果、人工采纳需要独立结论。旧 AV p50/p90 使用胜利局分位数之比（evaluator.py:21–25），当前 report 使用共同胜利对的耗时比中位数，两者不可用同一名称混报。效果结论必须说明配对集合、输/超时分母和样本范围；现有证据不能证明总体非劣或玩家体验改善。

## 当前切片的边界缺口

| 事实 | 依据 | 重构要求 |
|---|---|---|
| ExperimentPlan 冻结的是 request、changes、bounds、seeds/policies 和 game_fingerprint，没有完整 Candidate artifact 引用、预期 candidate hash 或 Author/revision 关联 | [contracts.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/contracts.py:33) | 用冻结 Candidate＋验证请求契约替代“待应用 changes”。同一候选可有独立验证请求；产生新候选必须由 Author 创建新 revision |
| worker 从磁盘读取 baseline/scenario，构造 legacy Authorization/TaskSpec，再在第 75 行 apply_changes；validate/execute 都会重新构造 | [combat_worker.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/combat_worker.py:53) | 即使函数完全确定，也混入了作者职责。Author 提前物化并冻结完整 baseline/candidate/scenario；Verifier 只加载、校验并执行，不导入/调用 apply_changes |
| 源指纹覆盖旧 combat_core、整个旧 verification_agent 包及 baseline/scenario；执行前后核对。结果另带 candidate/baseline/scenario hash | [combat_worker.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/combat_worker.py:17)，同文件 92–97 | 保留版本钉住，但把 artifact 输入 hash 与执行代码/适配器/环境版本分开。当前输入并没有上游预期 candidate hash；不能仅凭结果自报 hash 宣称跨服务候选身份已证明 |
| Store.complete 调 build_report 后提交；build_report 核对 plan hash/game hash、精确配对集合及有效 outcome/AV，不要求 candidate/baseline/scenario hash | [store.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/store.py:103)，[report.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/report.py:9)；测试 receipt fixture 第 32–34 行只需 rows/game/plan | 当前可信 worker 范围有用，不能外推为可接受任意远端 worker。新完成收据须绑定已批准的 candidate、baseline、执行 profile 和 evidence refs |
| 校验失败会抛异常；generic failed result 被简化为 `game validation failed`，CLI 仅输出错误和 no automatic retry；领域表没有失败 evidence 或返回 Author 的关联 | [workflow.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/workflow.py:28)，[__main__.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/__main__.py:35) | 失败也要不可变结果/收据：失败层、复现条件、输入 hash、logs/trace refs、原始错误与 Author/revision。禁止错误分支直接生成 candidate+1 |
| worker 只接受受限数值，固定 module/process，过滤模型凭据；无完整 Trace 落盘，仅摘要/trace SHA | [combat_worker.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/combat_worker.py:1)，34–44、87–97 行 | 保留可信 numeric 适配器；不能称代码沙箱或完整调试证据链。必要失败 Trace/日志需可读取 artifact，不仅有无法打开的 hash |
| `GamePort` 只有 validate/execute 一个具体适配器；CLI 人工 JSON、approve/reject/show/resume，没有模型计划、A2A、异步 Job 或工作台 | [contracts.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/contracts.py:62)，[__main__.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/__main__.py:12) | 降格表述为“本地可信数值实验切片”。Coding 代码/build candidate 的冻结工作区、依赖、编译/测试隔离、日志收集等要另验；NPC 不接入该修正闭环 |

## 授权、预算与恢复应怎样继承

**旧事实：** v2 [loop.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/loop.py:33) 在 model/tool/candidate/simulation 副作用前扣账并 checkpoint；失败调用也扣。Authorization 封顶调用数、候选数、模拟数、输出 token/次、active_seconds（[models.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/models.py:31)）。[evidence.py](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/evidence.py:71) 核验 artifact、事件链、最新 checkpoint 与 budget event totals；resume 只允许 awaiting_input，provider identity 不可切换（loop.py:23–29、148–158）。旧根层则在 create 中先生成候选，之后 authorize 的 scope 明确包括 bounded repairs（workflow.py:73、88–115）。

**当前事实：** [store.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/store.py:58) 对 request ID/payload 冲突拒绝，批准绑定 plan hash 且决定不可反转；claim 用 SQLite 事务先记 running/charged，再 execute；已完成相同收据复用；非 new attempt 无自动重试。OS 文件锁保证本地同目录单 driver，进程死后自动释放（11–34 行）。LangGraph 仅路由/暂停，领域账本拥有批准和结果；resume 本身不批准（[workflow.py](D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/workflow.py:37)）。

**判断：** 保留这些失败保守性与回执对账模式；明确三个不同决定：Author 编辑范围/预算、Verification 本次执行预算、策划最终采纳/应用。当前 `approve` 是实验授权，不是策划确认 Candidate Config 已应用。新验证权限只授予读取已冻结候选与执行指定检查，不授予修改候选；收到失败的 Author 若需要新候选，应在原 grant/预算账本下走新 revision。

**待验：** 当前账本只有 request_id，换 request 可新开额度；旧新建 task 也可重新获得一套计数。二者都没有跨修订总预算/并发共享额度。调用次数×每次输出 cap 也不是完整输入 token/金额预算。当前 CLI 无身份鉴权、actor/approval 审计契约、持久 Job 协议、fencing、取消对账或未知作业查询。旧 Evidence2.1 的文件 hash 链是本地完整性记录，非事务式外部执行收据或防管理员伪造签名；旧 `.lock` 崩溃残留与当前 OS lock 不能混为同一恢复实现。新的标准 A2A 委托和 MCP 工具权限需明确这些领域边界，不能因用了协议/框架而认为自动获得。

## 按处置归类

| 处置 | 内容 | 下一步可验收边界 |
|---|---|---|
| 保留 | Python 唯一规则源、schema/引用/规则/策略校验、确定性 diff/Evaluator、固定配对 manifest、结果限制说明 | 同一冻结 artifact 在 Author 预检和 Verification 复检使用相同领域版本，不会由模型覆盖 FAIL |
| 迁到 Config | requirement/clarify、catalog/schema/config 读取、精确参数约束、物化 Candidate Config、展示 diff、策划确认 | 默认单次候选交付；用户需优化时另有明确范围/预算/验收，不隐式启动搜索 |
| 重构 | 当前 changes-plan 输入、worker 内 apply_changes、完成收据绑定、失败持久证据、Author/revision 关联、授权与总预算 | Verifier 工具面无写候选能力；输入 hash 漂移先拒绝；失败结果原路返回 Author；新 revision 不重置总额度 |
| 降级实验 | 旧 model-selected 反复 propose/simulate/review Loop、当前可信 numeric CLI、旧自然语言命中率/固定域成绩 | 作为特定任务和环境的研究证据；不代表全类型 Candidate、A2A 产品或 Config 默认优化 |
| 从新默认架构淘汰 | 根层 review→固定减韧/减攻 repair、Verifier 自造 Spec/指标或构造候选、沿用历史目录名划职责 | 不删除旧代码/证据；新接口拒绝 repair/changes，提供具名失败证据 |

Coding 的原生子 Agent 数量与分工继续由任务动态决定。这里的 Config/Verification/NPC 是能力边界，不是把 Coding 固化为固定 1+3，也不是要求每次验证生成三名子 Agent。本审计没有重新评价封存协作实验。

## 已有证据与本次最小核验

| 层级 | 证据与结果 | 能证明 / 不能证明 |
|---|---|---|
| 本次源码 | 上述完整运行实现和当前测试 | 能判定职责、调用与账本顺序；不能用静态审计代替真实自然语言/网络/Unity 集成 |
| 本次离线回归 | 2026-10-05，以 framework venv `python -B` 加载 test_verification，排除唯一会启动旧 worker 的 `test_integer_numeric_changes_survive_real_game_validation`；其余 15 项，1.380s，exit 0 | 暂停拒绝不执行、hash 批准、结果恢复复用、unknown 不自动重跑、配对报告、进程锁等通过。未称本次重跑全部 16 项或真实游戏 |
| 本次 hash 核验 | 现 src 与 [最终恢复结果](D:/Desktop/mihoyo-agent-project/research/evidence/verification-recovery-n7zc67l5/result.json) 8/8 源 hash 相同；当前 game fingerprint=`68aa0460da651796a9f75d77c2433a07b7be2762f4d07f456721e86eada87b7f`，与历史恢复输入一致 | 历史结果可以定位到未变源码。不是新跑 4/12 场，也不是环境完全一致证明 |
| 2026-10-04 切片 | [测试日志](D:/Desktop/mihoyo-agent-project/research/evidence/verification-slice-tests-20261004.log) 16 tests /2.071s；[最终正常结果](D:/Desktop/mihoyo-agent-project/research/evidence/verification-slice-final-20261004/result.json) 12 场 DESCRIPTIVE_ONLY | 当前数值适配器行为证据，不是自然语言 Author 或独立冻结候选服务 |
| 2026-10-04 恢复 | [probe](D:/Desktop/mihoyo-agent-project/research/probes/verification_slice_probe.py:21) 与最终结果：真实 4 场后 domain commit→exit73，3 新进程 resume 不重算；unknown exit74 在 execute 前退出，0 场开始但保守扣 4 | 证明特定进程中断窗口；unknown 场景不能误报已经执行 4 场。无分布式 exactly-once/断电/自动补偿保证 |
| 2026-10-03/更早旧域 | [离线日志](D:/Desktop/mihoyo-agent-project/research/game-verification-evidence/pytest.log) 181 passed；[旧交付](D:/Desktop/combat-foundation/docs/AGENT_DELIVERY_ACCEPTANCE.md:14) 75/75 与 4/4 对照，45 ready_for_human/15 awaiting_input/15 rejected | 历史受限域预期行为；不是 75 个自动采纳、更不是新 Config/Verification 边界已经集成。历史 200 场/Unity929事件本次未重跑 |

本次离线核验命令要点（工作目录 `D:/Desktop/mihoyo-agent-project`，所有测试数据均用 TemporaryDirectory；无模型/Unity调用）：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='src;tests'
@'
import unittest, test_verification as tv
suite=unittest.TestSuite()
for cls in (tv.VerificationTests,tv.ReportTests):
    for name in unittest.defaultTestLoader.getTestCaseNames(cls):
        if name != 'test_integer_numeric_changes_survive_real_game_validation':
            suite.addTest(cls(name))
r=unittest.TextTestRunner().run(suite)
assert r.wasSuccessful() and r.testsRun == 15
'@ | & research/.venv-framework/Scripts/python.exe -B -
```

## 审计输入 SHA-256

以下为本次读取的文件 bytes SHA-256。旧源根为 `D:/Desktop/combat-foundation/services/verification-agent/verification_agent/`；当前源根为 `D:/Desktop/mihoyo-agent-project/src/agent_workbench/verification/`。路径完整含义由表头给出，不用 Git HEAD 代替未提交文件的身份。

| 文件 | SHA-256 |
|---|---|
| combat-foundation/README.md | `b29230b62cde2e3de9f96e327bbe23fbe0c1a6dfccf16da683233aded930e440` |
| combat-foundation/current_context.md | `1f0015897227f1821ca96c5f3d69c469755ef365381e9ae5392da14c045596a9` |
| combat-foundation/AGENTS.md | `899cc3cb9b9145c5eed1883e540ba5fd746afec7623a6d62e6da32d46efe5655` |
| 旧 workflow.py | `4e8f16e8d43137c586256dca29dae1201e83bb2ceadcff82d1a6f8df7500bc77` |
| 旧 agents.py | `3c74b8f3bda0d84ce748f0176e462a8ab25c4a3e57a3d10eee93cdf91104fb2a` |
| 旧 validation.py | `16f5cefc37a06065b4d87bad412ff5845299bfa95345025d85e31b3883d30523` |
| 旧 storage.py | `2467d4069726f830561e53a95bf25e4a9497f2d3c45d39b4bbae7e9e8867aa38` |
| 旧 provider.py | `f042fc3122c11b237453e7108a68d4c9f685be830ffd395eaa491cc4f3ca0115` |
| 旧 v2/loop.py | `8e9f3571d8a8733a759fe53589f4103fc3eaca02fb59711c8cae7d16919a16a5` |
| 旧 v2/models.py | `f9862c8965a83adf1f6c841e2c397b3a29358f14cf4a72a734b65ee114f1cf57` |
| 旧 v2/policy.py | `74501c52d9b5e63e400431e6a06ea4ccbd0fa8d1d96b2e0b473c48c92e6e5049` |
| 旧 v2/tools.py | `7c1bda3f321bbcb733398fd7f14b12f2987fe98b2decebb738f23d2bf5ba0a04` |
| 旧 v2/evaluator.py | `a3118abdd9f78c9a5764a19a7fae33653dd8f295bfd12b9297e483fc44f10d70` |
| 旧 v2/evidence.py | `e821b40094c3f3855ee203618646eeb46f290cf9231c2f815fd103d9d6319693` |
| 旧 v2/provider.py | `f6605fd9f20fed6623d016eabc0e13ca780d99f0be4f601931b960633b85a74e` |
| 旧 v2/cli.py | `f6fbfda63f399c0055da8c2584c3a778b4ec9cda613c63db19a98ee0328e36a4` |
| 旧 v2/prompts/game_change.md | `eb9b9687e6c80710b3037c4b28badec578d432fa982533abaa32f9bc8afe190d` |
| 旧 v2/prompts/verification_review.md | `00da638c6809a30bec865334b4166d059630c887ce8b4457fea9181bdfc08663` |
| 当前 contracts.py | `ff6357a0c04231df2a8e4ea9c6937ddb9846ab59981fc48b9e3b95d306fe75aa` |
| 当前 combat_worker.py | `e80d1ac86b6e09130ac97e0a4111a5aa69fa8009c5142a623e69bc520a7895c6` |
| 当前 workflow.py | `d85cf7bcd1bf8df6eb8f9e50f481fc1a70722084d540a10fb52109a1fde77f0a` |
| 当前 store.py | `def2eb33da135c5862a100c87b21fe2072eb0f537ade5f0d9e264cf44b18b6c9` |
| 当前 report.py | `7288d24999859df5f1dd9d0e13b1a95271833daed3c5e061b3b6266cc8dd3f13` |
| 当前 __main__.py | `e53710c5e12fd481579b454a9d24549d6445185d5ac85ef26a77ceb7183a7f43` |
| tests/test_verification.py | `9948b8fca2c4fc47eecd322ecf0aa3ab6b0ab2d58985f334084fc142a543708c` |
| verification_slice_probe.py | `1c9881f1ac3af31d4f3b8236308ca8d28d2fa277856b32ae3442a75d1c1123ef` |
| verification-slice-tests-20261004.log | `28f348fe4a1b373699411194719b08db1f5ed875b007cfa2ac7e0426765a5e56` |
| verification-slice-final-20261004/result.json | `efc776e91c036fb25ab3da2730c3da22a2d57dfdfd61cb0506234761e78875f7` |
| verification-recovery-n7zc67l5/result.json | `4c20716dce557561c0ff54716bdbbad09ca7e2b5e8ce3de44e89e8aaf352a1c6` |

## 追加：冻结候选边界的真实领域 probe

本轮追加授权后完成独立 [frozen_candidate_probe.py](D:/Desktop/mihoyo-agent-project/research/probes/frozen_candidate_probe.py) 与 [对应测试](D:/Desktop/mihoyo-agent-project/research/probes/test_frozen_candidate_probe.py)。Author-only 函数调用旧 policy，将完整 baseline 中 breaker_skill.multiplier 从 1.4 改为 1.7，物化 content-addressed 的完整 baseline/candidate/scenario。Verifier 的 inspect/verify 函数只接收冻结引用；没有 changes 入参、没有导入或调用 apply_changes，不写候选文件。它读取并验证文件 bytes hash、schema、来源和范围，然后执行固定 seeds 7/11、balanced、baseline/candidate 共 4 场。

结果封存在 [manifest](D:/Desktop/mihoyo-agent-project/research/evidence/frozen-candidate-probe-20261005/manifest.json)、[原始结果与 Trace 引用](D:/Desktop/mihoyo-agent-project/research/evidence/frozen-candidate-probe-20261005/verification/result.json)。4 份完整 Trace 可由各自引用读取；9/9 artifact/输出文件 SHA 核对通过，40 个游戏源/配置文件、8 个当前 src 文件与已有来源 hash 相同，候选磁盘 bytes 和传入模拟器的模型前后不变。结构校验 PASS；2 对结果仅 DESCRIPTIVE；总体 INCONCLUSIVE。两对均 win→win 不能外推行为改善，本文不将样本耗时变化认定为能力收益。

测试先观察到 6 个缺实现失败，再实现并完成 6 个通过；最终 [测试日志](D:/Desktop/mihoyo-agent-project/research/evidence/frozen-candidate-probe-20261005-tests.log) 为 0.516s、exit 0。测试使用真实 artifact/policy/schema；给 simulate 安装禁止调用断言仅用于验证失败发生在模拟前，不制造成功战斗数据。覆盖 hash 篡改、引用越界、声明 schema 错、正确 hash 下的 payload schema 错，以及 changes 输入/源指纹漂移拒绝；禁用 Author 的 apply_changes 后 Verifier 预检仍能通过。拒绝测试没有新增模拟。独立 hash 复核详见 [review.json](D:/Desktop/mihoyo-agent-project/research/evidence/frozen-candidate-probe-20261005-review.json)。

运行命令（显式旧游戏 Python、`-B`，未读取模型设置、未调用模型）：

```powershell
& D:/Desktop/combat-foundation/.venv/Scripts/python.exe -B -m unittest discover -s research/probes -p test_frozen_candidate_probe.py -v
& D:/Desktop/combat-foundation/.venv/Scripts/python.exe -B research/probes/frozen_candidate_probe.py --output research/evidence/frozen-candidate-probe-20261005
```

第二条已运行，输出目录不可覆盖；无需为复核再跑 4 场。新增模型调用 0；新增真实游戏 4 场。该 probe 证明本地可信数值候选的逻辑职责分离，不是 OS 只读沙箱、生产授权、标准 A2A、异步作业、LLM 需求理解或代码/build 候选验证；这些仍是接口设计及后续实施验收。旧 Spec 为结构 policy 兼容需要一个 criterion，probe 没有执行它或虚构用户效果验收，原始结果明确记录此限制。未追写旧实验。

| 新证据 | SHA-256 |
|---|---|
| frozen_candidate_probe.py | `d95ad02484d33f50ca32a577c52883eb59f4c1dbd0def612676cb7b2abd8b9a8` |
| test_frozen_candidate_probe.py | `31e16c5f33f0c5dfcca75b61d7796ca15bd692f1d9a8ac9a8a6ad583eabbc0ab` |
| frozen-candidate-probe-20261005/manifest.json | `a8da5e95ca4ce120aeee4a3e0d2620f8c633e5e2711ed00b51f066254873091b` |
| frozen-candidate-probe-20261005/verification/result.json | `9f7890d31dd857d90d0ef7a4761654b447081cbfdbf2da0587a016af0f4ed87e` |
| frozen-candidate-probe-20261005-review.json | `b40390d8a201aebe57691191d12c39abe1ce931d9414e1aabc1c6f7ce3713e1d` |
