# 灰塔框架主线改造实施计划

> **For agentic workers:** 使用 superpowers:executing-plans；独立模块可委派实现，最终做独立代码审查。步骤用复选框记录。

**Goal:** 在现有项目中交付 LangGraph＋LangChain 单研发 Agent、基本任务恢复和可管理的项目记忆，保留候选、可信执行和人工采用。

**Architecture:** StateGraph 管理模型决策、工具执行、等待与结束；LangChain ChatDeepSeek 和消息/工具组件负责模型交互。候选编辑和 Job receipt 继续使用现有领域实现；checkpoint 不替代执行事实。

**Tech Stack:** Python 3.11、LangGraph 1.2.12、LangChain Core 1.6.6／DeepSeek 1.1.1、SQLite、Starlette、React／TypeScript、Git、Docker。

**Spec:** 本轮用户已确认的方案（2026-10-25）：同一灰塔项目替换 Codex Runtime 主循环，单 Agent 动态调查/修改/检查/修订，项目记忆有来源、版本与确认状态；不新建教学项目，不要求优于通用 Agent。本文以下边界将该方案具体化。

## Global Constraints

- 只改 D:/Desktop/mihoyo-agent-project-next；Herta、原游戏、旧V1和封存实验只读，不推送GitHub。
- 本轮不沿用旧收费授权；默认不调用外部模型。新真实批次在材料和费用准备完成后才请求授权。
- 单机、本地服务、SQLite；不新增分布式部署、多Agent、A2A或向量数据库。
- 一个 Agent 循环；LangGraph 为新默认执行入口，原 Runtime 保留为历史实现。
- 编辑只在候选；可信测试只读；模型没有采用/恢复工具；确定性检查不被模型解释覆盖。
- 未知模型调用和未知Job不自动重试；恢复沿用稳定决策与操作ID。
- 中文前台只展示项目、需求、实际操作、Diff、真实检查和人工决定。

## Review Focus

- 模型已返回但checkpoint未更新：按稳定decision ID读取落账结果，不能重复付费。
- 工具已编辑或Job已完成但checkpoint落后：沿原operation ID和Job身份读取，不能重复执行。
- 无关、待确认或旧版本记忆：不进入模型上下文；已批准权限不作为记忆复用。
- 上下文或预算接近上限：保留有效工具对话，预留收尾，输出真实阶段结果。
- 页面刷新/服务重启/重复恢复：可看到保存状态，同一run单驱动；旧封存批次不被新入口续用。

## Task 1: 模型和项目记忆的独立基础模块

**Files:** 新建 development/model.py、memory.py；tests/test_development_model.py、test_development_memory.py。

**Interfaces:** ToolModel(root, grant, specs, api_key='', http_client=None)，complete(messages, decision_id, final_only=False) -> AIMessage；remaining_calls() -> int；summary() -> dict。ProjectMemory(database)，add(project, content, *, source, version, kind='constraint', status='pending', memory_id=None)，list(project)，update(project,id,**fields)，delete(project,id)，retrieve(project,query,version,limit=5)。

- [x] 先写并运行失败测试：真实LangChain HTTP边界、稳定ID重放、未知请求不重发、工具参数/usage、跨项目和版本过滤、CRUD。
- [x] 实现ChatDeepSeek工具调用；无隐式重试/外部Tracing；CallBudget继续封顶，决策响应独立落账。
- [x] 实现SQLite项目记忆，默认pending、确认后按项目/版本/词法关联检索，保留来源；来源不随模型任意伪造。
- [x] 跑模块测试，记录RED→GREEN及限制。

## Task 2: 图、上下文与恢复

**Files:** 新建 development/agent.py、context.py；修改 tools.py 增加通用工具适配但保持旧Runtime兼容；tests/test_development_agent.py。

**Interfaces:** run_agent(workspace,jobs,control,model,request,profile='standard',memories=(),resume=False,answer=None,memory=None) -> dict；checkpointer为run下SQLite；result含status、summary、tree_hash、pending、reason。

- [x] 失败测试：动态读→编辑→检查失败→修订→检查通过；澄清暂停/跨实例继续；工具后崩溃重放；检查完成不付费轮询；预算收尾。
- [x] 实现显式StateGraph与LangChain工具/消息；决定、工具、等待检查、澄清、交付节点。
- [x] 有限上下文：按需读取，压缩旧工具正文并保留身份和证据引用，保留近期完整工具调用对；最后一次模型调用禁用工具以收尾。
- [x] 操作ID绑定run和tool_call ID；checkpoint保存流程引用，候选/Job/费用回查账本；未知结果暂停，不盲目重试。
- [x] 跑图与已有工具/候选回归。

## Task 3: 服务、页面和启动入口

**Files:** development/service.py、web.py、__main__.py、frontend/src/DevelopmentPage.tsx及相关测试、启动/安装脚本。

**Interfaces:** 新scope schema=development-langgraph-v1，endpoint为官方chat/completions，完整材料预览含命中记忆；prepare/run/resume保持同一grant，旧scope拒绝进入新图。Workbench提供模型状态、实际事件、问题与恢复入口、项目记忆CRUD。

- [x] 失败测试：新默认路径不依赖SDK、重复运行/暂停恢复、scope变化、记忆预览变化、旧scope隔离、人工动作边界。
- [x] 接通任务执行、统一事件与结果；单机run锁；等待检查/用户时保留未关闭run；终止则封存。
- [x] 页面提供清楚的暂停原因、回复/继续、实际Diff和证据；项目记忆查看/新增/确认/修改/删除。
- [x] 默认安装启动仅需主Python环境；旧Runtime工具不删除，SDK参数保留兼容但新路径不使用。
- [x] 跑前后端测试、构建、启动冒烟。

## Task 4: 业务验收、说明与审查

**Files:** 更新AGENTS.md、current_context.md、项目说明.md、开始使用.md、开发记录.md；新增本轮证据摘要。

- [x] 跑完整Python/前端回归与构建；在临时游戏clone验证候选与人工采用/恢复；Docker可用时跑真实规则检查。
- [x] 在同一主图上用明确标注的脚本模型验证工程链路，不把它算作真实模型质量。
- [x] 独立审查本轮改动；重要问题先复现再修复。
- [x] 更新中文说明，清楚区分已实现、脚本验证和待真实模型验收；不改历史成绩。

## 执行决定

- 用户已明确“可以，开始做吧”，并长期要求普通步骤不反复确认。本计划直接实施；新收费外发与原项目写回仍保留边界。
- 不扩建通用平台。记忆先采用词法和版本过滤；没有明确召回缺口前不加Embedding。
