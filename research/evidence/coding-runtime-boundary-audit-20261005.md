# Coding Runtime 边界审计（2026-10-05）

本次只读核对旧 Coding 项目、Codex 本地源码、既有实验和 OpenAI 当前官方文档；没有调用模型、读取密钥、安装或升级 SDK，也没有修改旧仓库、现有 `src` 或冻结探针。本文唯一新增文件即本报告。

**结论：保留 Codex Runtime + 官方 Python SDK + 业务 Adapter。** Coding 主 Agent 可以在任务和权限预算内选择不委派，或按实际问题动态选择子 Agent 数量、职责和串并行方式；原生 Runtime 继续拥有采样、工具续步、spawn/send/wait/close 和子线程生命周期。旧固定 1+3 与六阶段 A+ 是对照实验条件，不是产品工作流。Coding 交付不可变 Candidate Change；独立 Verification Agent 可由业务 A2A 客户端委派。向模型暴露一个提交委派的工具可以是入口，但工具本身不能冒充 Verification Agent。

本文标记：**事实**表示本地代码/原始证据直接可核对；**开源参考**表示官方文档或参考源码能力，不等于本项目集成完成；**项目决策**表示建议的新边界；**待验**表示尚无相应端到端证据。

## 1. 版本与证据不能混为一谈

| 对象 | 本次核验 | 适用结论 |
|---|---|---|
| 旧 Coding 仓库 | `D:/Desktop/herta-agent-coding`，Git HEAD `e121d8207f74af98e22f2c100348b05160a0560b`；已完整阅读 README/current_context | 这是自写 Agent Loop 的 V1，不是已经完成 Codex 迁移的产品 |
| 官方当前 CLI | 2026-10-05 打开的官方 changelog 最新条目是 2026-10-01 的 **0.160.0** | 当前文档目标与旧实验二进制不同；本次没有升级或验证 0.160.0 |
| 本机实际实验 CLI | `codex-cli 0.159.0-alpha.12.1`；二进制 SHA-256 `1722907aa64401bcc9b34467ef5c2af43f6aef9a5045ef04d11d19dfae4589fb` | 10-04 实验只能归于这个二进制 |
| 本地参考源码 | `D:/Desktop/codex-main` 没有 `.git`，无法给出可验证 commit | 文件级行为可作开源参考，不能声称与某个发布 tag/二进制完全一致 |
| 实验导入的 Python SDK | 直接从参考树 `sdk/python/src` 导入；`pyproject.toml` 为 `0.0.0-dev`，声明 CLI dependency `0.153.4`，实际用显式 `codex_bin` 运行上述 alpha | 属于跨版本配对实验，没有验证其默认配对，也没有验证完整 SDK schema |
| 官方当前 Python SDK | 文档已标为 stable；发布包自带 pinned CLI runtime，支持 `Codex`/`AsyncCodex` | 官方推荐默认配对可作为下一步版本基线；本次未从包仓库核验具体最新 wheel 版本号，不将 `0.0.0-dev` 当成最新发布版 |

