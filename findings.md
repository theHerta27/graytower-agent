# 调研发现

## 2026-10-05 实施中的新证据

- SDK缺陷应和产品路径分别证明：官方固定Hello World可复现A2A终态再输入队列问题；本机V1按公开准入限制完整新Task，不需要大fork也不声称上游已修。
- 真实故障证明receipt必须先于图/返回更新：游戏4场完成后，MCP日志locals捕获闭包对象导致返回失败。去重复用避免重新模拟；显式日志参数修复后返回正常。这个问题未被只读/拒绝路径测试捕获，已补完整成功响应回归。
- 结构化LLM输出合法不等于解释正确：DeepSeek把负AV差说成更长。应让程序从原始配对数值生成事实、模型说明保留为草稿并做独立质量验收；不通过追加调用隐藏失败。
- 当前真实链的价值是职责分离及可审计恢复，不是已经证明多Agent质量/性能提升。新Config/QA协作与旧固定1＋3benchmark不是同一实验，不混用结论。

## 2026-10-05 当前收敛边界（优先于历史三Agent计划）

- 用户新增Config Agent承接策划配置生成；Coding和Config各自拥有Candidate，Verification只规划/执行/调查/形成证据判决，不改候选，不默认递归自优化。
- 标准A2A只暴露一套Verification capability/Agent Card，两类Author复用，不新增Config↔Coding链路。MCP是各Agent→研发工具边界，不以verify_everything工具代替独立QA Agent。
- Coding原生子Agent按任务动态委派，旧固定1主3子benchmark仅保留受控实验身份；NPC继续Memory/RAG/互动/世界工具，不预设多NPC。
- 初始目录检索未发现已有A2A服务/客户端或Agent Card实现；现src仍仅有Verification numeric切片，须进一步核验协议和领域状态迁移。

### 本轮实证与设计结论

- 源码确认旧Verifier既是Author又验证，当前worker仍构造候选；不是改目录名即可完成新边界。生成/编辑政策迁Config，Verifier独立只读复检，失败回Author，新revision沿用总grant。
- 官方A2A1.0/SDK1.2.1和MCP2.3.0在独立环境可共装，真实单Card/双client/MCP stdio/SQLite功能可行；MCP2没有Tasks runtime，业务Job与A2A Task分开。旧MCP1.26桥只作旧版本fixture证据。
- 37协议断言通过却不能过生产生命周期：终态再输入拒绝后0→2队列残留。优先上游或受测最小补丁，不隐瞒缺陷也不改回私有协议。
- Author冻结→Verifier只读的真实4场边界验证保留完整Trace，6测试通过；结构通过不等于业务效果。没有真实LLM QA，不将两独立probe包装为完整产品。
- SDK reader、子dynamicTools继承、role权限存在源码限制；动态功能仍保留，子只读必须逐执行入口负例验收，当前稳定CLI与旧测试版本分开。
- 本轮修正完整Manifest确认范围、准入拒绝/调查不确定、子权限、MCP优先级与协作功能保留的5项评审问题。主方案仍围绕一款游戏、四独立能力与真实证据，不造任意游戏平台。

## 已完整读取的原始材料
- mihoyoJD.md：游戏 Agent 通用能力、研发工具链、游戏体验、调试评测回放、边界控制；另含 Coding Agent 全栈职责与真实开发环境工具、跨端 WebView。
- PROJECT_BRIEF.md：一个可玩游戏底座 + Verification / Coding / NPC 三个项目；Windows 为主要环境；主语言 Python 是准备方向，不是所有模块的硬性限制。
- herta-agent-coding/README.md 与 current_context.md：旧桌面框架、Python 自有循环、SSE/SQLite、受控工具与 Docker pytest；文档称有真实模型与 Electron 验收，未接入 combat-foundation；部分 README 路径仍指向旧目录。
- combat-foundation/README.md 与 current_context.md：Python 唯一结算、Contract/Trace 2.0，Unity 为回放端；有授权/Spec/候选/模拟/Reviewer/证据链；崩溃 running 任务不自动重放。

## 初步待证实判断
- 游戏由回放展示升级为可交互、可复现的玩家回合，是三项目共同依赖。
- 旧验证业务资产价值较高；旧 Coding UI、生命周期测试与案例可迁移，但 Runtime 路线需对照 Codex 再定。
- NPC 需玩家/角色可见性与存档隔离，不应直接复用研发侧运行记录为经历。

