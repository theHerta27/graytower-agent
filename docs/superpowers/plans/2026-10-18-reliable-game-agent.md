# 灰塔单Agent研发链路实施计划

> For agentic workers: use superpowers:executing-plans inline. 本轮用户已经明确要求开始实施；沿用已确认的项目说明与隔离开发方式，普通步骤不再逐项审批。

**Goal:** 从真实灰塔Git版本接收新问题，同一Runtime通过受限工具读取、修改并获得实际检查反馈，交付可审阅候选。

**Architecture:** 新增独立的development业务入口，复用Codex Runtime/SDK、DeepSeek受限网关和Docker边界，不改旧V1运行路径。候选从真实Git文本材料创建，控制目录与可编辑目录分离；检查绑定冻结候选，固定回归与探索性诊断分开标记。

**Tech Stack:** Python、官方SDK/Runtime0.160.0、SQLite、Git、现有固定Docker镜像。

**Spec:** [项目说明](../../../项目说明.md)。实施日志见[开发记录](../../../开发记录.md)。

## Global Constraints

- Windows、单机、本地服务、SQLite；NPC退出，多Agent/A2A不进入默认主路。
- 不改原始graytower-game、不改封存实验、旧V1继续可用。
- 默认单Agent，不自动启动Review或子Agent；不开放宿主shell。
- 所有真实模型调用仍须新材料范围和费用授权；旧账本保持关闭。
- 解释器显式指定；复用旧环境依赖时，源码必须从新工作树导入。
- 测试与诊断在受限执行器中运行，密钥不得进入Runtime或候选执行环境。

## Review Focus

- 路径穿越、链接或编辑可信测试，必须在工具侧拒绝。
- 编辑后旧检查不能表示新候选通过；所有回执绑定真实快照。
- 已完成检查丢响应要读取原回执，未知执行不能自动重跑。
- 源项目有未提交改动时不得默默纳入、覆盖或提交。
- 没有模型/容器时给出可理解状态，不把夹具执行当真实Agent验收。

## Task 1 真实项目候选与受限文件工具

**Files:** create `src/agent_workbench/development/workspace.py`、`__init__.py`；test `tests/test_development_workspace.py`。

**Interfaces:** `ProjectWorkspace.create(project, control, ref='HEAD') -> ProjectWorkspace`；`open(control)`；`read_file(path)`；`search(query)`；`write_file(operation_id, path, expected_sha256, content)`；`inspect()`。源码/配置可修改，可信回归不可修改；支持实际项目范围内多文件修改和新增删除。

- [x] 先写实际Git临时项目测试：从提交创建、不注入故障、源项目不变、多文件修改、新增删除、不可编辑测试、路径逃逸和幂等/漂移。
- [x] 运行测试确认缺少实现导致失败，修正测试错误后再实现。
- [x] 实现基线物化、快照/Diff、文件工具与持久编辑回执。
- [x] 定向测试通过并提交；记录行为、边界与证据。（016，9项；14f14a7。后续补可信回归依赖闭包）

## Task 2 可信检查与结果回读

**Files:** create `development/checks.py`、`tools.py`；test `tests/test_development_checks.py`。

**Interfaces:** `CheckJobs.start(workspace, check_set)`返回持久Job；`read(job_id)`返回pending/completed/unknown；工具提供读取/检索/编辑/开始检查/读取结果。检查使用Task1的冻结快照，调用现有固定Docker镜像，不接受模型宿主命令。

- [x] 先写快照绑定、检查集合限制、重复请求、结果未知、编辑后旧结果失效测试并确认失败。
- [x] 实现可信v2回归入口、受限场景诊断与原始结果存储；执行作业不阻塞SDK reader。
- [x] 容器可用时运行真实灰塔回归，核对实际导入路径、测试数与清理；不可用时保留失败并继续不依赖容器的工作。（022首轮失败保留；043效果19项通过，新任务暴露真实失败；完整轨迹Python环境仍待解决）
- [x] 定向测试通过并提交，不将模拟执行结果计作真实容器验收。（06d7c1a；复核修复及最终268项回归见开发记录）

## Task 3 单Runtime工具反馈与业务入口

**Files:** create `development/runtime.py`、`runtime_worker.py`、`service.py`、`__main__.py`；test `tests/test_development_runtime.py`。

**Interfaces:** SDK启动一个主线程，工具回调路由到Task2，不另写模型循环；任务保存需求、工作区与实际工具/检查回执。CLI支持创建、查看差异、检查、结果与授权运行。

- [x] 先用受控协议夹具验证同一线程读源码→编辑→发起检查→读失败→修订→再次检查的可达性，确认默认无Review/子Agent和无宿主shell。（038，真实Runtime与Docker；脚本响应，不算模型质量）
- [x] 接受真实项目与新需求，不按D01/D02或固定文件挑选提示；CLI/API入口展示可核对的候选和检查状态。（新增CLI；本轮不重做前端）
- [x] 准备一次有限真实模型验证的材料、运行代码和费用上限，等待明确授权；等待期间完成本地回归和开发记录。（single-agent-resource-v1，49文本，18次/USD0.95；等待授权）
- [ ] 获授权后执行真实任务，保留首次失败及限制；无授权时明确报告工程完成范围，不声称模型质量通过。

## 后续阶段

本轮基础链路通过后，再补主仓人工采用/恢复、独立确认任务集和有无领域适配/独立QA对照。实施优先级不是再次重做前端、扩大游戏或增加协议。每一项延期和实际发现都记入开发记录。
