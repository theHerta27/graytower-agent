# 材料调研与必要技术验证报告

> **Coding最新离线增量（2026-10-05）：** 正式SDK/CLI0.160.0原生生命周期/权限probe3/3，产品single/auto文件→MCP检查→原生Review→冻结候选分别5/10次本地脚本响应成功。189 tests（187通过、2既有opt-in跳过），0外部模型/0战斗；不等于DeepSeek质量或Coding→QA真实模型验收。新scope待授权。详见[Coding接入与限制](research/evidence/coding-runtime-integration-20261005.md)。

> **最新实施记录（2026-10-05）：** 已开始本机 V1，新增 Config/独立 QA/A2A/MCP/SQLite CLI。真实6次 DeepSeek、4场 live；首跑日志返回故障已修但记录保留，模型解释方向误读仍计质量失败，程序生成中文数值事实。84项最终测试（82通过＋2 opt-in已分别实际执行），硬退出后收据恢复0新增战斗。详见 [V1 业务演示、费用与限制](research/evidence/v1-implementation-20261005.md)及 [封存记录](research/evidence/v1-implementation-20261005.json)。本切片不是完整 M3 或 Unity 产品验收；以下旧阶段证据按原日期保留。

> **续验更新（同日）：** 原批累计8次已用尽；新授权16次/4场已完成。Config首轮5/6、同题开发回归6/6；QA非法策略与Trace过度解释如实保留，完成报告不算全部业务验收通过。最新实现、精确费用、测试和后续限制见 [V1续验记录](research/evidence/v1-followup-20261005.md)；上段84项为首次实施历史。

初版：2026-10-03；更新：2026-10-05（Asia/Shanghai）。第1—10节保留前几轮实测与当时判断，不作为新四能力架构已交付的证明。第11节记录本轮审计、标准协议与冻结候选验证；当前仍未交付完整四Agent产品或Unity自动链。

## 1. 阅读与检查范围

完整读取用户指定的六份入口材料：本目录 `mihoyoJD.md`、`PROJECT_BRIEF.md`；`herta-agent-coding` 与 `combat-foundation` 根目录的 `README.md`、`current_context.md`。随后沿真实入口检查：

- 游戏：v2 contracts/state/scheduler/effects/boss/bots/simulation/trace/report；Unity播放与输入、项目版本/依赖；测试与历史交付证据。
- Verification：CLI入口、loop/models/policy/tools/evaluator/evidence/provider、授权与恢复、历史任务manifest和测试。
- Coding：Electron main/preload/进程与SSE桥、React状态、FastAPI装配、Run/SQLite事务、Loop/Provider、工作区/patch/Docker测试/Review、评测记录。
- Codex：CLI/App Server协议、thread manager、session/turn/step、context与compaction、工具路由/执行/审批、Windows sandbox、rollout与resume、MCP/Skills/Review、Python/TypeScript SDK、Rust extension-api。

未逐文件通读Codex全仓库；阅读按关键问题追踪，并在 [源码报告](research/codex-source-audit.md) 提供符号与行号。

## 2. 可识别基线

| 对象 | 基线 | 实际状态 |
|---|---|---|
| combat-foundation | `fdb9e8387af696482bf2b57d1543484f8b08495c` | 未跟踪current_context.md；检查前后相同，无产品源码修改 |
| herta-agent-coding | `e121d8207f74af98e22f2c100348b05160a0560b`，coding-agent分支 | 未跟踪上下文/验收/计划文档；检查前后相同，无已追踪代码修改 |
| codex-main参考源码 | 无.git；Rust版本0.0.0；SDK版本0.0.0-dev | 关键文件SHA-256见源码报告，不声称对应某个上游commit |
| 已装Codex可执行文件 | `0.159.0-alpha.12.1` | 与参考树非同一构建；只对本次协议探针负责 |
| 参考Python SDK默认CLI依赖 | `openai-codex-cli-bin==0.153.4` | 与已装alpha不同，实施需选择配对版本并测schema |
| 游戏Python | 项目venv Python 3.11.9 | 本次181测试与规则探针使用该环境 |
| Unity | 项目`6000.3.19f1`；本机Editor位于`E:/Unity6/6000.3.19f1/Editor/Unity.exe` | 本次只确认存在，未重新启动引擎/构建Player |
| Node/.NET | Node 22.16.0；系统.NET SDK 10.0.301 | 不能据系统.NET版本推断Unity API兼容 |

PATH上的默认Python属于其他现有环境，开发/复现命令应显式使用项目venv。原项目README的部分启动路径已过期，应在迁移时改为可解析相对路径与doctor输出。

## 3. 本次实际运行的实验