上述现状仍以说明文档为主，源码核查与本次实测将记入后续报告。

## 主线源码/环境核查
- Python 战斗 `v2/simulation.py` 在单个 while 循环里调用 Bot；已有 `effects.validate_action` 与 `resolve_action`，可抽出暂停/提交动作接口，不必迁移全部规则到 C#。
- RNG 是独立 `random.Random(seed)`；战斗状态有 rng_count，但恢复还需要保存 RNG 内部状态、调度阶段与事件序号，单存 BattleState 不足。
- Unity 项目版本为 6000.3.19f1，本机 Editor 确实位于 E:/Unity6/6000.3.19f1/Editor/Unity.exe。Packages 当前不含 UnityWebRequest 模块或正式 Test Framework，接入时需显式补齐并锁版本。
- 本机 Codex CLI=0.159.0-alpha.12.1；Node=22.16.0；.NET SDK=10.0.301；游戏 venv Python=3.11.9。PATH 的 python 指向 Hermes 环境，验证必须使用项目显式解释器。
- Codex 参考树无 Git 元数据，不等同于已装二进制；以关键源码哈希识别，后续使用协议契约测试控制差异。
- 官方 App Server 文档支持 stdio 双向 JSON-RPC、线程/审批/流式接口，当前页面同时声明实验性质；据此需要版本锁定与 adapter，而不是假设协议永远稳定。
- 官方 Windows sandbox 文档区分 elevated / unelevated；前者专用低权限用户与防火墙，后者限制 token/ACL 与较弱网络限制。Unity 是否能在推荐执行配置下完整跑通仍须独立验收。

官方来源（2026-10-03 已打开）：
- https://learn.chatgpt.com/docs/app-server
- https://learn.chatgpt.com/docs/windows/windows-sandbox
- https://docs.unity3d.com/6000.3/Documentation/Manual/EditorCommandLineArguments.html
- https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Networking.UnityWebRequest.html

## 收敛后的关键事实与决策
- 旧Coding实测发现共享旧副本、Review定位未核验、无结构化review也可结束、全skip也可标passed，支持工作区/结果ledger升级。
- Python SDK已存在，首选复用而非自写全部transport；但客户端handler默认accept、同步reader审批阻塞；高层auto_review需显式切换为人工route。
- 真二进制+fake Responses已验证会话基本协议，未验证模型效果/审批/执行沙箱。
- command/exec在参考WindowsRestrictedToken分支不支持streaming/terminate；执行Broker选择独立无凭据App Server的buffered/硬超时路径，必须验收子进程回收。取消模型turn不代表外部job停止。
- 两仓不可变版本包与联合release lock；NPC世界outbox/记忆inbox，保留独立知情边界。
- 演示任务改为尚缺的战前初始护盾功能；shield_expired.reason其实已经存在，不能把它当新增贡献。
- 精确证据、复验命令与源码行号已归入三份research专项报告；主方案与路线经过三线独立评审并修订。
# 2026-10-04 补充结论

- 用户认可总体方向，要求将主流Agent框架实际应用与原理纳入目标。D03改为Verification LangGraph重构编排、NPC LangGraph+LangChain、Coding原路线；详见FRAMEWORK_ORCHESTRATION_DESIGN.md。
- 真实LangGraph/SQLite进程退出探针通过：领域提交后图无receipt仍可从独立账本恢复；三次新进程恢复/旧checkpoint回放不重复预算和奖励。LangChain结构输出/只读ToolNode用HTTP fixture验证；ToolNode直接invoke缺Runtime的失败已保留，改在编译图内执行。
- 独立评审补齐Job完成早于interrupt的lost wake-up、NPC首次POST幂等与跨turn顺序、确认要求必须来自服务端action policy。稳定ID/payload冲突、总预算跨revision、一奖多ID、审批权威记录均明确。
- 原1560场与严格2pp非劣常见情景不匹配：n50零差异下界−10.381891pp；n272仅特例；默认n10000/cell共120960场设计点功效与成本已算。AV采用两个标准主cell的精确二项门槛，条件子集和family范围明示。
- Unity最终要求真实Editor+Player tests+构建+OS输入+权威状态+清理；旧静态harness/纯C#不替代。G0-U阻塞M2/M5，有界排障后仍未过就保留阻塞，不能免除要求。

