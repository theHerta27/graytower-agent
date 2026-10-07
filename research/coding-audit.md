# 现有 Herta Coding Agent 源码审计与复用建议

审计日期：2026-10-03。对象：`D:\Desktop\herta-agent-coding`。本报告供项目群方案决策使用，不是 V2 实施或正式游戏仓库验收。

## 1. 推荐结论

建议保留现有产品的 React/Electron 交互组件、业务验收经验、离线测试与微型评测资产；将它视为已经打通一个小型 Coding Agent 闭环的工程原型。新项目优先复用 Codex 的通用任务执行 Runtime，把自主贡献集中在游戏仓库任务上下文、任务工作区、变更约束、Windows/.NET/Unity 工具接入、结构化验证证据、评审完成判定和界面产品化。**不建议继续把 Herta Runtime 扩成另一个通用 Coding Runtime 作为主路线。**

这个判断来自现有实现的收益与缺口：它的单轮模型—工具循环、取消竞争、持久提交、容器回收已经有明确代码和测试，值得保留作机制讲解与对照基线；但要支持实际游戏任务，还需要增加上下文预算、压缩、项目指令、审批、Git/P4、任务级隔离、引擎执行、事件恢复、usage、MCP 与运行可观测性。补齐这些通用能力会长期分散游戏业务投入。Codex 的具体接入层和是否需要修改上游，应结合项目群的 Codex 源码专项报告决定；本报告没有仅凭 Herta 缺口宣称 App Server 能直接覆盖全部需求。

与 JD 的对应重点：AI 产品全栈岗位的“代码理解、自动修改、调试、评审、上下文、检索、流式交互、任务执行链路”已有原型基础；“真实开发环境的 Git/终端/索引/P4”“跨端 WebView”“效果评估”仍是实际工程贡献空间。游戏 Agent 岗位要求的游戏生产场景、稳定可控、调试与回放，应通过接入同一游戏底座的真实 C# 代码任务体现，不能由 Python 微型夹具替代。

## 2. 基线、文档与审计边界

- 已完整阅读项目群 `mihoyoJD.md`、`PROJECT_BRIEF.md`，以及本项目 `README.md`、`current_context.md`，随后沿实际代码链路检查。
- 分支 `coding-agent`；HEAD `e121d8207f74af98e22f2c100348b05160a0560b`；提交时间 `2026-10-02T21:15:24+08:00`；提交说明 `fix: checkpoint verified Docker sandbox lifecycle and reports`。
- 初始和结束 `git status --short` 相同：未跟踪 `current_context.md`、六份验收/评测报告及 `docs/superpowers/`。`git diff --stat`、`git diff --check` 无输出；没有已追踪源码改动。具体清单见 [状态日志](D:/Desktop/mihoyo-agent-project/research/coding-git-status-20261003.log)。Git 读取用户级全局 ignore 时有权限警告；这不影响已追踪差异检查，不把输出等同对所有忽略文件的完整盘点。
- `current_context.md:6` 记录 checkpoint 未 push；本次没有访问远端验证该历史状态，也没有提交、推送。
- `D:\AGENTS.md`、`D:\Desktop\AGENTS.md`、两个相关项目根目录及项目内检索均未发现适用 `AGENTS.md`。
- 当前授权是材料调研、必要验证与总体方案。旧 `current_context.md:43` 的暂停要求作为历史停点记录；本次只开展审计，没有正式重构、接入游戏仓库或新增模型样本。
- 没有调用真实模型/Embedding、读取密钥或凭据文件、安装依赖、启动 Docker daemon/GUI、启动 Electron GUI。现有测试使用 Mock/离线 Provider，包含本机 loopback 服务及临时子进程。新增内容只在项目群 `research` 目录；探针临时夹具退出后清理。

## 3. 实际链路与可复用事实

