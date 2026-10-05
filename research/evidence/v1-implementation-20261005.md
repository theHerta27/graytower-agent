# 本地 V1 实施与业务演示

日期：2026-10-05。已交付可运行 CLI 和真实业务/故障恢复演示；**M3 完整产品与模型质量验收尚未完成**。首跑有工具返回故障，解释草稿也出现数值误读，全部保留，不计为无故障端到端成功。

## 业务与运行入口

策划提出：“把击破手的战技倍率从 1.4 提高到 1.7，其他规则不变。我想先看看这样能不能让战斗快一点。”Config 读取真实游戏 Schema、规则和编辑范围，用 DeepSeek 生成修改；程序预检并冻结候选、展示 Diff。演示脚本以明确的 demo operator 身份确认 hash，**不是已做真人 UI 点击验收**。独立 QA 通过标准 A2A 接到候选，通过 MCP 调用游戏工具，再将报告送回调用方。

直接看保存的中文结果，不调用模型、不跑战斗：

```powershell
Set-Location -LiteralPath 'D:\Desktop\mihoyo-agent-project'
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -X utf8 -m agent_workbench.cli --data local-data/v1-demo report v1-live-demo
```

新建候选/确认/委托命令见 [README](../../README.md)。可独立 `serve --port 8771`，另一终端 `verify --url http://127.0.0.1:8771`；当前信任同一本机操作者，无 OAuth/多租户。React/Electron 页面未接入。

## 技术实际承担的职责

| 层次 | 作用与实现 |
|---|---|
| Config | [真实 LangGraph](../../src/agent_workbench/config/workflow.py)：理解需求、结构化编辑、澄清/拒绝、有界预检修正；不是数值优化器 |
| 模型 | [ModelGateway](../../src/agent_workbench/models.py)：LangChain ChatDeepSeek、完整预览、持久调用 cap、usage、无回退、关闭外部追踪 |
| 领域 | [CandidateRepository](../../src/agent_workbench/domain/candidates.py)：Author 冻结输入；Verifier 只读 hash；固定可信游戏子进程运行校验与模拟 |
| 独立 QA | [LangGraph 决策](../../src/agent_workbench/qa.py)：选模拟/读 Trace/结束；程序保有最终 verdict，图位置由 SQLite checkpoint 保存 |
| A2A | [官方 SDK client/routes/TaskStore](../../src/agent_workbench/protocol.py)：一张能力 Card；本切片仅接 Config numeric 候选，Coding 仍待接入 |
| MCP | [独立 stdio 工具服务](../../src/agent_workbench/game_tools.py)：候选读取、获批模拟、Trace、收据读取，没有 verify_everything 大工具 |
| 恢复 | [JobStore](../../src/agent_workbench/jobs.py)：确认、不可变请求、完成收据、去重；未知执行不自动重跑 |
| 结果 | [程序中文事实](../../src/agent_workbench/report_view.py)与[模型解释附录](../../src/agent_workbench/explain.py)分开；后者不能覆盖原判定 |

当前仅击破手倍率 `[1.4,1.7]`，不是多游戏平台/任意代码沙箱。V1 只部署单机、本地服务、SQLite；不实现 HA、OAuth、分布式 fencing/lease、生产级 outbox。独立请求显式批准 2–12 场；未做跨 revision 自动优化或共享 battle grant。Coding Runtime、NPC、Unity 沿既定路线继续。

## 真实结果与保留的失败

候选 manifest：`64a9d648e215d98886608147a415fd12849a55bca599c3cc498e0bc5c5f8bf00`。balanced、seed 7/11，共 2 对、4 场。两版本均 2 胜，原始行的精确分数计算如下：

| seed | 基线 AV | 候选 AV | 候选减基线 | 观测 |
|---|---:|---:|---:|---|
| 7 | 2300 | 23000/11 | -2300/11 | 候选行动值较少 |
| 11 | 16000/7 | 2200 | -600/7 | 候选行动值较少 |