| ID | 实验 | 结果 | 能证明什么 | 不能证明什么 |
|---|---|---|---|---|
| V01 | 游戏现有完整Python测试 | 181 passed，47.61s | 当前离线规则/Agent/契约回归成立 | 不等于新可玩功能或真实新Unity运行 |
| V02 | 现有C#控件编译与测试 | 16 passed | ReplayClock/Options控制逻辑可在Unity附带.NET工具链运行 | 不是Unity EditMode/PlayMode或Player测试 |
| V03 | 3策略×3seed×2次新模拟 | 18场；9/9对完整canonical trace相同 | 固定环境/输入下重复性、输入未被修改 | 不包含跨进程存档恢复、HTTP/Player输入、跨版本保证 |
| V04 | 历史证据完整性核查 | 27/27源码指纹、7/7回执hash、75/75任务EvidenceStore验证通过 | 历史证据与相应源文件可相互核对 | 不是本次重新跑了75个真实模型任务 |
| V05 | Coding现有后端回归 | 206 passed /13 skipped /167 subtests passed，48.79s | 本机离线测试路径通过 | 跳过的Docker测试不能算通过 |
| V06 | Coding前端单元测试 | 24 passed | React状态与展示的现有单测通过 | 本次未重跑Electron GUI/E2E、Electron10项或所有静态检查 |
| V07 | Coding四个边界探针 | 复现旧副本、假路径review、无结构化review完成、全skip标passed | 确认新的工作区/验收设计有实质需求 | 未修复旧产品，不能称新方案已实现 |
| V08 | 真Codex二进制+本地fake Responses服务 | start/stream/usage/interrupt/restart/resume/read通过 | 安装二进制的基本双向协议与持久历史可被本地程序驱动 | 不验证真实供应商、SDK全兼容、工具执行、审批或sandbox |
| V09 | 本地Python SDK fake-reader探针 | 默认command/file accept；等待handler阻塞后续通知，放行后恢复；custom binary override可用 | SDK人工审批通路需改造，版本下界通过不等于全schema兼容 | 不代表绕过所有Runtime审批，未执行任何shell |

### V01—V04证据

[游戏审计](research/game-verification-audit.md) 提供精确命令和历史解释；机器可读结果见 [audit-results.json](research/game-verification-evidence/audit-results.json)，测试见 [pytest.log](research/game-verification-evidence/pytest.log)、[pytest-results.xml](research/game-verification-evidence/pytest-results.xml)、[controls.log](research/game-verification-evidence/controls.log)，探针见 [audit_probe.py](research/game-verification-evidence/audit_probe.py)。

181项组成：旧核心32、v2核心69、旧Agent20、v2Agent40、契约20。重复模拟首遍每场0.17393—0.29449秒、817—1030事件、JSON约2.37—3.24MB；该耗时不含进程启动、网络、序列化与Unity，不能当玩家动作延迟。balanced/survival共6组全赢，basic_only3组全输。这支持增加困难度/资源层，而非仅在已饱和胜率上加seed。

历史75任务终态是45 ready_for_human、15 awaiting_input、15 rejected。“预期行为通过”包括正确澄清与拒绝。历史200场holdout和Unity929事件属于原验收记录；本次核对其文件hash，未重新构建/运行。

### V05—V07证据

[Coding审计](research/coding-audit.md)、[后端日志](research/coding-pytest-20261003.log)、[前端日志](research/coding-frontend-unit-20261003.log)、[边界探针](research/coding-offline-probe.py)、[探针结果](research/coding-offline-probe-20261003.log)。

13 skips包括5项Docker sandbox、1项coding eval、4项pytest runner的主机Docker集成门槛，以及3项被新Docker契约替代的旧PID/2秒契约测试。历史216/3与本次206/13差异来自未启用10项Docker测试；本阶段没有启动Docker来追求更好看的数字。

历史Debug严格通过6/10；Review8题中7题可评分，报告TP=5/FP=1/FN=0仅针对该小集。历史正式Electron验收是一个读取文件并运行pytest的任务，不应表述为各种游戏修改任务都已验证。

### V08证据与复现

[脚本](research/probes/codex_protocol_probe.py)、[result.json](research/evidence/codex-probe-20261003-231459/result.json)、[events.jsonl](research/evidence/codex-probe-20261003-231459/events.jsonl)。

```powershell
Set-Location -LiteralPath 'D:\Desktop\mihoyo-agent-project'
& 'D:\Desktop\combat-foundation\.venv\Scripts\python.exe' '.\research\probes\codex_protocol_probe.py'
```

