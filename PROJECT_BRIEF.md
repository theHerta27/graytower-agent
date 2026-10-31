# 灰塔：游戏规则代码修复 Agent

灰塔面向回合制游戏的 Python 规则代码与配置，支持问题定位、代码修改、自动化检查，以及人工确认后的 Git 合入和撤销。

## 当前架构

- 一个 LangGraph 研发 Agent，通过 LangChain 接入 DeepSeek 和项目工具。
- 每项新任务使用独立 Git 分支和 Worktree，修改不会直接覆盖开发项目。
- Docker 执行规则检查；交付前检查准备合并后的结果，确认后再次核对版本再合入。
- SQLite 保存任务状态、执行记录和已确认的项目记忆；文档检索使用 FTS5 / BM25。
- FastAPI 提供本机 API，React / TypeScript 展示需求、Diff、检查、提问回复与交付操作。

## 阅读入口

- [项目介绍与验证结果](README.md)
- [开始使用](开始使用.md)
- [工作树与交付实现](Git工作树与交付说明.md)
- [实际编码任务记录](research/evidence/completion-20261027.md)
- [Git / Docker 工程验收](research/evidence/git-worktree-20261028.md)

早期多 Agent、A2A、NPC 与 Codex Runtime 的探索材料继续保留，当前默认执行路径使用上面的单 Agent 架构。
