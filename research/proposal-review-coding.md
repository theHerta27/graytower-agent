# 总体方案独立审查：Coding / Runtime 边界

审查日期：2026-10-03。只读审查 `TECHNICAL_PROPOSAL.md`、`IMPLEMENTATION_ROADMAP.md`，对照任务书、Coding审计与本地Codex源码。下列行号对应本次读取版本；未修改主文档。

## 1. [P1] SDK补丁必须同时建立人工审批路由，不能只修reader阻塞

**定位：** [总体方案:184](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:184)、[总体方案:189](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:189)、[路线:28](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:28)。

方案已明确有界队列、handler、超时和迟到答复，但列出的SDK最小补丁只把handler贯穿API，没有明确改变高层 `ApprovalMode.auto_review` 的路由选择。按现源码实施这份清单，能够获得一个不阻塞的UI handler，却仍可能把本应由用户决定的审批送到上游自动评审路径，不能兑现“人工审批工作台”。

源码依据：`sdk/python/src/openai_codex/_approval_mode.py:13–35` 只有 `deny_all` 与 `auto_review`，后者明确映射 `on_request + ApprovalsReviewer.auto_review`；`api.py:138–157` 和 `:396–416` 在同步/异步 thread_start 中采用它。低层生成协议已有 `ApprovalsReviewer.user`（`generated/v2_all.py:260–263`），而App Server的 `thread.rs:89–92` 明确该字段控制当前thread和后续turn的审批接收者。仅把默认 accept 改成 decline 或增加 handler，均不能代替路由配置。

**具体修订：** 在G0和SDK补丁范围增加人工 `user` 路由（新增高层manual模式或由adapter使用低层参数），同时锁定 `approval_policy`、`approvals_reviewer` 与 sandbox/profile；检查thread start/resume/turn override实际返回的有效配置，禁止恢复时悄悄回到auto_review。验收应通过真实App Server触发一个必须审批的操作，证明UI拒绝/接受/取消均控制实际执行，且没有先经过另一条自动批准路径。区分“允许范围内无需提权的操作”和“必须由用户审批的升级”，不要改成每一步操作都要求审批。

## 2. [P1] MCP/Broker候选进程的隔离责任没有落实到可执行后端

**定位：** [总体方案:93](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:93)、[总体方案:119](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:119)、[总体方案:203](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:203)、[总体方案:240](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:240)、[路线:30](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:30)、[路线:75](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:75)。

架构让Codex调用Python MCP/Broker，由Worker执行候选；执行方案又总体依靠“Codex原生受限执行”。两条链路不是同一个权限边界：Codex shell/unified_exec的沙箱不会自动套到已连接的MCP服务所启动的Python/.NET/Unity子进程。主文档要求候选隔离、Unity必须受限，但没有明确由谁、通过哪个受验证后端为MCP Worker创建该边界。如果实现者在Python MCP工具内直接 `subprocess` 启动固定profile，入口校验虽正确，仍可能在控制服务权限下执行模型修改的源码。

源码依据：`codex-rs/core/src/tools/handlers/mcp.rs:196–264` 准备并调用MCP工具；`codex-rs/codex-mcp/src/connection_manager.rs:975–1033` 获取已连接client并执行RPC `call_tool`。这不等于经过shell的 `ToolOrchestrator`/sandbox进程创建。Codex专项审计 `research/codex-source-audit.md:91` 已明确此边界，建议将它升级为主方案的执行约束，避免知识仅留在调研附件。

**具体修订：** 加一张执行所有权表：Codex内置shell由Codex创建受限进程；MCP/Broker是控制面，只投递作业；Python/.NET/Unity候选Worker由独立、锁定且经过G0验证的受限执行后端创建，明确权限身份、读写根、网络策略、取消/清理责任。G0必须分别从实际shell路径和**实际MCP工具路径**触发工作区外写、网络、子进程/取消探针，并确保模型不能绕过Broker直接取得控制面凭证或隐藏验收目录。若没有可用的原生隔离后端，保留Python Docker路径，其他自动执行标为阻塞或明确的人工信任流程，不能凭“profile固定”和“单独进程”宣称隔离。

这项意见不是要求首版创造新的Windows沙箱，而是要求G0先证明所选可复用执行后端能覆盖真正的MCP/Worker调用链，再实施上层工具。

## 3. [P2] “空review均拒绝”与合法无问题评审的验收相冲突

**定位：** [路线:77](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:77)，对照[路线:132](D:/Desktop/mihoyo-agent-project/IMPLEMENTATION_ROADMAP.md:132)、[总体方案:172](D:/Desktop/mihoyo-agent-project/TECHNICAL_PROPOSAL.md:172)。

M2退出条件把“空review”与全skip、不存在路径、陈旧回执并列为拒绝通过项。按字面实现会拒绝成功提交 `findings=[]` 的干净diff，迫使Reviewer找问题才能结束，恰好重引入旧评测刻意避免的误报激励。路线后面又要求10个干净/仅风格diff的评审集，因此这里会直接影响状态机与评分器。

**具体修订：** 改为拒绝“未成功提交结构化Review、缺少reviewed revision/scope或证据对账失败”；明确 `findings=[]` 是合法结果，须绑定被审查候选hash、范围、完成状态并记录成功收据。finding存在时才执行文件/行号/变更区间校验；不以finding数量决定任务是否完成。对合法空提交和无提交的普通最终文本各设一项回归。