| 链路 | 已实现行为 | 精确代码依据 |
| --- | --- | --- |
| Renderer 输入 | `ChatStore.send` 检查状态、建立会话、生成 clientRequestId，交给 bridge；切换会话、草稿、历史状态和发送不确定态已有处理 | [chat-store.ts:31](D:/Desktop/herta-agent-coding/frontend/src/state/chat-store.ts:31)，[App.tsx:9](D:/Desktop/herta-agent-coding/frontend/src/App.tsx:9) |
| Electron IPC | preload 暴露窄接口；main 检查发送 frame，关闭 Node integration，启用 context isolation/sandbox；禁止外部导航/新窗口。IPC 事件批次需要 Renderer ack，避免无限堆积 | [preload.ts:4](D:/Desktop/herta-agent-coding/frontend/electron/preload.ts:4)，[main.ts:68](D:/Desktop/herta-agent-coding/frontend/electron/main.ts:68)，[main.ts:97](D:/Desktop/herta-agent-coding/frontend/electron/main.ts:97) |
| 后端进程所有权 | Electron 启动指定 Python/host，使用 stdio ready/shutdown 协议；Python 监听随机 loopback 端口，stdin EOF 触发停止；停止超时仅终止拥有的进程树 | [backend-process.ts:46](D:/Desktop/herta-agent-coding/frontend/electron/backend-process.ts:46)，[backend-process.ts:117](D:/Desktop/herta-agent-coding/frontend/electron/backend-process.ts:117)，[backend_host.py:17](D:/Desktop/herta-agent-coding/frontend/desktop/backend_host.py:17) |
| 流式传输 | main 发起 POST `/sessions/{id}/runs`，解析 SSE 后经 IPC 回 Renderer；事件校验 session/run，单批受条数和字节上限限制；断流后读取持久事实核对 | [run-transport.ts:22](D:/Desktop/herta-agent-coding/frontend/electron/run-transport.ts:22)，[chat-store.ts:77](D:/Desktop/herta-agent-coding/frontend/src/state/chat-store.ts:77) |
| 服务装配 | 启动 SQLite，修复中断状态；环境变量选择 coding/review，打开一个持久副本，创建对应 registry、context 与 Agent；coding 启动检查 Docker，失败仍可聊天但 health 报测试不可用 | [app.py:38](D:/Desktop/herta-agent-coding/backend/herta_agent/service/app.py:38)，[app.py:139](D:/Desktop/herta-agent-coding/backend/herta_agent/service/app.py:139) |
| Run 接纳 | 单进程服务，默认最多 4 个 Run，同会话只能有 1 个；接纳先预留内存所有权，再入库 user/Run；取消与最终提交竞争有明确胜者 | [settings.py:13](D:/Desktop/herta-agent-coding/backend/herta_agent/service/settings.py:13)，[runs.py:125](D:/Desktop/herta-agent-coding/backend/herta_agent/service/runs.py:125)，[runs.py:201](D:/Desktop/herta-agent-coding/backend/herta_agent/service/runs.py:201) |
| 持久化 | 完整 assistant/tool 消息先持久提交后更新内存；最终文本与 completed 状态同事务写入；SQLite 对 session sequence 和活跃 Run 有唯一约束 | [turn.py:25](D:/Desktop/herta-agent-coding/backend/herta_agent/service/turn.py:25)，[sqlite.py:25](D:/Desktop/herta-agent-coding/backend/herta_agent/storage/sqlite.py:25)，[sqlite.py:465](D:/Desktop/herta-agent-coding/backend/herta_agent/storage/sqlite.py:465) |
| Agent Loop | 每轮冻结 system context；每步拼接全量历史；默认最多 8 次请求；每批最多 4 个 tool calls，依次执行；末步返回 tool calls 时先记录调用再以步数耗尽停止，不执行这些调用 | [agent.py:93](D:/Desktop/herta-agent-coding/backend/herta_agent/runtime/agent.py:93)，[config.py:11](D:/Desktop/herta-agent-coding/backend/herta_agent/config.py:11) |
| Provider | 手写 Chat Completions HTTP/SSE adapter；完整工具调用和 finish_reason 校验后才提交；无自动重试；当前不承载 reasoning、usage、输出 token 上限等可配置协议字段 | [openai_compatible.py:45](D:/Desktop/herta-agent-coding/backend/herta_agent/llm/openai_compatible.py:45)，[streaming.py:68](D:/Desktop/herta-agent-coding/backend/herta_agent/llm/streaming.py:68)，[messages.py:25](D:/Desktop/herta-agent-coding/backend/herta_agent/runtime/messages.py:25) |
| 工具执行 | registry 白名单 + Pydantic JSON 参数校验；每工具 timeout；结构化 ok/data/error；CancelledError 向 Runtime 传播；call ID 通过 ContextVar 关联容器名 | [executor.py:42](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/executor.py:42)，[coding/__init__.py:10](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/__init__.py:10) |
| 代码副本与补丁 | 首次复制到源仓库内 `.coding-agent-workspace`，排除 `.git`、依赖、`.env*` 等；严格文本 unified diff，校验所有 hunk 后写盘，写异常尝试回滚；不支持 rename/binary | [workspace.py:19](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/workspace.py:19)，[paths.py:8](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/paths.py:8)，[apply_patch.py:22](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/apply_patch.py:22)，[apply_patch.py:130](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/apply_patch.py:130) |
| 测试执行 | Agent 的 `run_tests` 固定执行 Docker 中 pytest；共享副本写锁；stdout/JSON 限额；检查退出码、条目、汇总、阶段/subtest 一致性；finally 保留锁直到容器回收结束 | [run_tests.py:21](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/run_tests.py:21)，[run_tests.py:92](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/run_tests.py:92) |
| Docker 边界 | Linux containers、禁止拉取、无网络、1GiB/2 CPU/128 PID、uid 10001、只读 rootfs、临时 tmpfs；仅挂载可写副本；kill/rm 后查询唯一容器名，确认清理 | [sandbox.py:84](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/sandbox.py:84)，[sandbox.py:113](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/sandbox.py:113)，[sandbox.py:172](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/sandbox.py:172) |
| Review | 独立只读 registry，仅 read/list/grep/submit_review；category/title/path/line/explanation 结构化，UI 有专门卡片；仍使用同一 Agent Loop | [review_mode.py:21](D:/Desktop/herta-agent-coding/backend/herta_agent/service/review_mode.py:21)，[review_mode.py:41](D:/Desktop/herta-agent-coding/backend/herta_agent/service/review_mode.py:41)，[ReviewActivity.tsx:3](D:/Desktop/herta-agent-coding/frontend/src/components/ReviewActivity.tsx:3) |

