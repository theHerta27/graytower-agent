# 总体方案独立评审：游戏、Verification、NPC 与两仓边界

评审日期：2026-10-03。评审对象为本轮首次读取的 TECHNICAL_PROPOSAL.md（263行）和 IMPLEMENTATION_ROADMAP.md（162行）；以下行号针对该版本，后续修订可能移动。仅评审，未修改主文档。

总体方向成立：Python 唯一规则、可玩会话优先、真人命令与 headless 共用推进、Game Host 不加载未发布候选、NPC 按角色可知范围过滤、验证不把描述性样本冒称商业平衡，均与源码和任务书一致。M1 的决策边界存档、RNG、幂等、真实 Player 操作验收已达到可启动实施的粒度。以下为需要修改的实质问题。

## 1. [P1] Game Host 世界提交与 NPC 记忆落库之间缺少跨库恢复约定

位置：[总体方案116](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:116)、[209](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:209)、[224](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:224)，[路线95](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:95)。

方案按领域拆 SQLite 库，Game Host 执行世界事务，NPC 服务独立记录经历。当前只说明“世界执行返回收据，再落入经历”和 command id 去重。如果世界奖励已提交、响应/记忆写入前进程退出，就会留下世界已经改变而 NPC 不知道的状态；若记忆先写且世界提交失败，则可能记住未发生的奖励。Game Host 单库事务不能覆盖另一个服务的记忆库。M4 的“重复发奖为0”不足以验收叙事恢复与事实一致性。

**建议修订：** Game Host 在同一事务中提交世界状态、command receipt、权威领域事件/outbox；NPC 使用 `(save_id, world_event_id)` 幂等消费到 inbox/经历库，保存消费游标并可重放对账。对话只能把提交收据对应的事件当已完成事实，摘要是可重建投影。存档分支需要新的 namespace/lineage，不能沿用旧 save_id 的去重空间。M4 增加“世界已提交但响应丢失”“NPC落库前崩溃”“事件重复/乱序”“旧分支迟到响应”故障注入。这里不需要分布式两阶段提交。

## 2. [P1] Coding 演示主任务包含已经实现的字段，另一半缺陷尚无复现证据

位置：[总体方案162](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:162)、[249](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:249)。

“为护盾过期增加明确事件原因”不是当前源码缺口：`shield_expired` schema 已有 `reason`，[trace.py:16](D:/Desktop/combat-foundation/game-core/combat_core/v2/trace.py:16)；消耗完和自然过期分别写 `depleted`、`expired`，[effects.py:73](D:/Desktop/combat-foundation/game-core/combat_core/v2/effects.py:73)、[125](D:/Desktop/combat-foundation/game-core/combat_core/v2/effects.py:125)。Unity 现状会重新加载 typed shields，当前审计也未复现“护盾清除显示错误”。把这个例子当已有真实缺陷，会导致开发无实质 diff 或为了配合演示重新制造问题。

**建议修订：** 换为经源码确认缺失的跨端功能，例如新的受控初始支援参数及其合同/规则/Unity 显示；或使用冻结 benchmark 分支中明确标注的注入缺陷，保存注入补丁、期望行为和复现测试，不把注入缺陷叙述为原项目 bug。保留一个实际发现且能先复现的 bug 任务作第二案例。

## 3. [P2] 允许胜率下降2个百分点与旧 Evaluator 的强制“不下降”不兼容，需要显式版本迁移

位置：[总体方案143](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:143)，[路线83—89](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:83)、[144](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:144)。

现有 Evaluator 在解析 Spec 前，强制对所有 policy 增加 `win_rate_delta >= 0`，[evaluator.py:11](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/evaluator.py:11)。仅把 Spec 改成 `>= -0.02` 或“修正配对耗时”并不会改变这条硬门槛，候选小幅下降仍会 FAIL。当前 Criterion 无 scenario/profile 维度，工具只有固定 seeds×policies，[models.py:19](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/models.py:19)、[tools.py:79](D:/Desktop/combat-foundation/services/verification-agent/verification_agent/v2/tools.py:79)，也不能直接表达新三层场景的保护条件。

**建议修订：** M3 增加版本化 `ExperimentSpec/EvaluationPolicy` 迁移任务，区分旧描述性“不下降”模式与新的获授权非劣界/区间判定。Margin、场景层和聚合方式属于操作者锁定标准，模型不能扩大。历史2.0结果继续按旧 policy 阅读；不能用新容忍度重评分旧 FAIL 后改成成功。新评测需覆盖“点估计小幅负且仍可能合格”“区间跨界不确定”“超过界限失败”和旧任务行为兼容。

## 4. [P2] 采样计划还缺统计判定单位、追加规则与明确预算分配

位置：[路线140—144](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:140)，[总体方案156](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:156)。

1560场的乘法计算正确。问题在于：四候选探索960场 + 一次最终保留600场已经用满上限；之后又允许“按预设预算追加”，没有说明使用未花完的预算还是另设额度。2策略×3场景层同时缺少验收粒度：每格都要证明-2个百分点非劣，还是每个策略按固定权重汇总，或整体只判一个结果？不同选择会产生不同 verdict。文档认识到50 seeds可能不足，这是正确的，但没有规定区间方法和重复查看保留集的停止规则；普通固定样本95%区间不能直接当成任意追加/停止下的同等保证。

