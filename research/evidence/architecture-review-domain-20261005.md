# 四能力架构：领域边界独立审查

日期：2026-10-05。只读审查 TECHNICAL_PROPOSAL.md、FRAMEWORK_ORCHESTRATION_DESIGN.md 新稿，交叉核对既有职责审计、当前 Verification 源码与冻结候选 probe。没有修改主文档、旧源码或封存证据，没有重跑真实 4 场或模型。

当前处置：下列两项 P2 已在同日修订中关闭，见末尾复核。路线第 5、8.3、8.6 节未发现新增实质矛盾。原审查意见保留，作为修改与复核记录。

初次审查结论：总体职责收敛与源码事实一致。以下两处需要在实现确认/准入端点前明确，属于契约缺口，不声称是已有产品运行缺陷。没有发现需要推翻四能力架构的阻断问题。

## 1. 候选确认必须覆盖完整 manifest 身份

**P2。** [TECHNICAL_PROPOSAL.md:162](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:162) 写“策划确认后冻结候选”；[FRAMEWORK_ORCHESTRATION_DESIGN.md:54](D:/Desktop/mihoyo-agent-project/FRAMEWORK_ORCHESTRATION_DESIGN.md:54) 是“确认具体候选 hash → 冻结 CandidateManifest / 记录确认”。但总体方案第 106–112 行要求 Manifest 同时绑定 baseline/candidate/scenario、规则和环境身份。当前顺序及“候选 hash”用语未明确确认是否覆盖完整 Manifest，可能被实现成只批准 candidate JSON bytes。

例如 candidate 内容不变，却在确认后冻结了不同 baseline/scenario 或规则版本，此时原 diff、编辑许可和行为解释并不是策划看过的对象。不能仅凭 candidate bytes 相同复用该确认。

建议：先物化完整不可变 Manifest 及由同一输入得到的 diff，UI 确认 `manifest_hash + author_revision`；确认后只持久化决定，不再重取可变 baseline/scenario 或重新构造 Manifest。若“候选 hash”本来就指 manifest hash，应在两处明确统一。实验预算批准、最终采纳/发布仍保持独立。

这项建议是生产合同补齐。冻结 probe 固定了完整引用并核验 request/artifact hash，但没有实现人类确认端点或确认竞争测试，不能用 probe 通过消除此缺口。

## 2. 区分不接受的能力范围与已接受任务的证据不足

**P2。** [TECHNICAL_PROPOSAL.md:170](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:170) 把“能力不支持”列为 INCONCLUSIVE；同文件第 114 行又规定首版 Card 只支持 Config。[FRAMEWORK_ORCHESTRATION_DESIGN.md:216](D:/Desktop/mihoyo-agent-project/FRAMEWORK_ORCHESTRATION_DESIGN.md:216) 则规定范围未接受是 rejected。当前没有把两个层次的“能力不足”明确拆开，会影响状态、重试提示和是否建立验证预算 reservation。

建议给出一致映射：准入前不支持的 candidate kind/profile、越权或非法 artifact 引用走协议输入错误/REJECTED，不宣称已判断候选质量；已接受范围内某项必要检查无法完成、能力缺失或运行证据不足，保留覆盖与原因并交付 INCONCLUSIVE；若已证明另一项必需标准失败，总体仍 FAIL。合法报告的 A2A 状态为 COMPLETED；服务无法交付才 FAILED。典型用例分别是“Config-only 首版收到 code kind”和“已接受 Config 检查运行时拿不到必需结果”。

## 未发现问题的重点与 probe 覆盖

- Config 生成/格式纠错与 Verifier 调查分开；失败返回 Author，新 revision 不修改旧候选/报告，也不重置 campaign 总预算。新默认图没有验证失败直接自动调参的边。
- 三种决定已明确区分：候选确认、实验预算批准、最终采纳/发布。上述第 1 项只要求确认对象绑定完整，不建议额外增加第四种确认。
- 逻辑样本与物理 attempt/CPU/存储/模型成本分账；重算同 seed 不增加统计 n；旧大预算不是本轮授权。PASS/FAIL/INCONCLUSIVE 不交由模型覆盖，结构通过不偷换为总体概率保证。
- 旧代码职责、当前 worker 内 apply_changes、缺失败持久 receipt/上游 candidate hash/跨 revision 总预算，以及可信 numeric 不等于代码沙箱，均如实写明。未用框架或协议存在性代替领域保障。
- [冻结 probe 复核](D:/Desktop/mihoyo-agent-project/research/evidence/frozen-candidate-probe-20261005-review.json) 证明确定性 Author 物化完整 Candidate Config，Verifier 只读 artifact；真实 4 场、6 个边界测试；结构 PASS、行为 DESCRIPTIVE、总体 INCONCLUSIVE。没有 LLM 计划、真实身份权限、审批端点、A2A、持久异步 Job、只读 OS 沙箱或代码/build 验证。本次两份设计没有把这些缺口写成已完成。
- 严格统计确认与根据失败追加诊断的调查需在实现中继续分 profile，遵守“确认结果不用于调参、不追加到 PASS”；目前文字已给出该约束，本轮没有发现新统计效果或费用夸大。