已实现的价值主要在明确区分“流式临时显示”和“完整持久消息”、“工具成功”和“测试通过”、以及取消期间的执行资源所有权。这些应迁移为新产品的验收要求和回归用例，而不是为了保留旧代码继续维护平行的通用 Runtime。

## 4. 面向真实游戏仓库的缺口

### 4.1 工作区、Git 与任务范围

当前副本归属于**源目录**，没有 task ID、基线 commit、dirty 文件清单、分支、change set 或可回写补丁包。所有会话在一次服务中使用同一个副本；写工具的单锁可防止补丁与测试同时写，却不能让不同任务获得独立基线。副本上限 10,000 文件/100MiB，首次复制后仅检查 source 路径和 version marker，重开直接复用。源仓库更新不会同步，旧改动也不会自动消失。见 [workspace.py:19](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/workspace.py:19)。

`.git` 被排除，工具表没有 Git/P4、终端、diff 获取/提交；patch 只受仓库边界控制，没有任务级允许目录、禁止修改测试、场景/资产白名单等策略。模型可以请求修改副本内测试。历史评测“测试未改”是事后 hash/轨迹审计结果，不是产品强制策略。

推荐新产品使用每任务独立 Git worktree/受控副本，持久化 baseline commit、用户原始 dirty、patch、验证记录和最终交付范围；第一版先 Git，P4 后续按真正仓库需求适配。不要把游戏原目录直接设置成当前 `HERTA_CODING_REPO_ROOT` 就宣称已完成集成。

### 4.2 Unity/.NET 执行与 Docker pytest

`run_tests` 的参数固定为测试目录和 `test*.py`，容器命令直接写死 `python -B -m pytest`（[run_tests.py:87](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/run_tests.py:87)、[sandbox.py:151](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/sandbox.py:151)）。镜像构建只接受 pyproject + uv.lock 并导出 requirements（[build-coding-sandbox-image.ps1:14](D:/Desktop/herta-agent-coding/scripts/build-coding-sandbox-image.ps1:14)、[build-coding-sandbox-image.ps1:51](D:/Desktop/herta-agent-coding/scripts/build-coding-sandbox-image.ps1:51)）。没有 dotnet build/test、Unity EditMode/PlayMode/构建、NUnit/XML 解析、引擎日志或产物收集。