## 2026-10-04 最新证据覆盖旧推荐

- DeepSeek统一成品推理已明确。原生Responses受控3请求通过，包含原生inline Review；当前Codex MCP/subagent实际发送namespace，不能宣称兼容。SDK dynamicTools→官方MCP client窄转接fixture已通，当前选它继续生产集成。
- 主流框架价值落到真实Verification三节点与独立账本，不只是安装依赖；真实4场领域commit后崩溃/3次恢复不重跑，未知执行不自动重试。仍没有全产品模型/异步/沙箱能力。
- 212场探索显示效果依策略/资源改变，压力条件有win→loss；不保留默认5%/2pp与10000对预算。旧统计计算是条件设计参考，不能自动授权执行。
- 检索首次别名无改善；同扩展语料结构关系完整3/6→5/6属探索，未登记别称失败。NPC只有合成scope负例；旧prompt文件不冒称Skill实现。
- 多Agent学习以公平、可有负结论的实验完成；默认单Agent，原生Review不需永久独立角色。正文已解释工具/系统指令/任务上下文/Skill以及MCP客户端/服务/领域职责。

## 2026-10-04 协作决策新约束与证据

- 合理单Agent是完整基线，不是规避协作的目标。用户接受更多费用/耗时换可重复业务质量；真实协作实现/评估必做，有收益必须进产品模式。
- 现成MCP dynamicTools转接不实现原生协作；新增V1 namespace声明/调用名双向映射离线验证已保留Runtime spawn/wait/close、子上下文和生命周期。真实DeepSeek、V2 agent_message/取消恢复/完整SSE仍是工程项，不能当效果负面结果。
- 协作实验区分实际增量收益、增加单Agent资源后的价值和相同分工并行节时。独立确认不重用已知护盾任务；重复运行不是新增独立样本。方案9与路线4.1/8.5是当前执行依据。

## 2026-10-04 真实对照后的结论

- DeepSeek Responses可经有限V1 namespace/function适配承载Codex Runtime原生三子协作；不是必须重写主循环。实际原生等待参数范围和SSE调用身份需要程序校验，不能凭SDK方法存在判兼容。
- 同一完整资料上的三专业独立复核，未胜过合理single；28确认中主要三模式已知根因检出全满，证据完整性single9/14、六轮A+10/14、parallel8/14。上下文保护/动态工具专业化尚未受到本套封闭材料任务充分检验，不作普遍负面结论。
- 六阶段A+是按开发用量设计的有目的复查，不是严格同token/费用；parallel相对A+更快，但普通single仍更快且检出相同。同分工四对parallel运行合计少46.9%，该子集完整证据却低于serial，不能说保持全部质量的提速。
- 发现根因、支持性论断与修复可靠性要分开。一条并行结果建议重复维护队列字节账本，源码核查显示可能二次扣减；不能只数TP就包装业务成功。共同缺源码片段影响严格证据分，但不能奖励猜隐藏实现。
- 保留已实现可复现的协作实验能力，暂不升级这套profile为产品推荐；下一轮用真实仓库/失败日志任务、完整工具/检索/摘要基线与独立确认再决定，收益成立仍必须M2-C4产品化。


## 2026-10-05 真实业务续验与修复

- 状态类型与自然语言可能不一致：冲突请求被正确追问却返回rejected。结构化字段必须写清业务分类，不能只按文案关键词评分。
- 模型会混淆baseline/candidate版本与policy策略，具体枚举应进入工具Schema，不能仅靠prompt枚举；非法参数与预算不足应分开诊断。
- 截取Trace前6000字符会被大state_after快照占满，读到技能决策不等于验证伤害/倍率因果。压缩视图需保留事件引用、明确省略范围；模型解释仍单独验收。
- 图状态保存请求快照不能代表当前剩余额度；决策前查业务/模型账本，程序守预算且保留最后真实决定。额度耗尽不是provider错误。
- 开发首轮5/6→同题回归6/6是已知案例修复结果，不能作为独立质量或多Agent增益。