本次审查未覆盖路线更新；协议版本真实性另有专门审计，此处不重复网络查询。

审查所读快照（修订后行号可能变化）：

| 文档 | SHA-256 |
|---|---|
| TECHNICAL_PROPOSAL.md | `14f7f5231774cc3b390367787ed20fe026ff7faad1afc917fa1ad8c7262e22e0` |
| FRAMEWORK_ORCHESTRATION_DESIGN.md | `39f6bdb27dfaba5fc112db0451f3c9de9d8e9232ea249faaed60f12f639c8ccf` |

记录是对上述快照的审查，不覆盖父任务随后可能完成的修订。未再次执行模拟或把既有 4 场重复计入本轮验证。

## 同日修订复核与路线审查

**两项 P2 均已关闭，当前审查范围通过。** 只读复核，没有运行游戏、模型或修改主文档。

| 原意见 | 修订事实与定位 | 处置 |
|---|---|---|
| 确认完整 Manifest | [总体方案:162](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:162) 先冻结 baseline/candidate/scenario、规则/schema 和 diff 来源的完整 Manifest，再确认 manifest hash，确认只新增决定记录；[框架图:54](D:/Desktop/mihoyo-agent-project/FRAMEWORK_ORCHESTRATION_DESIGN.md:54) 已调整节点顺序；第 62 行要求任意组成变化产生新 Manifest 和新确认；[路线:143](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:143) 纳入退出条件 | 已关闭；生产实现仍需相应确认竞争/变更回归，未声称探针代替这些验收 |
| 准入与证据不足分开 | [总体方案:170](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:170) 和 [框架:92](D:/Desktop/mihoyo-agent-project/FRAMEWORK_ORCHESTRATION_DESIGN.md:92) 已明确准入前 unsupported kind/profile、非法引用/权限错误为拒绝或标准输入错误；已接收任务缺检查/证据则 INCONCLUSIVE，已证必需失败仍 FAIL；[路线:153](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:153) 要求 unsupported kind 拒绝且 Card 如实 | 已关闭；A2A COMPLETED 与业务结论继续分离 |

路线第 5 节检查结果：M3-A 只负责配置作者、生成纠错和确认，不默认效果搜索；M3-B 明确将当前 changes 输入/worker apply_changes 迁出、持久失败证据、只读候选及总 grant；M3-R 规定异步/取消/补输入等待验门槛，未拿当前同步 CLI 顶替；M3-C 依赖代码/build 隔离和真实引擎验证，完成后才扩大 Card。各阶段顺序和两份设计一致。

路线第 8.3 节检查结果：240 场是拟定开发 cap，6 个开发/24 个正式任务也标明收费前另冻结预算，未恢复旧 314160 场授权；严格效应/非劣阈值与功效是假设下示例，普通描述性证据不升格为概率保证；配对共同胜利耗时、失败/超时分母、确认不回流调参和逻辑/物理预算分账一致。固定流程与 Agent 调查对照使用同一冻结候选且都禁止修改，符合所评能力。

路线第 8.6 节检查结果：Config 的 6 开发/12 正式任务聚焦配置符合、合法性、澄清/拒绝与编辑范围，不把“候选合法”写成“游戏效果改善”；基线也有相同 schema/规则上下文。跨产品测试覆盖同一 Verifier、Author 新 revision、unsupported kind、身份隔离和故障，未与 NPC 混线。未发现新增实质矛盾。

新快照 SHA-256：

| 文档 | SHA-256 |
|---|---|
| TECHNICAL_PROPOSAL.md | `91dff6b9097053307cba084d3d35aa71f059ff1c701785d4cf5a0aac0c09337a` |
| FRAMEWORK_ORCHESTRATION_DESIGN.md | `bd0e43f6af851ae638c4a3e7b8647d3fe2e7fe6a5e20c5a1b1a67b8380bfeb63` |
| IMPLEMENTATION_ROADMAP.md | `5421897fa98d7a7015026c3ab95191ca4210cef9fee26201840315ec4af7e8af` |

该“通过”是上述文档合同一致性复核，不是未来产品或未实现故障矩阵已经通过。