因此，这套 Docker pytest 可继续验证 Python 工具/微型夹具，但**不能代表游戏 C# 代码、Unity 项目或真实客户端已验证**。新执行接口应按验证类型定义，例如规则库 build/test、确定性战斗回放、Unity 测试和客户端 smoke，分别保留命令、版本、退出码、用例、日志、超时、取消与产物。Windows 原生受限执行是否满足所需隔离，应由 Codex/平台专项验证；Unity 编辑器许可、batchmode 和本机进程边界也需单独验证，不能通过一句“换镜像”解决。

Docker 现有边界值得保留为 Python adapter 的模式：只传所需环境、call ID 关联资源、清理不可被重复取消打断、清理失败不能伪报完成。它不是所有游戏工具的统一执行后端。

### 4.3 检索、上下文、项目知识

`grep_code` 是逐文件 UTF-8 **字面子串**扫描；最多 2,000 文件/16MiB，单文件超过 1MiB 或二进制会跳过，返回命中行与 truncated/skipped 信息（[grep_code.py:14](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/grep_code.py:14)）。没有语义索引、符号/引用检索或增量索引。历史目录检索缺陷已修复为相对路径检查，不能继续沿用“根目录 grep 不可用”的旧结论（[paths.py:79](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/paths.py:79)，本轮相关回归在 206 项中）。

原角色 RAG 并非代码 RAG：`create_app` 仅在 `coding is None` 时加载/注册知识检索（[app.py:83](D:/Desktop/herta-agent-coding/backend/herta_agent/service/app.py:83)）。Coding system 是硬编码说明，不加载 AGENTS/项目规则；`ContextSnapshot.build_messages` 每次发完整历史，没有 token 预算、压缩或证据挑选（[coding.py:34](D:/Desktop/herta-agent-coding/backend/herta_agent/coding.py:34)、[context.py:27](D:/Desktop/herta-agent-coding/backend/herta_agent/runtime/context.py:27)）。

首版先建立游戏代码地图、项目指令、精确文本/符号检索与引用证据，按真实游戏任务测检索命中和上下文成本；没有证据前不因存在旧 RAG 组件就追加向量数据库。

### 4.4 审批、恢复和可观测性

- `propose_plan` 仅返回标题/理由清单，UI明确“提议不代表完成”；没有执行状态、计划审批或写前强制 gate（[plan.py:16](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/plan.py:16)、[PlanActivity.tsx:3](D:/Desktop/herta-agent-coding/frontend/src/components/PlanActivity.tsx:3)）。工具权限由启动时 registry 决定，运行中无审批请求/决策协议。
- SQLite 启动恢复将 created/running Run 改为 interrupted，未落库工具结果补为“未知；未重新执行”；这能避免盲目重放，但不支持继续执行、回滚补丁、恢复终端或核对 daemon 骤停的遗留容器（[sqlite.py:509](D:/Desktop/herta-agent-coding/backend/herta_agent/storage/sqlite.py:509)、[sqlite.py:553](D:/Desktop/herta-agent-coding/backend/herta_agent/storage/sqlite.py:553)）。文件副作用与 SQLite 事务并不原子，遇到中断必须检查工作区。
- SSE 是在途消息通道，非持久事件日志；服务明确拒绝 Last-Event-ID 重放（[app.py:187](D:/Desktop/herta-agent-coding/backend/herta_agent/service/app.py:187)）。历史恢复重建消息/工具卡片，不能称为逐 token 执行回放。断线会走取消/终态核对，而非后台持续任务自动重连（[sse.py:33](D:/Desktop/herta-agent-coding/backend/herta_agent/service/sse.py:33)）。
- SSE parser 接受 usage frame 后直接丢弃；ModelReply/SQLite 无 usage 字段（[streaming.py:88](D:/Desktop/herta-agent-coding/backend/herta_agent/llm/streaming.py:88)、[messages.py:59](D:/Desktop/herta-agent-coding/backend/herta_agent/runtime/messages.py:59)、[sqlite.py:29](D:/Desktop/herta-agent-coding/backend/herta_agent/storage/sqlite.py:29)）。历史评测脚本单独采集的 usage 不能当作产品已实现用量监控。
- 本机 FastAPI 的定位是单用户 loopback；当前公开路由没有鉴权/审批桥接。若扩展浏览器、UE/Maya WebView 或远程访问，需重新定义连接身份与安全边界，不能直接外放端口。

