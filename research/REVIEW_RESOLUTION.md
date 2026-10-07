# 独立评审与修订记录

日期：2026-10-03。三位专项审查者在主方案初稿后分别评审；原报告保留，行号对应当时初稿，可能随修订移动。

原始报告：[Coding](proposal-review-coding.md)、[Codex](proposal-review-codex.md)、[游戏/验证/NPC](proposal-review-game.md)。

| 评审发现 | 采用的修订 | 所在位置 |
|---|---|---|
| SDK高层auto_review与低层accept混淆，人工route未明确 | 描述两层机制；显式on-request + reviewer=user，同步/异步API暴露handler与模式；start/resume/turn均需锁定 | 总方案3.3/7.3；路线G0 |
| MCP宿主不继承shell沙箱 | Broker独立执行；双入口权限矩阵；指定独立无凭据App Server command/exec后端；记录Windows分支限制 | 总方案9；路线G0/M2 |
| Interrupted不保证外部进程全停 | 产品turn/job状态分开；cancel_requested保留至真实退出/收据；有界超时与回收门槛 | 总方案7.3/9；路线G0 |
| Delta按item身份去重可能漏字 | item/turn仅用于投影；事件按seq/generation去重，保留重复文本合法delta | 总方案7.3 |
| 空review不一定是错误 | 允许带hash/范围的findings=[]；只拒绝未提交或无效结构化完成 | 路线M2 |
| 世界事务与NPC记忆不同库 | 世界状态+receipt+outbox原子提交；NPC inbox/记忆幂等事务；崩溃/乱序/重复测试 | 总方案5.2；路线M4 |
| 示例字段已存在，展示bug未复现 | 换成源码确实缺少的战前支援护盾Scenario功能；bug题先复现或标明注入 | 总方案7/10；路线M2 |
| 新胜率容忍度与旧Evaluator硬门槛冲突 | legacy描述性模式保留，新ExperimentSpec/policy版本化定义margin/场景/统计法 | 总方案6；路线M3 |
| 保留集追加与预算/停止规则不明 | 固定最终600场、一次分析；最多总1560场；追加另开预注册实验；六层保护不由均值抵消 | 路线8.3 |
| “保持机制”未可判定 | 固定脚本事件谓词：真实进入阶段、召唤、蓄力和可打断；与数值指标分别判定 | 总方案6；路线M3 |
| NPC修复包对满血初态无效，护盾未有入口 | SP+1方案直接映射旧初态；护盾方案依赖M2新功能；只选预写ID | 总方案8；路线M4 |
| 联合发布只锁游戏版本不够 | 同时锁工作台、NPC、policy、SDK/CLI/schema/产物；不可变包消费，活跃会话固定release | 总方案5.1；路线M5 |

补充发现：继续追踪Broker实现时，参考源码command_exec.rs的WindowsRestrictedToken分支拒绝streaming及terminate/write/resize。已加入限制与验收门槛，不将接口存在宣传为即时取消已可用。原始代码未修改，属于源码证据，尚非本机执行验证。

最终专项核查确认command/exec可独立于模型turn运行，但环境是merge、sandbox基准cwd可来自server配置、断开不会终止UnsupportedWindowsSandbox作业。方案已补充每任务执行进程的启动环境清理、cwd固定、默认输出cap与断开后job对账；这些仍需G0实际测量。

实施风险仍按验证报告保留；文档评审不替代SDK补丁、Unity自动执行、玩家输入、NPC或真实模型的后续测试。
# 2026-10-04 D03、恢复、统计与Unity追加评审

用户本轮反馈优先于2026-10-03旧选型；旧审计作为历史证据保留。新增设计见 [FRAMEWORK_ORCHESTRATION_DESIGN.md](../FRAMEWORK_ORCHESTRATION_DESIGN.md)。

| 评审发现 | 修订 |
|---|---|
| 旧D03以手写Loop存在为不采用框架理由 | 按项目选型，Verification实际拆Loop成图；NPC复用LangChain组件；Coding保持独立Runtime |
| effect成功而图没记录不能靠checkpoint消重 | 领域operation/receipt、预算事务和世界事务；真实框架跨进程probe验证最小模式 |
| payload hash进入唯一键可能将同槽变更变成新操作 | 逻辑槽唯一，payload仅作冻结值与冲突检查；新revision不重置总授权 |
| Job完成通知可早于interrupt而丢唤醒 | completion outbox/inbox、wait_registration，启动/暂停后扫描receipt |
| NPC首次POST丢响应可生成两个turn | scope+request ID幂等建turn；同save+NPC排队，conversation revision排序 |
| 模型布尔字段可绕过玩家确认 | action policy决定确认，commit核验权威decision；resume仅通知 |
| 不同command ID可能重复领奖 | 世界资格/奖励业务唯一键与receipt双层约束 |
| 业务fence不能防旧driver写checkpoint | 首版单Supervisor、同thread串行，确认旧driver退出再接管 |
| 50对不能普遍支撑严格2pp非劣 | 精确界与计数功效核算，低成本/严格profile分离、固定预算及family范围；AV单独精确二项定义 |
| “手动引擎替代”可被误读为最终降级 | Unity自动链路必交，G0-U未过阻塞M2/M5；真实输入/新XML/构建产物/清理合同 |

来源：[恢复语义审查](langgraph-recovery-review-20261004.md)、[统计核算](verification-statistical-budget-20261004.md)、[Unity审查](unity-automation-delivery-20261004.md)。独立agent复审主框架文档与Unity章节，父任务已纳入上述问题；所有未来验收与本轮fixture实测分开表述。
