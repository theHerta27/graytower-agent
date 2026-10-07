# Config Agent 源码说明

面向策划：把自然语言调整需求变成可审阅的配置候选；目标不清楚时澄清，超出范围时拒绝。候选经过程序校验和冻结后，由策划/研发人员确认，再交给独立 Verification。

## 从哪里读

- `workflow.py` 的 `ConfigAgent`：主入口；LangGraph 组织读取上下文、模型提议、确定性预检及有限格式修正。
- `ConfigDecision`、`ConfigEdit`：结构化输出契约。
- `../domain/`：授权字段、实际编辑、校验、Diff、候选冻结和确认。
- `../models.py`：DeepSeek 与 LangChain 模型接入。
- `../workbench.py`：页面 API 接入。

## 复用了什么

LangGraph 承担图流程；模型理解需求并提议编辑。数值范围、文件修改、候选身份与确认由本项目的确定性程序负责。图节点本身不等同于多个 Agent。

## 如何使用与当前限制

双击根目录 `打开研发工作台.cmd`，进入 Config 页面，提出明确数值需求或查看历史候选。当前主场景是受限战技倍率调整，不支持自动搜索最佳数值或任意配置修改。现有数值候选管线仍依赖只读 `combat-foundation` 基线，尚未完成跨机器路径整理。