### 4.5 评审与验收语义

Review 模式结构化约束很薄：只检查 line 为正数且顺序正确，路径只做 `exists=False` 的仓库边界检查，不核对基线/修改后文件、实际行数、diff 变更区间或引用证据（[review_mode.py:21](D:/Desktop/herta-agent-coding/backend/herta_agent/service/review_mode.py:21)、[review_mode.py:42](D:/Desktop/herta-agent-coding/backend/herta_agent/service/review_mode.py:42)）。普通最终文本在 Loop 中即可完成 Run，强制结构化提交依赖 prompt 和事后人工验收。新产品应独立记录 review completion、reviewed revision、diff scope 和 findings 校验，不让通用 Run completed 代替评审完成。

测试 parser 对“收集到一个但全部 skipped 的测试、exit=0”也返回 status=passed，因它要求 total>0/failed=0，没有要求 passed>0（[run_tests.py:73](D:/Desktop/herta-agent-coding/backend/herta_agent/tools/coding/run_tests.py:73)）。这是当前聚合规则，不等于执行了有效游戏验证。新业务验收应要求指定套件和必要用例真实执行，区分 passed、skipped、inconclusive。

## 5. UI 与资产迁移取舍

| 资产 | 建议 | 理由/边界 |
| --- | --- | --- |
| Composer、会话侧栏、流式消息、历史核对 | 保留交互和组件，重新适配 runtime bridge | 流式/取消/历史 UX 有离线覆盖；目前 `App` 直接依赖 `window.herta`，不是开箱即用的浏览器/WebView 产品 |
| Tool/Plan/Test/Review 卡片 | 保留展示思路，重设数据契约 | 当前卡片识别具体旧工具名和结果形状；新接口需要引擎测试、审批、diff、产物和 usage 卡片 |
| Electron 后端进程管理 | 保留所有权/关闭设计与测试；是否继续启动 Python 按新进程划分决定 | 机制清晰，但不能同时让 Electron、Python 和 Codex 三方争夺同一 Run 生命周期 |
| FastAPI/SQLite 旧 Session Store | 保留历史只读查看或导出；新业务存储只记录产品任务、证据、审批与 Runtime ID 映射 | 不建议将旧消息表变成 Codex 对话事实的第二主库，避免双写和恢复冲突 |
| Herta Runtime/Provider | 冻结为学习与对照基线 | 能解释事务、取消、SSE 和工具协议；扩到通用生产 Runtime 的维护成本高 |
| Python 工具与 Docker adapter | 保留工具结果校验/生命周期经验及回归，按适配层需要选择复用 | pytest 是 Python 适配器；Unity/.NET 必须独立实现真实验证链路 |
| 10 Debug + 8 Review 样本 | 保留为快速冒烟和失败分析材料 | 过小且以 Python 为主，不能承担游戏仓库效果结论；需要修订新评测契约但不改写历史分数 |
| 原 Persona、角色知识库与图像 | 与 Coding 主流程分离 | Coding 已绕开角色 RAG；NPC 可复用存储/检索设计经验，但玩家记忆与业务数据不能混用 |

当前 UI 仍主要是聊天：没有任务仓库选择、Git diff 导航、审批面板、引擎产物视图、Review 范围选择和正式 Settings。coding/review 通过环境变量切换并重启服务。组件可复用不等于现有界面已经满足完整游戏研发工作台。

## 6. 历史验收：能证明什么

已阅读历史报告，并只读抽查 `.local` 中的结构化结果及 Electron SQLite；没有重发模型请求。本次确认这些证据文件存在且关键计数一致，不宣称重新完成了历史全部 hash、截图、Docker 隔离或供应商原始流复验。