脚本为临时研究探针，不是生产adapter：启动真实CLI/App Server、独立loopback fake Responses端点和新的子进程数据目录；不修改用户Codex配置，不读取现有登录，不访问真实模型。两次请求路径实际为`/v1/responses`，fixture产生usage=13只是验证字段传递，**不是13个真实付费token**。

结果：第一turn completed且收到文本delta和usage；第二turn长流中断后为interrupted；进程正常关闭并重新启动后，thread ID相同、历史两个turn状态分别为completed/interrupted。本实验没有注入硬崩溃，没有测试任意shell、file approval、MCP、compaction或外部副作用exactly-once。

### V09证据

[脚本](research/evidence/codex-sdk-static-probe.py)、[结果](research/evidence/codex-sdk-static-probe-result.json)。直接导入参考SDK并用内存fixture模拟消息，不启动Runtime。实验环境的packaging 26.0低于源码声明>=26.2，能导入并完成本探针不构成完整安装验证。

高层默认auto_review与客户端handler默认accept是两层机制。准确结论是：到达客户端的command/file请求会被默认接受，且高层缺少完整人工模式；自定义等待UI的同步handler会堵住reader。后续需显式人工路由、异步处理和fail-closed默认，不只是修改一个accept字面量。

## 4. 官方资料对架构的约束

以下均于2026-10-03检索并打开，适用性仍以锁定版本源码和后续真实smoke为准：

