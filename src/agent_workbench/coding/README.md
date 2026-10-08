# Coding Agent 源码说明

面向研发人员：理解修改需求，在隔离工作区生成候选，执行检查与原生 Review，再交给独立 Verification。当前真实业务验收主要覆盖击破手战技倍率配置编辑；任意游戏代码开发与构建尚未完整交付。

## 从哪里读

- `service.py`：业务入口、运行授权、候选交付。
- `runtime_adapter.py`：准备指令、工具、上下文、运行配置并启动 SDK 工作进程。
- `runtime_worker.py`：通过官方 Python SDK 启动 Codex Runtime，创建线程、处理工具请求、收集事件与 Review。
- `file_tools.py`、`readonly_mcp.py`：受限文件操作及只读工具服务。
- `candidates.py`：工作区检查与候选身份。
- `responses_transport.py`、`response_namespaces.py`：DeepSeek Responses 接入、预算与受测协议适配。

## 复用了什么

官方 `openai-codex` Python SDK 与 `openai-codex-cli-bin` Runtime 包固定配对为 0.160.0。Runtime 以独立进程运行，承担 Agent 主循环、线程、原生子 Agent 和 Review；本仓库没有复制整个 Runtime 源码。`D:/Desktop/codex-main` 是阅读参考，不是此模块运行时加载的源码树。

本项目新增业务工具、工作区与候选管理、模型接入控制、权限边界、运行证据，以及与 Verification 的产品链路。配置允许协作不代表本次运行实际启用了协作，更不代表已经证明协作质量收益。

## 如何使用

双击仓库根目录 `打开研发工作台.cmd`，进入 Coding 页面。默认关闭新模型调用，可查看已有运行记录。真实任务需配置模型与明确的调用预算；游戏规则与候选领域实现位于共享模块及游戏仓库。
## 2026-10-08 Python 修复切片

保留同一官方 SDK/Runtime 0.160.0 与 Responses 预算接入，新增 `shield-damage-python-v1` profile：只读 MCP 读取固定游戏代码目录；主线程 `edit_text` 仅写 effects.py；原生 Review 后绑定树与文件 Hash；CodeWorkspace 冻结实际 Git diff；CodeTestJobs 在独立 Docker 中重建并测试候选。

`scripts/run_python_coding_demo.py` 提供 prepare/run（run 需要本次scope hash、独立授权记录及本机密钥）。真实 D-01 已执行7调用，候选四项测试通过，批次已关闭；不得重置目录续用额度。`/code-repair` 是只读证据页面，统一代码Task/QA委托与新尝试入口还在开发。此前numeric配置任务仍使用原profile，不把worktree当进程沙箱，也不复刻Runtime循环。
