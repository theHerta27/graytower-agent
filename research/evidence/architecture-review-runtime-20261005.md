# Runtime 独立架构评审（2026-10-05）

范围：完整阅读本轮 `TECHNICAL_PROPOSAL.md` 与 `FRAMEWORK_ORCHESTRATION_DESIGN.md`，随后检查 `IMPLEMENTATION_ROADMAP.md` 的 G0、4.1、5、7、8.5 及相关 M2 段；对照 [Runtime边界审计](D:/Desktop/mihoyo-agent-project/research/evidence/coding-runtime-boundary-audit-20261005.md) 与所引用的本地 Codex 源码。未改被评文档/源码，未运行模型或候选代码。

评审时文件 SHA-256：

- `TECHNICAL_PROPOSAL.md`：`14f7f5231774cc3b390367787ed20fe026ff7faad1afc917fa1ad8c7262e22e0`。
- `FRAMEWORK_ORCHESTRATION_DESIGN.md`：`39f6bdb27dfaba5fc112db0451f3c9de9d8e9232ea249faaed60f12f639c8ccf`。
- `IMPLEMENTATION_ROADMAP.md`：`e0e8bb44f0077855cede3151953975f20c8a45e465a5e0ecfd26927b93fe6301`。

## 发现：P1 — 子 Agent 只读需要明确的强制执行前提

位置：[TECHNICAL_PROPOSAL.md:132](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:132)。

这里把首版写入策略定为“主 Agent 唯一写者，子 Agent 只读”。但目前选定 Runtime 的降权机制尚未确定：本地 [child_config.rs:73](D:/Desktop/codex-main/codex-rs/core/src/agent/child_config.rs:73) 应用角色后，第84行又调用 runtime overrides；[同文件:171](D:/Desktop/codex-main/codex-rs/core/src/agent/child_config.rs:171) 将父 turn 的 approval、cwd 与 permission snapshot 重新套给子。旧 [role.rs:80](D:/Desktop/codex-main/codex-rs/core/src/agent/role.rs:80) 也未投影独立 sandbox/MCP 权限。父线程可写时，不能仅凭 role 的只读说明或配置名称就认定子线程被强制只读。省略 agent_type、fork、恢复路径也可能回到父权限。

影响：实现人员若直接依此用角色模板部署，子任务仍可能经原生 shell/apply_patch 或继承的工具写入共享工作树，破坏“唯一写者”的冲突与候选冻结前提。第134行已承认版本差异，故此处是**尚缺明确成立条件的设计约束**，不是声称现有产品已出现越权，也不是认定新稳定版本必然同样不支持。

建议：明确将“真实子权限收紧”作为该首版策略的 G0 前置。锁定 SDK/CLI 后分别验证普通/默认角色/fork/resume 子任务的 shell、apply_patch、MCP 与 dynamicTools 写路径；越权写必须由 Runtime/OS/服务端执行边界拒绝。若配对版本不能按子降权，选择经过验证的受限能力或独立隔离工作区方式，继续使用原生动态调度；不要把提示词、角色名称或仅隐藏工具算作权限完成。不要求为此改写 Runtime 主循环。

同一前提也出现在 [IMPLEMENTATION_ROADMAP.md:131](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:131)，应同步收紧。

## 追加发现：P2 — G0 的 MCP 实现优先级相反

位置：[IMPLEMENTATION_ROADMAP.md:48](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:48) 与 [TECHNICAL_PROPOSAL.md:263](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:263)。

路线仍写“当前选择 SDK dynamicTools→业务 MCP client 窄转接继续真实工具契约验收，再与受测版本比较”；总体新稿则要求先验当前稳定 Runtime 原生 MCP＋DeepSeek，不兼容才用窄桥。两者会驱动不同的 G0 先后和 Adapter 实现；且 fresh child 对 dynamicTools 与 MCP 的继承不同，这不是纯措辞差异。建议统一为已决定的原生优先、受限窄桥后备，并保留旧 MCP1 fixture 的历史范围。

## 追加发现：P2 — 旧采纳规则仍允许删掉动态功能

位置：[IMPLEMENTATION_ROADMAP.md:275](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:275)。

“若所有差异不值得维护，就保留单 Agent”仍把效果实验结果写成删除协作能力的条件，与用户要求、M2-C4 和第277行“功能验收通过后交付 auto/single、不因负面删除原生动态能力”冲突。建议只让结果决定是否推荐具体任务/分工策略，保留用户要求的原生 auto 与 single 功能；移除旧功能淘汰措辞。

## 其余检查未发现需阻断的新问题

- 原生动态 0..N 与历史固定 1+3 分开；single 是显式模式，没有把闭卷 benchmark 阴性外推为功能不可交付。
- 0.160.0 官方版本、已测 alpha、参考 SDK 的 0.153.4 dependency 分开记录，并要求重验；没有将源码能力或 fixture 直接写成生产完成。
- SDK reader 不等待长期 QA，A2A 快速提交与后续跟踪分开；人工审批 reader 与默认 auto-review 风险已写入。
- A2A completed 不等于业务 PASS，canceled 不等于物理 worker 回收；本地 asyncio/SDK/MCP 取消不被当作远端停止证据。
- Candidate 身份不可变、Verifier 不修候选、代码/build 与 QA 控制面隔离、无模型凭据执行后端及 Windows command/exec 限制已明确列为待验边界。

本记录只评实现边界与事实表述，不代替安全隔离、取消恢复或真实业务验收。上述检查未报问题也不表示这些尚未实现的能力已验证通过。

## 最终处置与定向复验

2026-10-05 收到修订通知后，重新读取总体方案第130—136行、路线第43—49/127—134/273—279行；本轮没有扩审其他历史材料。

| 发现 | 修订后的实际内容 | 处置 |
|---|---|---|
| P1 子只读执行前提 | 总体132、路线131明确为待验约束，要求 shell/apply_patch/MCP/dynamicTools 各路径越权写负例；不接受 role/prompt 代替隔离，版本不能降权时走受测只读能力/隔离工作区 | 文档问题关闭；真实隔离仍须 G0 验收，未声称已实现 |
| P2 MCP 优先级 | 路线48已改为锁定稳定 Runtime 原生 MCP＋DeepSeek 优先，namespace 不兼容才用窄桥；MCP2/真模型契约分别验证 | 关闭，与总体263一致 |
| P2 实验阴性删除动态功能 | 路线275仅否定不值得推荐的固定 profile，明确保留受测原生动态能力与 single；与277功能退出规则一致 | 关闭 |

定向复验时总体方案 SHA-256 为 `91dff6b9097053307cba084d3d35aa71f059ff1c701785d4cf5a0aac0c09337a`，路线为 `5421897fa98d7a7015026c3ab95191ca4210cef9fee26201840315ec4af7e8af`。本轮报告的3项均已按上述限定关闭，未发现需追加的新问题；本结论不覆盖其他评审者的修改或尚未执行的产品验收。