官方依据：[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)、[当前 changelog](https://learn.chatgpt.com/docs/changelog)。0.160.0 的条目还涉及 provider model catalog、子 Agent environment 和 Windows sandbox 修复，因此不能仅凭版本相近跳过升级回归。

**项目决策：**下一次产品实现先记录“已发布 Python SDK 版本 + 其默认 pinned CLI + CLI SHA + 协议能力/schema + provider 配置指纹”。若需显式替换 CLI，另建兼容矩阵。保留旧实验版本，不覆盖它来伪造当前稳定版验证。

本次重新计算的参考文件指纹：

| 文件 | SHA-256 |
|---|---|
| `D:/Desktop/codex-main/sdk/python/pyproject.toml` | `da5e5b8eca67f727c49befc1bec71ed72957c1358b3c055433af97a5c0bd4354` |
| `D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py` | `8452afbd8148ea212c94e8a6727468054b175acb0daf95002c84b66b604d05a6` |
| `D:/Desktop/codex-main/codex-rs/core/src/agent/child_config.rs` | `33d4dd6f70e6640af1059398272c48b88e16e0005105fbd1ef13e30456d39a39` |

## 2. 原生动态委派可行，但旧实验证据范围有限

**开源参考：**当前官方 Subagents 文档支持独立上下文、并行线程和角色配置；Runtime 负责启动、续发任务、等待和关闭。默认启用并不等于所有模型、推理级别都会主动委派；当前本地 Codex 文档允许由直接请求或项目/技能指令触发。本产品可在受信任 Coding 指令中明确授权“自行判断是否、多少和何种委派”，不必硬编码每次三名专家。[官方 Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

本地源码边界：

| 源码锚点 | 直接可见的行为 | 产品含义 |
|---|---|---|
| [multi_agents_spec.rs:65](D:/Desktop/codex-main/codex-rs/core/src/tools/handlers/multi_agents_spec.rs:65)、[同文件:591](D:/Desktop/codex-main/codex-rs/core/src/tools/handlers/multi_agents_spec.rs:591) | 原生 V1 schema 支持 message、agent_type、fork_context、模型/推理选项；V2 有独立协议 | 动态任务和角色由模型提出；不要复刻 Python 调度循环。是否开放模型覆盖另受产品政策约束 |
| [spawn.rs:116](D:/Desktop/codex-main/codex-rs/core/src/tools/handlers/multi_agents/spawn.rs:116) | handler 调用 Runtime `agent_control.spawn(SpawnRequest)`，携带 parent/root turn 与 environment | 原生 child ID、父子图和 lifecycle 由 Runtime 产生，Adapter 只记录关联 |
| [child_config.rs:51](D:/Desktop/codex-main/codex-rs/core/src/agent/child_config.rs:51)、[同文件:131](D:/Desktop/codex-main/codex-rs/core/src/agent/child_config.rs:131) | 从父 turn 的实际 provider/model/context 构造配置；显式/默认模型与 role 层再覆盖；最后重新套用 live runtime 权限 | “默认继承 DeepSeek”不等于所有 override 都不能越界；应校验主、子、review、恢复及审批链实际 provider/model |
| [child_config.rs:159](D:/Desktop/codex-main/codex-rs/core/src/agent/child_config.rs:159) | V1 full-history fork 拒绝 agent_type override | 不能同时承诺该版本“完整 fork 上下文 + 任意另选 role”；应按有效 schema 选择 |
| [config/mod.rs:3884](D:/Desktop/codex-main/codex-rs/core/src/config/mod.rs:3884) | 有 concurrency/depth/default subagent model 等配置 | 最大并发/深度是上限；不应将上限写成必须创建的数量 |

**事实：**已封存的 [确认 native audit](D:/Desktop/mihoyo-agent-project/research/evidence/collaboration-confirmation-native-audit-20261004.json) 有 28/28 native 检查通过、201 次请求、36 个真实子 Agent：8 single、8 A+、8 parallel、4 serial。12 组团队均确认子 Agent 真 completed 后再 close/父汇总；8 parallel 有实际重叠，4 serial 无前子结果转交。这证明受限 DeepSeek + 原生 V1 lifecycle 能工作。它没有证明动态组队质量优于单 Agent，也没有证明文件编辑、任意工具、取消恢复或完整 V2 兼容。

**事实：**[live runner:193](D:/Desktop/mihoyo-agent-project/research/probes/collaboration_live_runner.py:193) 过滤所有非 lifecycle 工具；[参数校验:241](D:/Desktop/mihoyo-agent-project/research/probes/collaboration_live_runner.py:241) 禁止 spawn role/model override 与 fork；[配置:512](D:/Desktop/mihoyo-agent-project/research/probes/collaboration_live_runner.py:512) 是 read-only、max_depth=1、无 shell/apps/plugins；[fixed profile:42](D:/Desktop/mihoyo-agent-project/research/probes/collaboration_profile_runner.py:42) 额外锁定三份任务文本。因此不能把 frozen runner 直接迁成动态产品 Adapter。

**项目决策：**Coding 内部以“0..N 自主委派 + 受信任能力目录 + 全树预算 + 写入冲突约束”为政策。职责文本可以随任务变化；角色目录描述允许的工具、权限和职责，不固化团队结构。先让只读探索/审查并行；写入子任务必须有明确所有权或独立工作区。原生 spawn 创建线程，不等于业务层自动提供独立 Git worktree、隔离数据库或无冲突文件系统。

## 3. dynamicTools、MCP 与子 Agent 能力传播

**开源参考：**App-server 的 `thread/start.dynamicTools` 和 `item/tool/call` 仍标为 experimental，需 initialize opt-in。工具声明会持久化，resume 可恢复；声明与工具执行宿主是两个层面。MCP 侧当前支持 STDIO/Streamable HTTP、允许/禁止工具以及审批配置。[App-server](https://learn.chatgpt.com/docs/app-server)、[MCP](https://learn.chatgpt.com/docs/extend/mcp)

本地源码已确认以下差异，不能用“父子共享能力”一句话概括：

| 路径 | 源码事实 | 当前判断 |
|---|---|---|
| 普通 fresh native child | [thread_manager.rs:1933](D:/Desktop/codex-main/codex-rs/core/src/thread_manager.rs:1933) 使用 `StartThreadOptions::new`；其 [默认:304](D:/Desktop/codex-main/codex-rs/core/src/thread_manager.rs:304) 为 `dynamic_tools: Vec::new()`，initial_history 为 New | **不能假定继承父 dynamicTools**；父注册某业务工具不证明 fresh child 能调用 |
| fork/resume history | [spawn.rs:1229](D:/Desktop/codex-main/codex-rs/core/src/agent/control/spawn.rs:1229) 传 Forked history；[history/lib.rs:451](D:/Desktop/codex-main/codex-rs/history/src/lib.rs:451) 从 SessionMeta 取 dynamic tools；[session/mod.rs:752](D:/Desktop/codex-main/codex-rs/core/src/session/mod.rs:752) 在显式工具空时恢复 | 源码支持元数据恢复，**仍未实测子线程工具请求路由、实际 handler 重连和权限**。不能把 fork 当成已验生产绕法；它也会增加上下文/泄漏面 |
| configured MCP/client extensions | 父有效 config 被复制；[thread_manager.rs:1932](D:/Desktop/codex-main/codex-rs/core/src/thread_manager.rs:1932)、[同文件:2026](D:/Desktop/codex-main/codex-rs/core/src/thread_manager.rs:2026) 显式继承 `client_mcp_extensions` | 是不同于 dynamicTools 的传播路径；还需按最终 CLI 版本验证实际 MCP 连接、审批、工具目录与 provider wire |
| custom role 配置 | 当前官方文档允许 sandbox/MCP 等角色设置；本地 [role.rs:80](D:/Desktop/codex-main/codex-rs/core/src/agent/role.rs:80) 的投影只包含 instructions/model/reasoning 等和部分禁用项，未投影 mcp_servers/permission；[child_config.rs:84](D:/Desktop/codex-main/codex-rs/core/src/agent/child_config.rs:84) 最后重套父权限 | 这是重要版本差异。不能用旧源码宣称当前文档全部能力已具备，也不能靠 role prompt 实现权限隔离 |

**事实：**既有 [dynamic MCP probe:41](D:/Desktop/mihoyo-agent-project/research/probes/runtime_deepseek_dynamic_mcp_probe.py:41) 用官方 MCP `ClientSession`，并在 [handler:80](D:/Desktop/mihoyo-agent-project/research/probes/runtime_deepseek_dynamic_mcp_probe.py:80) 映射一个受限 function。已有本地 fixture 证据，不是“真实 DeepSeek → 生产游戏 MCP → 子 Agent”端到端验收。handler 第 95 行同步等 Future 的实现只适合作实验。

**项目决策：**业务目录可通过原生配置 MCP 或受限 dynamicTools→官方 MCP client 连接。二者择一按版本验收，不混称。A2A 的第一版调用入口仅放主 Coding Agent，直到子调用权限和路由被验证；这不限制内部子 Agent 的原生调查/实现能力。不要为了传递一项 QA 权限默认 fork 完整父上下文。

**协议适配边界：**[cooperation_protocol_probe.py:38](D:/Desktop/mihoyo-agent-project/research/probes/cooperation_protocol_probe.py:38) 的 `multi_agent_v1` namespace→function 映射及 [反向:69](D:/Desktop/mihoyo-agent-project/research/probes/cooperation_protocol_probe.py:69) 已有受限证据。它只应转换声明/调用名称并保留 call ID、参数、错误和时序；不能伪造 child result、替 Runtime spawn、静默改变任务或把未知工具放行。真实 Coding 还可能涉及 built-in custom/freeform tools、其他 namespace、tool search、MCP 与 V2 items；当前窄映射未覆盖，需逐项能力探针，不能扩成未经验证的通用 Responses 网关。

官方已在 2026-09-05 移除 `codex mcp-server`/独立 `codex-mcp-server`。旧 cookbook 将 Codex 包成 MCP server 再由另一个 Agents SDK 调度的办法不作为本项目路线；这与 Codex 作为 MCP client 连接外部工具是不同方向。[移除记录](https://learn.chatgpt.com/docs/changelog)

## 4. Adapter 新增职责与 A2A outbound 的挂接点

以下是**项目决策**，不是已存在的接口实现，也不声称官方 Codex 提供 A2A client：

| 层 | 应负责 | 不应接管 |
|---|---|---|
| Codex Runtime / 官方 SDK | 主/子线程采样、工具续步、原生委派、上下文及 thread/turn/item 协议 | 不承担业务 Candidate/Verification 状态的真值 |
| Coding 业务 Adapter | run 与 Runtime ID 关联、工具目录/审批/资源上限、事件投影、工作区授权、Candidate 打包、A2A outbound 和 receipt | 不另写 `model → tools → model`、不复制原生 spawn/wait 调度器 |
| 领域 MCP/Broker | 窄工具执行、路径/资源校验、结构化执行证据、独立超时与清理 | 不以 `verify_everything` 吞并 QA 规划、诊断与任务状态 |
| 独立 Verification Agent | 接收冻结 Candidate；自己规划检查、选择测试/反例/工具、形成有证据的通过/失败/不确定结论，拥有独立 task/state/预算 | 不修改 Candidate，也不信任 Coding 自述“测试通过”作为验证结果 |

建议挂接顺序：

1. Coding 在隔离工作区产出修改。Adapter 对实际 baseline/diff/文件清单、内容 hash、需求/场景引用、已有工具 receipts 做校验并冻结 Candidate Change。Candidate 至少关联 candidate ID、来源任务/作者、base revision、patch/artifact digest、目标环境/profile；不是最终自然语言摘要或可继续变化的工作目录路径。
2. 模型经窄工具请求委派，示意名为 `verification_submit(candidate_ref, verification_profile_ref)`。Adapter 校验授权与 artifact 完整性，持久化发送意图和幂等键，再用 **A2A client** 向独立 Verification 服务提交；快速返回 task ID/receipt。示意名称不是 A2A 官方方法名称，最终应按选定 A2A SDK 绑定。
3. `verification_status/result/cancel` 可以作为对应的窄能力；长任务由业务事件订阅器/作业宿主管理，避免让模型高频轮询烧 token。Coding 可以继续独立工作，也可结束当前 turn 显示 waiting_external；外部任务状态仍由 Verification 持有。
4. Verification 完成后，Adapter 校验 candidate digest、task/receipt、报告与证据引用，持久化事件并投递给同一个 Coding thread：idle 时普通 `turn/start`；仍 active 时按授权的 `turn/steer(expectedTurnId)` 语义投递。单线程只允许一个业务驱动者，防止 UI 请求、恢复器和回调竞争。投递是外部事件进入 Runtime，后续分析/工具动作仍由 Runtime 驱动。
5. Coding 可以据反馈产出新版 Candidate；新版本需新 digest/lineage 和相应验证任务。旧验证结果不能自动移用到变更后的文件。候选失败、验证失败或无法判定均是正常可记录结果，不能改为成功。

可直接使用的 SDK 边界：[thread_start/resume/read/fork:478](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:478)、[turn_start:650](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:650)、[turn_interrupt:701](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:701)、[turn_steer:708](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:708)。外部 A2A 请求与结果必须映射业务 ID，不能拿 native child ID 冒充独立 Verification task ID。

**当前项目事实：**现有 `src/agent_workbench/verification` 是本地 LangGraph/CLI 数值验证切片；不是已完成上述异步 A2A 服务。本报告不将其升级为“QA Agent 已验收”。Coding 自测与原生 Review 可以产生内部证据；用户要求的独立 Verification 仍需独立入口、状态、权限及 Agent 行为。

## 5. 权限、取消与恢复的具体风险

| 风险 | 本地依据 | 业务侧必须补的边界 |
|---|---|---|
| 默认审批不是人工审批 | [client.py:833](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:833) 缺省 handler 对 command/file approval 返回 accept；高层 [api.py:138](D:/Desktop/codex-main/sdk/python/src/openai_codex/api.py:138) 默认 auto_review，[_approval_mode.py:20](D:/Desktop/codex-main/sdk/python/src/openai_codex/_approval_mode.py:20) 映射自动审核 | 明确人工/拒绝/业务既有授权策略，未知 server request fail closed；不能用高层默认值声称“所有模型都 DeepSeek”或“所有越权均人工确认” |
| 服务端请求阻塞唯一 reader | [client.py:863](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:863) 在 reader 内同步执行 `_handle_server_request`，随后才读下一条 | 同步回调只作快速验证/提交；需要长审批/工具流时用经测试的异步 server-request 分流适配或当前 SDK 正式扩展点，不从回调重入等待同一 reader 的 RPC。只做 I/O 分流，不再实现 Agent Loop |
| SDK async cancel 不等于停止 Runtime | [async_client.py:313](D:/Desktop/codex-main/sdk/python/src/openai_codex/async_client.py:313) 在 start 被取消时释放未领取 subscription，没有发送 interrupt | 保存实际 thread/turn ID，显式 interrupt，并确认终态；断线后先 read/resume 对账，不盲目再 start |
| close 不代表完成 | [close_agent.rs:68](D:/Desktop/codex-main/codex-rs/core/src/tools/handlers/multi_agents/close_agent.rs:68) 记录 previous status 再关闭；[legacy.rs:107](D:/Desktop/codex-main/codex-rs/core/src/agent/control/legacy.rs:107) 关闭内存树可达子孙 | interrupted/closed/idle/transport-completed 与业务 completed 分开。汇总用子真实完成结果，不能 close 正在执行的子后声称其工作已完成 |
| 本地进程关闭不是外部任务撤销 | [client.py:283](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:283) terminate/kill app-server；没有替 A2A 服务撤销任务 | 分别记录 Runtime interrupt、MCP/worker cancel 和 A2A cancel acknowledgment；超时/断连记 unknown，不写“已撤销”。远端完成与取消竞态按 receipt 对账 |
| Runtime sandbox 不覆盖客户端工具宿主 | `item/tool/call` 由 Adapter 执行；旧 MCP probe 就在独立 Python/MCP 进程中跑 | Adapter/Broker 自身执行路径、网络、凭据、进程/容器权限；不可将 read-only Runtime 当成客户端工具的 OS 隔离 |
| 环境变量泄漏 | [client.py:258](D:/Desktop/codex-main/sdk/python/src/openai_codex/client.py:258) 合并整个父 `os.environ` | 用独立受信任启动进程和环境 allowlist；不要在多租户服务器中照搬 probe 短暂清空全局环境的技巧；日志不落密钥 |
| role/config 改变 provider 或权限预期 | child_config 的多层继承和 role override，且参考版本有差异 | 固定受信任角色来源/配置指纹；检查实际 root/child/review/恢复请求模型，未知模型拒绝；工具可见性与执行端授权双重约束 |
| resume 只恢复 Runtime 历史 | dynamic tool spec 可从 history 恢复，但外部 host/secret/receipt/job 并不在其中 | 重连工具宿主，核验 tool/schema/profile 版本、权限和 Candidate hash；先查询原作业，再决定是否恢复。不能因 checkpoint 存在就重放有副作用的工具 |
| 总预算/写入竞争 | native concurrency/depth 不是跨 A2A 全链资源账本；工作目录可能共享 | 业务账本在发送前预留、usage 已知才结算、未知保留；绑定全树及外部委派预算。工作区/文件所有权与合并验收独立做 |

App-server 当前文档仍对其 command/WebSocket 的 production 支持给出 experimental 限定，同时 Python SDK 页面标为 stable；不能将“SDK 发布稳定”推成“所有 transport、dynamicTools 与扩展都获得生产稳定保证”。本项目应走选定发布 SDK 的默认本地传输，并逐项记录实验性依赖。[App-server 文档](https://learn.chatgpt.com/docs/app-server)

## 6. 旧代码保留与降级清单

“保留”表示迁移候选/行为与测试资产，**不是原样复制即可生产可用**。本次均未改动。

| 具体路径/行 | 处置 | 原因与适用边界 |
|---|---|---|
| [runtime/agent.py:93](D:/Desktop/herta-agent-coding/backend/herta_agent/runtime/agent.py:93) | 降级为历史参考 | 第110行自写 model/tool loop、逐工具执行，迁移后由 Codex Runtime 替代 |
| [llm/openai_compatible.py:45](D:/Desktop/herta-agent-coding/backend/herta_agent/llm/openai_compatible.py:45) | 降级 | 当前走 Chat Completions、自定义 reply parser；不能套在 Codex 外再驱动一次模型循环 |
| [service/app.py:38](D:/Desktop/herta-agent-coding/backend/herta_agent/service/app.py:38) | 保留服务 composition/健康状态思路，替换 Runtime 组装 | 第82/98/109行组装旧 Provider/Agent/RunManager；迁移入口改为 SDK + Adapter |
| [service/runs.py:108](D:/Desktop/herta-agent-coding/backend/herta_agent/service/runs.py:108)、[同文件:220](D:/Desktop/herta-agent-coding/backend/herta_agent/service/runs.py:220) | 保留 admission/终态/释放所有权规则；重写 Runtime 接口适配 | `Session.restore → self.agent.run` 是旧循环边界；业务 run 映射 official thread/turn，并跟踪外部 task |
| [storage/sqlite.py:553](D:/Desktop/herta-agent-coding/backend/herta_agent/storage/sqlite.py:553) | 保留“启动不自动重放工具”的安全语义；扩大恢复模型 | 旧 recover 仅把 created/running 标 interrupted，没有外部任务对账；不能作为 A2A/Runtime 恢复完成证据 |
| [coding.py:34](D:/Desktop/herta-agent-coding/backend/herta_agent/coding.py:34) | 保留证据真实性/源码不可信等规则；重写上下文入口 | 旧提示绑定 list/grep/apply_patch/run_tests 和副本，不能与原生工具名/权限配置混用 |
| [workspace.py:19](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/workspace.py:19) | 保留副本所有权、拒绝链接、失败清理等测试；升级为任务/候选工作区 | 单一 `.coding-agent-workspace` 持久副本没有 revision/分支/候选不可变性；不足以支撑多任务、多作者与独立 QA |
| [paths.py:33](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/paths.py:33) | 保留路径排除/穿越/Windows 路径案例 | 是应用路径校验，不是 OS sandbox；权限仍由执行宿主强制 |
| [run_tests.py:21](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/run_tests.py:21)、[同文件:142](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/run_tests.py:142) | 保留结构化报告判定、取消时持有锁直至清理等资产 | 工具成功不等于测试通过；当前只覆盖 pytest，不是完整 Verification Agent |
| [sandbox.py:23](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/sandbox.py:23)、[同文件:113](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/sandbox.py:113)、[同文件:172](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/sandbox.py:172) | 保留环境 allowlist、固定 Docker 参数、确认容器消失的原则与测试 | 仅支持该 Docker/pytest profile；需扩展目标环境与候选挂载策略，不宣称覆盖 Unity/宿主进程/远端取消 |
| [apply_patch.py:22](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/apply_patch.py:22) | 降级为 patch 校验案例；不保留第二套同名 Runtime 写工具 | 原生编辑由 Runtime；Candidate 层核对实际 diff/hash。领域资源写入若有特殊事务，另走明确业务工具 |
| [review_mode.py:21](D:/Desktop/herta-agent-coding/backend/herta_agent/service/review_mode.py:21)、[同文件:41](D:/Desktop/herta-agent-coding/backend/herta_agent/service/review_mode.py:41) | 保留 finding schema/证据规则；降级单 Agent review 模式 | submit_review 只记录结构化结果，不证明测试，更不是独立 QA Agent |
| [service/sse.py:11](D:/Desktop/herta-agent-coding/backend/herta_agent/service/sse.py:11)、[run-reducer.ts:12](D:/Desktop/herta-agent-coding/frontend/src/state/run-reducer.ts:12)、[sse-parser.ts:2](D:/Desktop/herta-agent-coding/frontend/src/api/sse-parser.ts:2) | 保留 UI 流与replay/终态测试资产，新增事件投影 | 需要呈现 Runtime thread/turn/item、审批、child 与 A2A task，不能继续把旧 llm/tool 事件当成全部事实 |
| [backend-process.ts:23](D:/Desktop/herta-agent-coding/frontend/electron/backend-process.ts:23)、[main.ts:16](D:/Desktop/herta-agent-coding/frontend/electron/main.ts:16)、[preload.ts](D:/Desktop/herta-agent-coding/frontend/electron/preload.ts) | 保留桌面启动/受限桥接与所有权设计 | 增加 SDK/app-server 进程与外部作业生命周期观测；不将关闭窗口等同于所有远程工作撤销 |
| [cooperation_protocol_probe.py:38](D:/Desktop/mihoyo-agent-project/research/probes/cooperation_protocol_probe.py:38)、[live runner:392](D:/Desktop/mihoyo-agent-project/research/probes/collaboration_live_runner.py:392) | 冻结保存，只作协议/预算/审计测试素材 | 是窄实验 relay，含 buffered SSE、固定权限及有限输入类型，不是生产 Coding Adapter |
| [profile runner:42](D:/Desktop/mihoyo-agent-project/research/probes/collaboration_profile_runner.py:42)、[同文件:122](D:/Desktop/mihoyo-agent-project/research/probes/collaboration_profile_runner.py:122) | 固定 1+3 / A+6 完全降为 benchmark profile | 产品不得 enum 锁死所有子任务、强制三角色或机械六轮 |

旧 README/current_context 中的测试与实模数字是历史记录，本次没有重跑，也不把它们当迁移后验收结果。新仓库现有 Verification 切片保留数值工具/契约/receipt 资产，由独立 Verification 审计决定扩展；Coding 不另造一个包办它的 MCP。

## 7. 下一阶段必须验证的最小集合

以下是**待验计划**，没有在本次执行，也不代表额外付费授权：

1. **版本配对与拒绝路径：**当前发布 Python SDK 默认 pinned runtime；schema/namespace/naming/SSE；未知工具和模型拒绝；审批服务端请求可并发接收，回调不阻塞 reader，断连不默认 accept。
2. **真正动态委派：**至少简单任务选择0子、复杂任务自选不同数量/职责；记录实际 provider/model/IDs/工具/完成性。允许单 Agent 做完；验收不要求固定团队，也不以子数衡量质量。
3. **工具传播：**fresh/fork/resume 三种路径分别验证 dynamicTools/MCP 的可见性、调用路由、call ID、宿主授权与错误回传；不要只检查 schema 声明。
4. **Coding → Candidate：**真实读写/测试后冻结实际 artifact；并发编辑冲突、dirty baseline、Candidate 版本错配必须明确失败。补原生 shell/apply_patch 与 DeepSeek wire 兼容，不用闭卷 packet 成功替代。
5. **Candidate → 独立 QA：**A2A submit/status/result/cancel、独立 Agent 规划与工具证据、无 Candidate 修改；检查请求重试、重复完成回调、未知结果、崩溃后对账、不支持取消与取消完成竞态。
6. **端到端恢复/清理：**用户停止、预算耗尽、app-server 死亡、MCP 断线、远端仍运行都分别验证。以 Runtime 终态、worker/container 清理、A2A terminal receipt 三层证据判断，避免只看父线程 idle。

## 8. 冻结证据未变

本次重新核验：

- `collaboration_live_runner.py`：`360109c34b2a3613c1fe019437c7deb8666a04914b6bcfe377c682c73d2f3b19`。
- `collaboration_profile_runner.py`：`f4528c0a22a6def099b77c6db41459ed5fabd56f86f587fb3776d55a7729a61c`。
- `collaboration-confirmation-native-audit-20261004.json`：`d12ca78c8ce3caaf21a0a2415b7202229cce03c582d725cadead3c75435a38de`。

已读本地证据还包括 [runtime-deepseek-assessment](D:/Desktop/mihoyo-agent-project/research/evidence/runtime-deepseek-assessment.md)、[cooperation protocol README](D:/Desktop/mihoyo-agent-project/research/evidence/cooperation-protocol-20261004-175241/README.md)、[当前上下文](D:/Desktop/mihoyo-agent-project/current_context.md)。旧记录按时间和明确范围解释；本报告提出新产品边界，不改写旧结果。