| 历史记录 | 可以引用的结论 | 不能外推的结论 |
| --- | --- | --- |
| 2026-10-02 checkpoint 回归 | 文档记录 216 passed/3 skipped、前端24、Electron10，启用真实 Docker；[报告:12](D:/Desktop/herta-agent-coding/docs/coding-agent-electron-real-model-e2e.md:12) | 本次未跑 Docker/Electron，不把这些写成今天结果 |
| Debug 累计10例 | 多批次共66次请求；严格 D/F/T/U 完整通过6/10；[batch2:87](D:/Desktop/herta-agent-coding/docs/coding-agent-full-eval-batch2.md:87) | 不是同一基线单次大评测，也不是“10例模型全通过” |
| Debug 评分契约 | 05/07/10 正向目标与原测试红→绿，但严格兼容性判失败；参考补丁本身也存在同类 None 行为变化；[batch2:57](D:/Desktop/herta-agent-coding/docs/coding-agent-full-eval-batch2.md:57) | 不能将参考补丁红→绿当成满足全部语义，更不能将这些失败全部归于模型不会修目标 bug |
| Review 8例 | 7例结构化提交，5个标注命中，1个误报；P=83.33%、R=100%、F1=90.91%；07 clean 因最后一步限额未提交；[Review:9](D:/Desktop/herta-agent-coding/docs/coding-agent-review-real-model-eval.md:9) | 不是8/8完成；是微型混合 style/bug/tests 的统一口径，不是真实游戏仓库 bug recall |
| Review 模型条件 | 使用旧 checkpoint c8afb786 的独立快照、max_tokens=1024、thinking disabled、max_steps=4；[Review:124](D:/Desktop/herta-agent-coding/docs/coding-agent-review-real-model-eval.md:124) | 不能当作现正式桌面默认参数的完整协议兼容性证明 |
| 正式 Electron 单场景 | 当前 checkpoint 正式 Provider 直连；3请求、2文件读取+1 Docker pytest，1 passed；无 patch；15.167秒，重开恢复和清理；[E2E:26](D:/Desktop/herta-agent-coding/docs/coding-agent-electron-real-model-e2e.md:26) | 不是自主修改游戏代码、长任务、审批、thinking 多轮或所有桌面功能验收 |
| Docker 历史安全验收 | 自身靶场网络/资源/uid/取消清理有报告；[迁移记录:126](D:/Desktop/herta-agent-coding/docs/run-tests-sandbox-plan.md:126) | 没有磁盘配额、报告不是防恶意伪造证明，daemon/服务骤停及外部不可信游戏仓库未验收（同报告末段） |

本次只读证据核对：Electron `result.json` 为 passed=true、requestCount=3、completedRequests=3、deltaCount=342、historyRestored=true、ownedContainersRemaining=[]、usage=null；`independent-verification.json` 记录 301 文件、7条持久消息、1个独立 Run。直接以 SQLite URI `mode=ro` 查询得到 1 Session / 1 Run / 7 Message，状态 completed。Review `assessment.json.quality` 与报告 TP=5/FP=1/FN=0、7/8 可评分一致。结构化结果仍是历史运行产物，不是独立供应商原始响应审计。

文档有明显新旧并存问题：README 的启动示例仍进入旧 `D:\Desktop\herta-agent`（[README:10](D:/Desktop/herta-agent-coding/README.md:10)、[README:21](D:/Desktop/herta-agent-coding/README.md:21)、[README:32](D:/Desktop/herta-agent-coding/README.md:32)），多处绝对链接也指向旧目录；178项、195项、212项、216项是不同阶段，不能混为当前状态。walkthrough:122仍称后续 Debug/Review待补验，已被后续报告推进。建议下一实施阶段统一唯一启动入口、相对链接、最新验证索引，并将旧阶段教程明确放为历史记录。本次没有修改这些旧文档。

## 7. 本轮实际离线验证与结果

运行环境：Windows；项目已有 Python **3.12.13**、Node **v22.16.0**、npm **10.9.2**，Vitest实际输出 **3.2.7**。未安装或升级依赖。

### 7.1 原有后端全量离线回归

在 `D:\Desktop\herta-agent-coding` 运行：

```powershell
$env:HERTA_DOCKER_TESTS='0'
$env:HERTA_SERVICE_PROVIDER='demo'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\Desktop\herta-agent-coding\backend'
.\.venv\Scripts\python.exe -m pytest backend/tests -q -rs -p no:cacheprovider
```