- [App Server](https://learn.chatgpt.com/docs/app-server)：可用于深度客户端集成；stdio双向RPC提供必要链路，接口实验性质要求版本/协议测试。
- [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)：Python SDK与App Server的关系已由本地代码再次核对，不再假设只存在TS exec封装。
- [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox)：elevated/unelevated能力不同；引擎和MCP宿主执行不能自动继承shell的全部限制。
- [Unity命令行](https://docs.unity3d.com/6000.3/Documentation/Manual/EditorCommandLineArguments.html) 与 [UnityWebRequest](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Networking.UnityWebRequest.html)：支持推荐的自动化/HTTP方向；具体模块、许可和Player仍待真机验证。
- [DeepSeek Responses兼容](https://api-docs.deepseek.com/guides/responses_api/)：已有原生Responses接口，不能说永远只支持Chat Completions；但部分工具/参数支持有限，需要按Runtime实际流量测兼容。开始两次fetch超时，后续官方页面成功获取；未运行其中安装/配置脚本。
- [LangGraph持久化](https://docs.langchain.com/oss/python/langgraph/persistence)：checkpoint/store分别管理图内与跨thread数据。2026-10-04已按用户反馈修订D03，Verification/NPC采用框架、Coding保留Codex；旧“以后再评估LangGraph”的判断已被替代，见 [框架设计](FRAMEWORK_ORCHESTRATION_DESIGN.md)。
- [SQLite FTS5](https://www.sqlite.org/fts5.html)：可供词法检索；中文分词/角色可见性仍须业务实现与评测，数据库功能本身不保证正确记忆。

## 5. 未关闭问题及其处理

| 未验证事项 | 影响 | 推荐处理 |
|---|---|---|
| SDK/CLI/schema完整配对 | 人工审批与事件兼容 | G0固定版本、局部patch与协议回归 |
| Windows原生受限执行里的Unity | 自动化引擎验收能否完整交付 | G0-U真实Editor/Player测试、产品构建/自动OS输入与回收矩阵；未通过阻塞M2/M5，手测不得最终替代 |
| command/exec的Windows限制 | Broker流式与长作业取消 | 源码WindowsRestrictedToken分支明确不支持stream/terminate；先验收buffered硬超时/回收，不能据协议探针声称即时停止 |
| Python sidecar/HTTP/真实Player输入 | 游戏是否可玩、是否延迟可接受 | M1首交付必须真实构建与录制复现 |
| Python3.11→3.12和打包 | 规则/随机可重复与分发 | 先golden对比，锁版本再发包 |
| 真实模型质量、供应商兼容、成本 | 三Agent可用性 | 小smoke后固定provider/model，再正式评测 |
| 新统计profile/最终保留集 | 平衡效果结论是否可靠 | M3预注册样本、口径、预算与停止规则 |
| NPC知识/存档隔离、迟到响应与奖励 | 玩家体验和世界一致性 | M4明确事务、来源与作用域测试 |
| Rust扩展必要性 | 维护成本 | 外部adapter对照失败才启动，首版不承诺 |

这些未测项不妨碍完成本阶段总体方案；它们是实施阶段显式的风险门槛。现有材料和探针足以确定推荐架构，没有必要在本阶段重写产品来伪装调研完成。

## 6. 2026-10-04追加：真实框架恢复探针

本节为新增实测，前文2026-10-03的规则/Coding/SDK成绩仍是原日期证据，没有因文档修订重复计算。独立研究环境位于`research/.venv-framework`，旧项目依赖未改；PyPI下载获准后安装真实框架。研究锁为LangGraph1.2.12、checkpoint4.2.0、SQLite saver3.1.1、LangChain1.4.3、core1.6.6、DeepSeek组件1.1.1、Pydantic2.13.5，解释器Python3.11.9。目标Python3.12与异步服务仍待G0-F验证。

脚本：[langgraph_recovery_probe.py](research/probes/langgraph_recovery_probe.py)；[完整依赖锁](research/probes/framework-requirements.lock.txt)；[结果与版本](research/evidence/langgraph-20261004-mtqwchsr/result.json)。脚本使用真实StateGraph/SqliteSaver/interrupt，并把副作用账本与checkpoint放在不同SQLite文件。

| 探针 | 实际结果 | 结论范围 |
|---|---|---|
| 实验提交后checkpoint前进程退出 | child以73退出；checkpoint next=effect，无receipt；三次新进程恢复及一次旧checkpoint回放后仅1个operation、12局预算预留 | 能用真实框架验证领域receipt补偿图进度；“12局”是fixture账本数，未运行12场游戏 |
| NPC世界提交后响应/图更新前退出 | 同样强制退出；恢复后三次仍world revision=1、reward=1、outbox=1；旧checkpoint回放不重奖 | 验证最小命令收据模式；不是生产Game Host、HTTP故障或完整记忆消费验收 |
| interrupt节点重入 | 一次暂停/恢复，共进入节点2次；使用interrupt ID映射resume | 证明节点开头会重跑；未实现API并发resume、approval CAS/outbox |
| LangChain组件 | ChatDeepSeek.with_structured_output(function_calling)经HTTP MockTransport返回Pydantic意图；@tool/编译图内ToolNode配对工具消息成功 | SDK/API组合成立；0次真实provider调用，无模型质量/延迟/费用结论 |

首次完整探针在ToolNode直接invoke处失败：已安装`langgraph-prebuilt`要求Runtime上下文，`_runnable.py`报告`Missing required config key 'N/A' for 'tools'`。读取`ToolNode._func(..., runtime)`与注入源码后，只把工具调用放入编译StateGraph，重跑全部探针通过。这是探针调用方式修正，没有修改框架包。失败与修订另记 [运行说明](research/evidence/langgraph-probe-run-notes.md)。

**未验证：** 持久Job等待注册/早到通知、并发resume、fence、inbox乱序、图升级、生产async saver、真实游戏worker、真实provider、断电/磁盘损坏。跨进程probe只覆盖进程退出和已完成SQLite事务；不宣称exactly-once或生产恢复已经实现。

## 7. 2026-10-04追加：统计核算与Unity合同

[统计报告](research/verification-statistical-budget-20261004.md) 和 [原始结果](research/evidence/statistical-budget-20261004/results.json) 保留脚本/依赖/输入hash。实际运行的是CP数值边界核验及100组、每组200000次多项计数模拟，**没有新增战斗样本**。

确认：六cell共12单侧界、alpha=.05/12下，n=50且b=c=0的下界−10.381891pp；零不一致至少n=272达到−2pp。n=10000/cell在假设q=.10、delta=0时六独立同类cell全部PASS概率约97.60%，在其他参数下可很低。当时据该假设提出120960场/任务（含探索）；该默认预算已在本轮撤销，旧1560场也只可作低成本行为/描述性profile，实际标准需基于业务与独立pilot重定。对应时间/存储是旧易场景线性外推，不能当新worker性能实测。

AV补充精确二项计算：m=500共同胜利对、两主cell各alpha=.025时需k≥273对改善至少5%；条件达标概率p=.6的假设下，单层功效约99.37%、两个独立层约98.75%。正式AV要求使用固定总pair集合，m不足不能继续抽到足够；此计数结果不代表当前游戏AV分布已经达标。

[Unity专项报告](research/unity-automation-delivery-20261004.md) 核对真实源码及官方6000.3命令/UTF语义，补齐Editor/Player tests/普通Player构建/OS输入/权威状态/清理的最终门槛。**本轮仍未启动Unity或构建Player**；G0-U未关闭，手动引擎或纯C#不能替代最终自动化。报告的命令模板、时间预算和故障矩阵都是待实现合同。

本轮研究支持修改方案与实施验收，不等于已经交付LangGraph产品、NPC、严格平衡效果或Unity自动测试链路。

## 8. 2026-10-04最新：业务校准、真实DeepSeek与首个实现切片

本节对应最新用户要求：不固定多Agent，成品全部DeepSeek，解释真实业务与技术边界；旧方案的固定Reviewer、5%/2pp及大批次默认预算已撤销。

| 实验 | 实际结果 | 可推断与不可推断 |
|---|---|---|
| 游戏业务校准 | 212真实模拟，55.26s；12个源/配置hash前后未变；另20项原规则测试通过 | 为场景/候选选择提供探索依据；不是确认集/玩家效果/发布统计 |
| DeepSeek受控smoke | 真实CLI＋官方SDK源码；3 HTTP200，只读动态工具往返及原生inline Review完成，全部deepseek-flash | 基础真实协议通；工具白名单relay封顶/缓存SSE，未测完整shell/改码/MCP/长上下文/实时流延迟或Review质量 |
| 原生工具捕获 | 本地fake Responses下6场景；原生MCP及subagent声明namespace，V2出现agent_message | 证明所装Runtime实际发什么；DeepSeek未明确支持这些类型，不能推断原生调用兼容 |
| SDK动态工具→MCP窄转接 | 真实CLI＋官方Codex SDK＋MCP SDK1.26.0，本地模型fixture；5步Runtime循环、2次MCP调用，正常/未注册/非法参数/MCP错误处理通过 | 选择此为当前工具接入实施路径；未测真实DeepSeek全链、取消、断线或业务Job receipt |
| 检索初轮 | 35源码文件、363片段、6查询，6000字符/8片段预算；强词法与别名扩展均宏召回61.11%、完整2/6 | 别名扩展本次无收益，不为技术包装虚构提升 |
| 检索结构跟进 | 同650片段语料，词法66.67%/3题完整，配置/AST关系83.33%/5题完整 | 看过失败后的同题探索；分块变化与结构增益分开，不算独立保留集或代码任务完成率 |
| 新Verification代码 | 16项测试通过，最终12场真实实验，报告DESCRIPTIVE_ONLY | 有可运行CLI/领域模块与LangGraph编排；没有自然语言模型、UI、异步Worker或沙箱 |
| 新切片进程故障 | 最终4场完成后退出73，checkpoint仍待experiment；3新进程resume收据/扣账不变。另准入后退出74、尚未模拟，保守扣账4，恢复拒绝自动重跑 | 真实代码与游戏支持领域先提交恢复；未知attempt停止，未实现生产分布式调度或自动重算 |

### 新证据与具体发现

- [校准数据](research/evidence/game-semantics-calibration-20261004.json)、[日志](research/evidence/game-semantics-calibration-20261004.log)、[20项规则测试](research/evidence/game-semantics-rules-20261004.log)。32场选择Boss ATK490压力条件，180场对照仍属探索。倍率1.4→1.7普通两策略配对AV约−4.35%/−1.19%；压力balanced3/10→7/10胜，但含1胜→败、仅2共同胜利。韧性360→288普通survival反而更慢并减少蓄力打断。不能继续默认“降低韧性快5%”。
- [DeepSeek总说明](research/evidence/runtime-deepseek-assessment.md)、[真实请求](research/evidence/runtime-deepseek-20261004-152744/live-result.json)、[原生MCP声明](research/evidence/runtime-deepseek-20261004-153025/result.json)、[窄转接](research/evidence/runtime-deepseek-20261004-154144/dynamic-mcp-result.json)。真实请求输入7513（cache hit1792）、输出159含reasoning50；官方当时非高峰价格估约USD0.000959，不是实扣账单。3请求/总6000输出token封顶，之后只做离线实验。未读取用户Codex auth，原密钥仅内存使用，129件当次产物扫描无key命中。
- [检索说明](research/evidence/retrieval-mcp-notes-20261004.md)、[初轮](research/evidence/retrieval-probe-20261004.json)、[结构对照](research/evidence/retrieval-structure-probe-20261004.json)。中文未登记别称仍0召回；FTS5中文子串能力不能默认成立；NPC仅合成scope过滤负例通过，没有真实NPC记忆召回质量结论。
- [产品源码](src/agent_workbench/verification/workflow.py)、[测试](tests/test_verification.py)、[最终测试日志](research/evidence/verification-slice-tests-20261004.log)、[最终正常实验](research/evidence/verification-slice-final-20261004/result.json)、[最终故障](research/evidence/verification-recovery-n7zc67l5/result.json)。CLI独立prepare/approve/reject/show/resume；批准绑定plan hash、图resume不构成批准；结果绑定计划/源/配置/场景hash；领域摘要与receipt同事务；OS文件锁保单driver。

独立代码评审发现3项实际缺陷，均先补失败测试再修复：整数288被转float后违反核心严格int；完成边界未绑定结果与plan hash可串候选；源指纹漏掉会执行的包入口。最终16项含这些回归及双进程锁。早期`verification-slice-20261004`、`verification-recovery-gq60it03`保留为修订前记录，其receipt格式与最终代码不同，不用于当前验收，也不手工改成通过。

真实模拟计数：本轮研究212场＋实现前后两版各16场＝244场；最终版本有效切片证据为12＋4场，重复样本和重跑不增加统计样本量。退出74的unknown案例未启动模拟但保守扣4场，必须与实际完成局数区分。完整trace未落盘，保留摘要和trace hash；尚无成品trace分页调试器。

该阶段尚未关闭：固定CLI/SDK全协议、非阻塞人工审批、DeepSeek真实apply_patch/shell/游戏MCP/取消与恢复、Unity G0-U、真人可玩BattleSession、完整Verification模型选择、NPC世界/记忆/行动真实链路、独立检索和多Agent效果对照。框架组件fixture不等于这几项通过；后续获授权的真实协作对照见第10节，其余边界未被替代。

## 9. 2026-10-04协作取舍补充：原生V1窄格式适配

用户进一步明确：多Agent若有可重复业务质量提升，即使更慢/更多token也愿采用；必须明确实现与公平评估，有正面结果则进入正式产品。已据此更新总体方案9、路线4.1/8.5与接续规则。本节是接入验证，不是业务效果实验。

[探针](research/probes/cooperation_protocol_probe.py)、[原始结果](research/evidence/cooperation-protocol-20261004-175241/result.json)。真实CLI0.159.0-alpha.12.1和官方Python SDK，经本地有限映射，将原生V1 namespace内工具声明/历史调用名展平为function，响应再还原namespace。上游为固定本地Responses fixture，不访问DeepSeek，不读key/auth，也不执行模型shell/写工具。

5个请求完成原生spawn→wait→close；Runtime真实创建子thread、返回子结果，父子配置deepseek-flash；call/item ID和历史正文保留，非允许的工具输出被拒绝。父子调度仍在Runtime，适配层没有实现另一套Agent循环。选择此为G0-MA优先进一步验证的兼容候选，已有MCP dynamicTools转接继续承担领域工具，两者职责不同。

该离线阶段限制：仅一个子Agent、固定消息/工具响应，relay缓冲SSE；未测真实DeepSeek工具选择、send、多子并发、完整reasoning/流增量、限流、未知字段、异常重试、取消/恢复和费用归属；V2 agent_message仍待处理。当时不能宣称真实多Agent可用、并行提速或质量增益。后续真实provider及效果进展见第10节；本节5请求仍是本地fixture，不改称真实调用。

## 10. 2026-10-04真实Coding协作与独立确认

完整方法、原始记录、计量与采纳见[真实协作对照报告](research/evidence/collaboration-evaluation-20261004.md)。真实运行16次开发、28次独立确认；2开发题/4确认题，13个源码注入根因＋1干净候选的14项程序核验通过，不把注入问题声称为旧项目原有缺陷。

- **实现已证：**官方Python SDK＋Codex CLI 0.159.0-alpha.12.1＋V1窄格式适配，Runtime负责主循环与1主＋3子生命周期；父子全部DeepSeek。确认201请求均200并正常完成，36子均真实completed后关闭，父最终汇总随后开始；8parallel真实重叠、4serial不把前子答案转给后子，8个A+同thread六阶段0子。28/28原生轨迹审计通过。适配层没有替代Runtime调度。
- **质量结果：**28/28交付，所有条件零已知根因漏报/零误报。single、A+、parallel各14/14根因命中，完整提交证据依次9/14、10/14、8/14；serial仅两题，为8/8根因及4/8完整证据。四批隐藏模式的独立源码判定已封存，评分按根因/触发/位置/证据，不依标题关键词。不是人类盲审或参试DeepSeek自评分；材料缺口、重复不独立、检出上限明确披露。
- **时间与资源：**三种主要条件平均运行20.33/103.94/42.25秒，均价USD0.002689/0.013740/0.011134。固定同分工四对串并合计433.657→230.328秒，减少46.9%，完整证据在该子集为串4/8、并2/8，并非质量等价。Runtime墙钟不含最终序列化/独立评分，不是全产品交付端到端。A+按开发费用曲线增强，实际token和缓存不相同，不声称严格同资源因果比较。
- **全部成本：**352次额度登记，350次已知usage估非峰USD0.487120，2次未知保留峰价预留USD0.048152；峰价已知＋预留合计USD1.022392、输出实际＋预留686534，未超USD3/600请求/100万输出。包含工程和开发失败，不把未知写成0；不是账单，不含开发助手费用。外发在用户明确授权六份评测包及分析后继续，没有绕过此前自动审批拒绝。
- **工程回归：**22运行/预算/profile＋16评分＋16既有Verification=54项通过；另14项冻结真值程序检查。测试调用一次漏PYTHONPATH在发现测试前失败，按README配置src后通过。计量独立复核454数值断言是证据算术检查，不是产品测试数量。

**采纳：**当前profile没有可重复质量增益，保留single基线与四种真实研究运行模式，暂不推荐为正式产品默认路径。更快的parallel相对六轮A+或serial，不足以推翻普通single在这些任务已更快、更省且检出相同的事实。不外推“多Agent无用”；下一轮面向真实仓库/失败日志、动态工具/检索与上下文压力，在完整基线上独立确认，有收益再推进M2-C4正式入口。没有增加未证收益的UI或固定Verification/NPC角色。

**仍未证：**真实完整Coding改码与测试交付、V2/send/生产取消恢复、所有异常在途请求对账、Unity真实自动链、完整Verification/NPC产品。受限评审接入成功与本轮效果结论不替代这些门槛。

## 11. 2026-10-05：四能力边界审计与必要本地验证

本轮完整读取用户最新附件及现有主文档，按实际入口重审旧Verification、新numeric切片、旧Herta、Codex参考源码、当前官方协议与测试证据。审计分三条独立线，结论见[领域边界](research/evidence/verification-boundary-audit-20261005.md)、[Runtime边界](research/evidence/coding-runtime-boundary-audit-20261005.md)、[标准/框架](research/evidence/a2a-mcp-langgraph-audit-20261005.md)。旧目录与现src保持原样；本轮新增研究探针，不将其冒充产品迁移。

### 11.1 影响设计的源码与官方事实

- 旧Verification含候选生成和FAIL后修候选；当前worker也还在内部`apply_changes`。新设计把Author能力迁Config，Verifier只读上游冻结输入，报告失败回原Author。当前Store绑定plan/source但未校验上游预期candidate hash，失败证据和总预算需补齐。
- 旧Herta是自写model/tool Loop，不是Codex产品。参考SDK默认approval handler接受请求、同步reader会阻塞，fresh子Agent不默认带父dynamicTools，role权限能力随版本不同。Coding复用Runtime原生动态0..N委派，不照抄固定1＋3实验约束。
- 官方CLI0.160.0已发布；历史实测为0.159 alpha，参考SDK依赖0.153.4，未升级重测。A2A规范v1.0.1对应wire1.0，官方SDK1.2.1为本轮安装基线；新MCP SDK2.3.0改用MCPServer/httpx2且没有可用Tasks实现。API、源码tag与来源在审计记录，不能按旧0.3/v1 MCP教程猜测。

独立新环境`research/.venv-protocols`安装A2A `[http-server,sqlite]`、MCP2、LangGraph及SQLite saver；[完整锁](research/probes/protocol-requirements-20261005.lock.txt)、[下载版本与hash报告](research/evidence/protocol-dependencies-20261005.json)可复核，`pip check`无依赖冲突。普通网络下载先被sandbox拒绝，获工具级批准后只下载公开SDK；没有外发项目源码、没有读取/发送模型密钥，也没有改变旧venv。

### 11.2 Author冻结→Verifier只读：真实游戏小验证

[probe](research/probes/frozen_candidate_probe.py)、[6项测试](research/probes/test_frozen_candidate_probe.py)、[结果](research/evidence/frozen-candidate-probe-20261005/verification/result.json)、[复核记录](research/evidence/frozen-candidate-probe-20261005-review.json)。

Author fixture从可信游戏1.4基线生成1.7倍率候选，分别保存完整Baseline/Candidate/Scenario和内容hash；Verifier入口只收引用，校验类型/版本/来源，不接受changes也不调用apply_changes。两seed（7、11）×balanced×两版本共**4场真实战斗**，完整4份Trace落盘。候选磁盘与内存、40份旧游戏源/配置、8份当前src均核验未变；9份输入/输出文件与manifest可验hash。没有全仓复制，没有新模型请求。

6项边界测试通过：Author生成精确diff、禁用Author函数后仍可预检、bytes篡改、路径引用越界、声明schema错、实际payload schema错、changes入口与源版本漂移拒绝（部分一项测试含两个相关断言）。拒绝在simulate前发生。父任务独立重跑6项也通过，没有因此重跑战斗。

结构判定PASS，行为仅DESCRIPTIVE，**总体INCONCLUSIVE**。旧TaskSpec为兼容结构校验需一个criterion，本probe明确不按它判行为验收，也不因此创造业务目标。四场观察不能证明改善或总体非劣。探针证明只读输入的逻辑边界，不证明OS只读挂载、生产授权、A2A接入、跨revision预算、代码/build沙箱或完整QA Agent。

### 11.3 一张A2A Card、两个客户端、真实MCP

[probe](research/probes/a2a_mcp_boundary_probe.py)、[测试](research/probes/test_a2a_mcp_boundary_probe.py)、[协议实测报告](research/evidence/a2a-mcp-boundary-probe-20261005.md)、[冻结功能结果](research/evidence/a2a-mcp-test-20261005-e8qqhg02/result.json)、[实际HTTP wire](research/evidence/a2a-mcp-test-20261005-e8qqhg02/http-wire.json)。

真实loopback HTTP＋官方A2A1.0 JSONRPC/SSE，Coding/Config两个**测试客户端**发现同一Verification Card/skill；真正MCP2 stdio子进程提供query_schema/validate/read_artifact，实际协商协议2026-07-28；LangGraph只跑固定判断fixture，不调用LLM。不是把私有HTTP接口叫A2A，也不是已集成真实Codex/Config产品。

4项新增测试通过，其中一项集成用例含**37个功能断言**：completed承载PASS/FAIL/INCONCLUSIVE；测试身份和跨owner Get/List/续输入/Cancel隔离；相同业务ID重发不再验证、不增加reservation，同ID换payload拒绝；INPUT_REQUIRED同Task续行；错误context/终态再输入拒绝；断流后Subscribe/Get；Cancel及执行协程取消；官方SQLite TaskStore另开实例读回最终报告；候选无变化。相同业务请求产生两个不同A2A Task ID而复用同一领域结果，证明不应拿协议ID冒充业务去重键。

**生命周期没有通过生产验收。** 终态再输入拒绝前检测0个`EventQueueSource` dispatcher，拒绝后2个；结束伴随pending task / OpenTelemetry detach告警。固定SDK源码中的ActiveTask异常创建路径支持这是SDK清理缺口的判断；详见[SDK诊断](research/evidence/a2a-mcp-test-20261005-e8qqhg02/sdk-diagnostics.log)、[stderr](research/evidence/a2a-mcp-test-20261005-e8qqhg02/stderr.txt)及协议审计补记。功能结果明确`production_ready=false`。不隐藏警告、不修改安装包来抹平记录；正式G0需采用上游修复或受测最小补丁，并做终态拒绝/断线/取消/重复调用的队列与进程清理回归。

实现时还修正了两处探针用法：MCP工具显式开启structured output，否则仅有文本content；A2A V2续输入流不替executor生成首Task，需应用发恢复快照。原失败目录保留，当前代码与最终结果hash绑定；这些不是模型质量提升。

本probe未测首次响应完全丢失且没有task ID、运行中服务硬崩溃、持久LangGraph等待、并发重复业务请求的完整跟随、真实OAuth、外部游戏Job取消或OS沙箱。SQLite另开实例读回不是跨进程运行中自动恢复。其数值字段/结论为合成规则，不属于前一节4场真实战斗；两条探针尚未集成同一真实Agent链。全轮新增模型调用为**0**，不新增DeepSeek费用。父任务独立重跑4项测试，同样37功能断言通过并复现0→2队列问题；[复验记录](research/evidence/architecture-validation-20261005.json)绑定该次结果与来源hash，未重跑真实游戏。

### 11.4 独立评审与实施落点

[领域评审](research/evidence/architecture-review-domain-20261005.md)与[Runtime评审](research/evidence/architecture-review-runtime-20261005.md)共发现5项文档契约问题，已修正并定向复核：完整Manifest先冻结再确认、准入拒绝与调查不确定区分、子只读强制路径待验、稳定版原生MCP/后备桥优先级一致、固定profile阴性不淘汰原生动态能力。协议研究者另抽查新方案的A2A/MCP版本/API与状态映射，未发现阻断事实错误。文档一致性通过不代替相应生产实现。

现有主方案/框架/路线已收敛四能力、保留/迁移/实验处置、状态与证据契约、安全恢复和阶段验收。README、原任务书优先说明、AGENTS和接续记录同步。旧框架/协作runner/真值/manifest/原始轨迹/评分seal及当前src未变，文档检查继续核验它们。

下一步按M3-A/B先做真实Config→A2A独立Verification→证据回Author；并行M1可玩会话、G0-C稳定Runtime与动态子权限、G0-U真实Unity。严统计标准与预算、代码/build验证和NPC世界链继续按显式门槛推进，不把本轮研究完成当项目群交付完成。