**建议修订：** 首版最简单的是预先锁每个策略/场景的样本数、聚合权重、主要指标和固定一次最终分析，保留集只运行一次，预算耗尽仍跨界即 INCONCLUSIVE。若确需追加，单独授权 reserve 并冻结检查时点/停止规则，选有相应保证的序贯方法，而非“看结果到通过为止”。明确50样本时全胜/无discordance的区间退化测试，不采用机械的零宽区间制造充分性。硬回归按每层检查；效果指标明确按层或按固定权重判断，不允许 pooled 平均掩盖低资源层退化。

## 5. [P2] “三阶段仍展示关键机制”未变为可判定的保护项

位置：[总体方案143](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:143)、[250](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:250)，[路线85](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:85)、[144](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:144)。

主场景同时要求更快通关和保留机制展示，而当前验收描述只给胜率/AV、泛称“硬回归”。实际核心可能跨过阶段，`phase_changed.entered=False` 表示未真正进入中间阶段；Boss被击杀后也不会再进入后续阶段，[boss.py:8](D:/Desktop/combat-foundation/game-core/combat_core/v2/boss.py:8)。单看通关更快、胜率更高可以接受一个把召唤或蓄力展示完全跳掉的候选，与产品主目标冲突。

**建议修订：** 锁一组机制演示场景/命令脚本，指定“实际进入三个阶段”“至少发生一次召唤”“发生蓄力并可被指定动作打断”等事件谓词作为单独硬门槛；对随机/策略变化影响展示频率的部分则定义完成率及阈值。不要把“所有随机对局都必须出现每种事件”当默认条件。结果页单列机制保持结果，并在M3加入“数值指标达标但机制门槛FAIL”的测试。

## 6. [P2] 两种NPC支援缺少与现有初态的明确映射

位置：[总体方案211](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:211)、[224](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:224)，[路线93—97](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:93)。

现在 `Scenario` 只支持 initial_skill_points、initial_energy 和 limits，[contracts.py:191](D:/Desktop/combat-foundation/game-core/combat_core/v2/contracts.py:191)；每场创建的角色固定满生命且没有初始护盾，[state.py:77](D:/Desktop/combat-foundation/game-core/combat_core/v2/state.py:77)。因此“修复包/护盾支援改变下一场初始条件”不能直接落在现有规则里：修复满血角色没有效果，初始护盾需要新增协议和规则路径。M4 尚未把这项规则改造或可复用映射列为依赖。

**建议修订：** 首版可明确选用现有合法参数，例如“额外1点初始战技点”与“支援角色获得指定初始能量”，并给每种支持固定 ID、幅度、选择消耗、开战时一次消费和快照映射；叙事名称解释实际效果。若坚持初始护盾，则把版本化 encounter modifier 的契约/核心/consumer/golden测试列为M4前置或M2代表功能。NPC只选择预编写方案ID，不能输出任意数值。这能确保NPC选择有实际后果，而非对话宣称有支援。

## 7. [P2] 两仓联合发布只锁游戏版本，尚不足以复现工作台与NPC协议组合

位置：[总体方案127—131](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:127)，[路线103—107](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:103)。

两个生产仓库的划分合理，但现有 release 清单字段主要绑定游戏commit/规则/内容/Unity。工作台提供NPC、Verification policy、Broker和DTO消费端；如果它们升级而游戏 release 不变，同一“游戏版本”可能得到不同权限、判定与叙事行为。方案虽要求 schema hash 锁定，但尚未写明工作台如何获取不可变的游戏工具/契约包、支持哪组版本，或联合发布如何防止消费本机另一个editable checkout。

**建议修订：** 在联合release/lock中同时绑定游戏构建产物hash、工作台commit/产物hash、合同schema hash、NPC故事/Persona和评估policy版本、已锁工具链/依赖；两仓之间通过可校验的版本化包/构建产物消费，不通过隐式相对目录或环境 PYTHONPATH 找“最新源码”。Game Host只有发布管理器可切换当前版本，运行中的会话固定旧release直至结束/显式迁移；CI/doctor运行生产者与消费者兼容矩阵。无需建立独立第三个契约仓库。

## 已对齐及待实测事项

M1已经明确同构建恢复、终结技使用/跳过边界、命令收据与事件一致提交、真实Player手动操作、20场景与5关键存档点；不建议为了上述修订推迟可玩底座或迁移C#。知情过滤在检索前发生、听说不升级事实、迟到行动重验、模型离线降级均有正确的产品边界。

仍需按阶段实际验证的事项包括：UnityWebRequest/Test Framework依赖与Player收发；Windows受限账户下Unity授权和构建；sidecar分发与p95延迟；Python3.12 golden；统计样本量/区间退化；双库崩溃对账；新NPC支援的真实效果。它们在本次文档评审中没有被运行或证明。
