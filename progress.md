# 工作进度

## 2026-10-05 四能力架构收敛（完成本轮审计/设计范围）

- 完整读取用户粘贴附件：新增独立Config；Verification接收不可变候选并只验证，失败回Author；Coding保留Runtime动态原生子Agent，旧1+3只为实验；NPC保持独立；仅Config/Coding→Verification的一套标准A2A能力。
- 开始并行旧Verification/现切片、旧Coding/Codex Runtime、A2A/MCP/LangGraph官方版本审计；主线梳理现有总体方案、状态/证据/安全边界与实施依赖。旧研究结论保留适用范围，不冒充新架构验收。
- 本轮先做资料/源码审计及本地协议验证，不启动旧付费对照或扩大DeepSeek数据外发。规划和结论仍维护现有主文档。

- 已完成三线源码/官方版本审计并改写原总体方案、框架/恢复、路线，README/AGENTS/任务书优先说明/验证报告与接续记录同步。四能力及当前未实施状态清楚，固定1＋3仅历史实验。
- 独立协议环境安装公开SDK后pip check通过；新6项冻结候选测试和4场真实游戏完成，完整Trace与输入/输出hash封存；新4项A2A/MCP测试含37功能断言，两个官方client访问同一Card，0模型。
- SDK1.2.1终态拒绝留下队列任务，诊断和失败原件保留，G0生产生命周期未过；确定下一步修复/回归门槛。MCP结构输出/续输入首Task等我方探针错误已修，旧失败未覆盖。
- 两位独立评审发现5项设计边界问题，已修并复核；协议事实再次抽查。父任务独立重跑6＋4测试，37功能断言与队列缺口均复现；9 artifact/40旧游戏源/8当前src及协议seal核对。没有重新跑付费协作或旧战斗批次。
- 为查看新探针残留尝试只读Win32_Process inventory被宿主拒绝访问，因此没有把系统进程检查记为通过；无依此修改权限或绕过。程序侧正常退出与SDK队列清理问题分开记录。
- 最终可复验入口为research/probes/check_documents.py、两个新test文件和research/evidence/architecture-validation-20261005.json；文档链接/hash检查输出见document-check.json。下一步首个Agent链按M3-A/B执行，M1/G0-C/G0-U并行。

## 2026-10-03
- 定位统筹目录 D:/Desktop/mihoyo-agent-project，完整阅读 JD、任务书及四份要求的项目入口文档。
- 阅读规划、架构探索、并行调研与官方资料检索技能；本次请求已明确授权自主调研、验证与方案落盘，按该范围继续。
- 建立调研计划与发现记录。下一步：三条源码核查线并行，主线核对环境与关键架构可行性。
- 完成真实已装 Codex App Server 的独立协议探针：本地伪 Responses 端点，线程创建、流式文本、usage 通知、取消、进程重启与历史恢复全部通过。未调用真实模型、未运行shell工具、未验证Windows sandbox。证据 research/evidence/codex-probe-20261003-231459/。
- 并行回归：游戏 Python 181 passed；Coding Python 206 passed / 13 skipped / 167 subtests，React 24 passed；细节与日志由审计报告收录。
- 新发现：参考树含 Python App Server SDK，需将其纳入选型；不能沿旧知识默认只有 TypeScript exec SDK。
- 完成总体方案、G0/M1—M5实施路线、验证报告和三份源码审计；新增README、简明AGENTS与current_context接续入口。
- 三条独立评审提出并已处理：人工审批路由、MCP执行隔离、delta去重、外部job取消语义、合法空Review、NPC跨库恢复、真实代码任务、统计版本/停止规则、机制保持、支援映射、联合版本锁。
- 对Broker执行路径继续核对，发现WindowsRestrictedToken不支持command/exec streaming/terminate，已明确buffered硬超时/回收边界与G0门槛。
- 完成文档完整性验证：18份文档、304个本地链接/源码行号无缺失或越界；再次核对游戏JUnit181、Coding日志206/13、真实二进制fake模型协议结果和SDK行为证据。检查脚本与结果已保存。
- 最终执行后端补充经源码专项复核无明显矛盾；补充后再次校验18份文档、313个本地链接/行号全部通过。源代码审计第9节保留command/exec具体边界。
## 2026-10-04 方案修订

用户认可总体方向，并要求按项目引入主流Agent框架。本轮并行研究LangGraph恢复语义、严格统计样本预算、Unity自动化交付；父任务进行真实框架离线探针与总体设计。仅修改本项目方案和研究产物，不重构旧产品。

