# Verification Agent 源码说明

面向 QA 与研发：独立读取已冻结候选，选择配对模拟、读取事件证据或结束，输出可核对报告。它不编辑候选；程序根据真实检查决定 PASS、FAIL 或 INCONCLUSIVE，模型不能覆盖失败事实。

## 从哪里读

- `agent.py` 的 `VerificationAgent`：当前工作台的 QA 主入口，LangGraph 组织 inspect → decide → execute → conclude。
- `../qa.py`：旧导入的兼容入口，已不存放主流程。
- `workflow.py`：较早的结构化实验计划编排，仍供独立实验 CLI 使用；与工作台 QA 入口用途不同。
- `store.py`、`../jobs.py`：本地实验与任务记录、执行收据、基本恢复。
- `combat_worker.py`：可信本地游戏适配。
- `contracts.py`、`report.py`：实验契约及确定性报告。
- `../game_tools.py`、`../protocol.py`：MCP 游戏工具与 A2A 服务/客户端。

## 复用了什么

LangGraph 与 SQLite checkpoint 承担图状态恢复，MCP/A2A SDK 承担接入协议。本项目实现候选身份、预算、实验收据、证据归属和报告判定。checkpoint 不是战斗已执行的唯一依据；实验完成但图未更新时，按同一业务操作的收据对账，避免重复消费战斗预算。

## 如何使用与当前限制

从工作台选择已确认候选，提交独立验证并查看报告；也可用 `agent_workbench.cli` 的 serve/verify 命令。`python -m agent_workbench.verification --help` 查看结构化实验 CLI。工作台默认关闭模型；CLI 的 serve/verify 在配置模型后可产生真实调用，应先设置预算。当前是单机本地 SQLite 部署，可信数值验证仍依赖旧 `combat-foundation` 基线；小样本描述不能当作总体胜率提升证明。
