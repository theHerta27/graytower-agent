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