配对 AV 比值中位数约 0.9358。**不是总体提升 6.42% 的证据，也不能承诺胜率提高。** AV 是战斗行动时间轴，不是模拟器耗时。结构 PASS，总体 INCONCLUSIVE；候选没有应用到游戏基线。

首跑收据已保存，但 MCP 日志的 `locals()` 带入闭包 GameTools 对象，JSON 序列化失败。QA 收到 4 次工具返回错误，观测列表为空，报告仍包含已落盘作业结果。重复调用复用收据，没有多跑战斗。修复仅改为显式日志参数字典；回归先失败后通过，真实 MCP 返回同一 receipt/metrics/Trace，新增战斗 0。QA 另外补了“返回丢失但收据存在”的精确参数恢复，错误记录保留。

原错误及结果保留：[首跑记录](../../local-data/v1-demo/demo-result.json)、[原 A2A Task 回读](../../local-data/v1-demo/original-a2a-task-readback.json)及 SQLite。后续交付文件以 request＋Task ID 命名。

追加一次只读解释时，模型把 seed 11 的负差值误说成“更长”，又说两个方向不一致。这是**尚未证明解决的模型质量错误**；[原草稿](../../local-data/v1-demo/explanations/v1-live-demo.json)不改，也没有加调用刷成功。`report` 由程序计算中文事实，`explain` 单列未核验草稿。修复后没有再付费跑完整新任务；后续独立需求验收必须补干净新任务和解释准确性。

## 实测、恢复与费用

- 真实进程在 receipt 完成、图更新前 `os._exit(73)`；另一进程恢复同一 Job，新增战斗 0，artifact hash 不变。该测试是 2 场真实战斗、fixture 模型、领域直连，MCP 另测。[硬退出证据](../../local-data/recovery-demo/receipt-93e305f1eafc/recovery-result.json)。
- running 无收据保持未知，同参数/新参数不能绕过重跑。没有冒称未知物理执行自动 exactly-once。
- A2A 服务重开，同业务请求新建 Task，复用报告、QA 调用 0；原 Task 可 GetTask。MCP 修复后正常返回原收据/Trace，原报告不变。[恢复结果](../../local-data/v1-demo/recovery-result.json)。
- 附录绑定原 report/candidate/receipt hashes；完成后重读无调用，started 无成品不自动重试。
- 父最终 suite：84 项，82 通过、2 个真实战斗 opt-in 默认跳过；两项已单独实际执行（领域 4 场＋恢复 2 场）。本轮已知实跑共 10 场（上述 6＋live 4），不是 10 个独立统计样本。[完整日志](../../local-data/v1-final-tests.log)，`pip check` 通过。
- 来源、测试、调用和 artifact hashes 在 [封存记录](v1-implementation-20261005.json)。旧协作/恢复原件继续由 `check_documents.py` 检查，未覆盖。

新批次用户授权仅官方 Chat Completions、deepseek-flash、最多 8 次/USD0.50；实际 **6 次完成、0 未知**：11297 input（3840 cached）＋1168 output。按当日[官方峰价](https://api-docs.deepseek.com/quick_start/pricing/)估算 **USD0.00366174**，非供应商账单。费用包含工具故障后的重复决策；旧六包账本未重置，剩余额度不自动移用于其他材料。

## A2A 与接下来的交付

[官方固定 tag Hello World 最小复现](a2a-official-minimal-20261005.md)确认终态重复输入残留 dispatcher，最新 release/main 核对尚有同路径。**没有 SDK 修改或 fork。** 产品新建完整 Task、终态 GetTask，公开准入拒绝续输入，暂不支持取消；不声称修好上游所有异常清理。

下一步先完成 Config/QA 独立自然需求、干净新任务与解释准确性验收，再接 React 策划/QA 工作台。之后 Coding 接稳定 Runtime、冻结代码候选和同一 QA；可玩 BattleSession、Unity 最终测试链、NPC 按路线推进。每阶段仍以实际可操作的业务演示退出。