- 完成FRAMEWORK_ORCHESTRATION_DESIGN.md，并同步主方案、G0/M1—M5路线、验收、README/AGENTS/current_context；旧D03手写编排基线已被替代。
- 获准在独立研究环境安装锁版本LangGraph/LangChain。真实SQLite图进程退出恢复、重复续跑/旧checkpoint回放、interrupt重入、LangChain离线结构输出/只读工具组合通过；首次ToolNode上下文错误及修复记录保留。
- 完成严格NI精确界与100组计数功效、AV精确二项计算；区分逻辑样本、物理10%恢复池、CPU/存储外推，禁止把小样本或重复抽样写成严格效果。
- 独立框架评审补齐lost wake-up、首次NPC请求幂等、服务器确认规则、logical slot/payload冲突、总预算跨revision与奖励业务唯一键。Unity主方案和最终路线独立复审通过，G0-U不通过阻塞最终交付。
- 最终文档检查23份、380本地链接/行号全部有效；新框架与统计脚本hash匹配结果，旧JUnit/协议证据仍核验通过。旧两仓git status仅原有未跟踪文档，未见已追踪源码修改（git用户ignore路径访问警告另保留）。
- 本轮完成的是方案修订与必要验证；未执行生产迁移、新真实模型/战斗大样本/Unity引擎。后续实施从M1与并行G0-F/G0-U等子门槛开始。

## 2026-10-04 最新用户反馈：收敛与开始实现

- 产品改为单Agent基线、全部DeepSeek；原生Review保留，固定多角色/强制Reviewer撤销。参照两篇Anthropic文章设计同资源及追加资源对照，不移用文章结果。
- 212场游戏校准推翻默认5%目标与“韧性降低必然更快”假设；撤销默认12万场/任务与31万场批次。明确AV/胜率/机制、NPC120点3回合待实现设计、自然完整交互及不同用户页面。
- 真实DeepSeek3请求通过dynamic function与inline Review；额外发现原生MCP/subagent namespace风险。选择SDK动态工具→业务MCP client窄转接，官方MCP SDK离线fixture成功；不重写Runtime，不做通用网关。
- 首个独立Verification LangGraph实验切片已写入src，16测试通过；最终真实12场实验＋4场receipt先提交后exit73，3次新进程恢复不重算，unknown exit74停止重试。旧代码只读，当前目录非Git，没有提交/推送。
- 独立代码评审三缺陷（整数转换、收据未绑定计划、指纹漏入口）均测试复现后修复；文档评审修正MCP路径、对照共用兼容层、护盾台词绝对判断及可信scope来源。
- 已同步现有主文档；框架/模型/产品/统计/Unity证据边界分别记录。最终文档检查结果见research/evidence/document-check.json；G0-C生产接入和G0-U仍未完成。

## 2026-10-04 协作质量优先补充

- 用户明确接受有意义、可重复质量提升带来的更多token和耗时。已移除把同资源/提速/省钱当全部协作实验前提的表述，分别设计A/B投入产出、A+/B资源归因、同分工串并行时间消融。
- Coding跨规则/契约/Unity调查评审优先；明确G0-MA和M2-C1—C4工作包，真实原生子Agent实现、开发实验、独立确认、正面结果后的正式可选模式。单Agent完整保留，首版启动时选择。
- 主动验证协议候选：真实Codex CLI/官方SDK通过namespace/tool name窄映射，原生V1 spawn→wait→close、子结果回传、模型配置继承、call/item IDs与历史保留，本地5请求通过。未读key/auth、无新增付费调用；不是DeepSeek协作效果证据。
- 独立方案复核通过，补齐证据不足/无收益/接入未完状态区别。主文档和接续文件同步，未来接入未过不得结论为协作无价值；有收益不得只交评测表。

## 2026-10-04 真实协作完成

- 获用户具体外发授权后完成原生DeepSeek接入和1主＋3子；16开发、28独立确认及四批盲判，失败/截断/未启动历史完整保留。确认201请求、36真实子，原生审计28/28通过。
- 确认single/A+/parallel各14/14已知根因、零误报；完整提交证据9/14、10/14、8/14。没有可重复质量增益；保留single与四模式实验入口，不将本profile正式默认化。协议接入完成与质量收益未证分开。
- 同分工两题四配对运行墙钟少46.9%，不是完整交付端到端或质量等价；全部协作研究350已知usage估USD0.487120，另2未知保留额度，总峰价实耗＋预留USD1.022392，未超USD3。
- 54工程/评分/既有切片测试、14冻结真值检查通过；独立方法、原生与计量复核完成。主方案/路线/框架/验收/README/上下文同步。详见research/evidence/collaboration-evaluation-20261004.md。