退出码 0；**206 passed / 13 skipped / 167 subtests passed，48.79秒**。日志：[coding-pytest-20261003.log](D:/Desktop/mihoyo-agent-project/research/coding-pytest-20261003.log)。覆盖现有 Runtime、流式协议、API、真实 loopback socket、SQLite中断恢复、路径、补丁、工具、前述检索修复及Docker命令/清理 mock。

13项跳过由 [conftest.py:14](D:/Desktop/herta-agent-coding/backend/tests/conftest.py:14) 明确指定：5项真实Docker集成、1项调试夹具聚合、4项生产pytest执行器、3项保留的旧本地PID/2秒契约。今天的206+13仍是219个测试项；历史216+3同为219项，差异主要是今天没有启用10项Docker相关用例，不能把跳过算通过。subtest数不同也不能简单相加为模型能力指标。

### 7.2 原有前端 unit

```powershell
npm --prefix frontend test
```

退出码0；**11 files / 24 tests passed，Vitest报告3.57秒**。日志：[coding-frontend-unit-20261003.log](D:/Desktop/mihoyo-agent-project/research/coding-frontend-unit-20261003.log)。包含真实无GUI backend-host 子进程关闭与复用，仍不等于Electron GUI E2E。没有为本次审计重复运行 build/typecheck/lint，也没有宣称其本次通过。

### 7.3 独立边界探针

脚本 [coding-offline-probe.py](D:/Desktop/mihoyo-agent-project/research/coding-offline-probe.py) 只使用现有生产类和临时合成文件，不改旧源码、不调用网络或Docker：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\Desktop\herta-agent-coding\backend'
.\.venv\Scripts\python.exe D:\Desktop\mihoyo-agent-project\research\coding-offline-probe.py
```

退出码0，结果见 [coding-offline-probe-20261003.log](D:/Desktop/mihoyo-agent-project/research/coding-offline-probe-20261003.log)：

1. source 改为 `value=2` 后重开 Workspace，副本仍为 `value=1`；复用相同路径，各对象 lock 不同。证明没有源变更同步，也不是跨进程锁；没有据此声称复现了并发破坏。
2. `submit_review` 接受不存在的 `missing.py:999999`。证明结构校验不等于引用真实性。
3. 离线 Provider只返回最终文本，Review Agent正常返回，tool消息数0。证明通用Run结束不强制结构化Review完成。
4. 合成pytest报告 `total=1, passed=0, skipped=1, exit=0` 返回 `status=passed`。证明产品业务完成标准需要关注有效执行数和必跑套件。

### 7.4 状态核对

执行前后 `git status --short` 一致；结束 `git diff --stat` 和 `git diff --check` 无输出，未修改旧产品源码。未启动付费或真实模型验证。上述探针是调研证据，不是新增生产测试或对旧问题的修复。

## 8. 对后续首个 Coding 交付阶段的建议

首个交付应是**在任务专属工作区中完成一个真实游戏 C# 小改动，并产出可核对的 diff + 真实测试结果 + 可恢复任务记录**。例如修复已有确定性战斗规则的边界条件；具体任务由游戏底座审计选择，不凭空构造另一个无业务关联的 Python 案例。

最小闭环包含：选择基线与允许范围 → 获取项目规则和相关代码 → 提交计划 → 受控修改 → 真实 .NET/规则回放验证 → 只读评审 → 展示差异、日志、影响和剩余限制。原 UI组件迁移到新的Runtime adapter；Python持有游戏任务/证据业务，不自行实现第二套模型循环。需演示一个成功任务、一个测试失败后修订任务、一个取消/重启后可解释的任务；未完成任务不能显示为业务成功。

首阶段验收先测集成契约与工具链，再做冻结的真实任务评测。对照至少保留“旧Herta微型闭环”和“无游戏适配的通用Coding流程”；新方案重点量化正确验证命令选择、有效测试执行、任务完成率、范围违规率、评审完成/误报、恢复后的证据完整性和usage可观测性。大仓库语义检索、P4、MCP/Skills、多Agent和跨端嵌入按真实需求逐步加入，不以功能名数量替代闭环质量。
