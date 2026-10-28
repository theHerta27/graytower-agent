# 灰塔 Git 工作树 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新任务使用受限 Git 工作树，经真实检查和人工审批后合入，支持冲突处理、撤销和旧任务读取。

**Architecture:** 保留现有 ProjectWorkspace 协议及 legacy snapshot 实现，以 GitWorkspace 实现新后端。GitDelivery 独立保存准备、审批和执行记录；检查仍由 CheckJobs 对冻结输入执行。页面与 CLI 使用同一交付服务。

**Tech Stack:** Python 3.11+、Git 2.49、SQLite、现有 LangGraph/LangChain、Docker、React/TypeScript；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-10-28-git-worktree-design.md`

## Global Constraints

- 新建任务默认 `git_worktree`，旧 `development-project-v1` 数据不迁移、不改历史。
- 原有 READ_ROOTS/EDIT_ROOTS、大小、路径和链接限制不放宽；Git 工作树不是操作系统沙箱。
- 新模式采用与撤回产生 Git 提交，不强制覆盖、不 reset --hard、不自动推送。
- M 第一父提交 T、第二父提交 C；审批与 T/C/M、检查定义和回执绑定，确认后复查。
- 原游戏、历史收费证据只读；工程验收使用临时仓库、脚本模型和真实 Docker，0 新收费调用。
- Windows PowerShell；复用 next 已有工作树和现有解释器，不另建开发 checkout。
- 用户已确认设计并交由本会话连续实施；采用 native 执行，最后独立审查。

## Review Focus

- 路径含空格/中文、Git 指针被替换或工作树外新增文件：拒绝越界，保留用户文件（Task 1/3）。
- 源分支推进且改动不冲突：不能遗漏原项目新代码，检查合并结果（Task 2）。
- 用户处理冲突时漏暂存或自行提交：不能把错误版本交付（Task 2）。
- Git 已合并而 SQLite 未记录成功：重开后对账，不能再次合并或回退（Task 2/3）。
- 页面保留旧确认框、另一个进程启动任务：后端拒绝过期审批与并发写（Task 1/4）。

## Files and interfaces

- `development/git_support.py`: 受控 Git 子进程、原子 JSON、跨进程可重入锁、提交/树读取。
- `development/git_workspace.py`: `GitWorkspace.create(project, control, ref='HEAD')`、`snapshot()`、`inspect()`、`freeze()->str`、`mutation_lock()`、`archive()`；继承受限编辑协议。
- `development/workspace.py`: `ProjectWorkspace.create(..., mode='git_worktree')` 与 `open()` 分发，保留 `mode='snapshot'`；新模式从 Git 读取基线。
- `development/git_delivery.py`: `GitDelivery(workspace, launcher=None)`，`prepare(kind='merge', operation_id=None)`、`resolve(preparation_id)`、`check(preparation_id)`、`status()`、`approve(preparation_id, approval_hash, _after_merge=None)`；所有 ID 都查持久记录。
- `development/adoption.py`: legacy 保留，新任务显式拒绝旧直接写回接口。
- `development/service.py`, `web.py`, `__main__.py`: 新默认、模式绑定、同一锁、交付/清理 API。
- `frontend/src/GitDeliveryPanel.tsx`, `DevelopmentPage.tsx`: 独立交付面板及 legacy 显示。

## Verification commands

Python: `D:/Desktop/mihoyo-agent-project/.venv/Scripts/python.exe`，环境 `PYTHONPATH=<repo>/src;<repo>/tests;<repo>/scripts`，`PYTHONUTF8=1`。使用 unittest，不使用 pytest。
Frontend: bundled Node + `E:/Nodejs/node_modules/npm/bin/npm-cli.js`，`npm test -- --run` / `npm run build`。

### Task 1: 真实工作树、差异和编辑保护

**Files:** 新增 git_support.py、git_workspace.py；修改 workspace.py；新增 tests/test_development_git_workspace.py；旧 workspace/adoption fixture 显式 snapshot。
**Consumes:** ProjectWorkspace 既有 snapshot/read/write 协议。
**Produces:** 上述 GitWorkspace 接口；metadata mode、task_branch、target_branch、baseline_commit、candidate_commit、git_dir/common_dir；`mutation_lock()` 同进程重入、跨线程/进程互斥。

- [ ] 写失败测试：`test_real_worktrees_keep_source_and_secret_untouched` 验证两个工作树被 Git 登记、源 HEAD/文件不变、tracked .env 不落盘；`test_git_diff_add_delete_and_no_newline` 验证 Git diff 可 apply；`test_external_head_index_and_pointer_changes_rejected`；`test_edit_replay_and_cross_process_lock`；`test_old_snapshot_still_opens`。
- [ ] 运行 `python -m unittest test_development_git_workspace -q`，Expected: 新工作树断言失败。
- [ ] 实现隔离分支、no-checkout/稀疏检出、身份核验、Git diff（含新增）、受限 freeze 和跨进程锁；不改其他工作树检出行为，不执行 hook/filter/textconv。读取只用固定 Git 对象；保留 SQLite 编辑记录。
- [ ] 运行新测试和原 workspace/adoption/checks，Expected: 全通过。
- [ ] 提交本任务代码与测试。

### Task 2: 准备合并、人工冲突处理、检查和审批

**Files:** 新增 git_delivery.py、tests/test_development_git_delivery.py；必要时检查协议小幅扩展。
**Consumes:** GitWorkspace.freeze、snapshot、mutation_lock；CheckJobs.start/read/list。
**Produces:** GitDelivery prepare/resolve/check/status/approve；准备记录 T/C/M、tree_hash、approval_hash、patch、checks、state、kind，持久操作状态。

- [ ] 写失败测试：`test_merge_preserves_target_changes_and_requires_new_rules_receipt`、`test_stale_approval_and_dirty_source_rejected`、`test_conflict_resolution_requires_staged_allowed_files`、`test_merge_lost_ack_reconciles_once`；断言真实 Git parents、文件字节和原目录不提前改动。
- [ ] 运行新测试，Expected: 新交付服务不存在或行为断言失败。
- [ ] 实现 merge-tree / 独立交付工作树、commit-tree、来源身份与范围检查；冲突后允许人编辑和 git add，确认后固定 M。每次准备有独立 CheckJobs 目录，旧候选 PASS 不算交付 PASS。
- [ ] 审批前保存 T/M 意图，确认后取得仓库锁再次校验，再执行 merge --ff-only。中断只按实际 HEAD 对账，不覆盖其他版本。
- [ ] 运行 Task 1+2 测试，Expected: 全通过；提交。

### Task 3: 撤销和清理

**Files:** git_delivery.py、git_workspace.py；Task 1/2 测试补用例。
**Consumes:** GitDelivery 持久准备/执行记录。
**Produces:** prepare(kind='revert', operation_id=...) 与通用 approve；archive() 保存只读快照和差异后移除已登记工作树。

- [ ] 写失败测试：`test_revert_adds_commit_and_rejects_later_changes`、`test_archive_preserves_evidence_and_rejects_unknown_files`、`test_pending_jobs_and_operations_block_cleanup`、`test_partial_creation_does_not_remove_unowned_path`。
- [ ] 运行这些测试，Expected: 新行为失败。
- [ ] 在独立交付工作树准备撤销（第一父提交差异），重新检查审批；要求原分支仍为 M 且干净。清理只移除已登记且干净的自有工作树，保留提交引用、报告、回执，不删除未知改动。
- [ ] 运行 Task 1–3 测试，Expected: 全通过；提交。

### Task 4: 接入任务、HTTP、CLI 和页面

**Files:** service.py、web.py、__main__.py、adoption.py、GitDeliveryPanel.tsx、DevelopmentPage.tsx；Python HTTP 和前端测试。
**Consumes:** Task 1–3 的精确接口和状态。
**Produces:** HTTP actions `delivery-prepare(kind,operation_id?)`、`delivery-resolve(preparation_id)`、`delivery-check(preparation_id)`、`delivery-approve(preparation_id,approval_hash)`、`archive(tree_hash)`；CLI 同名子命令。summary 包含 delivery；旧 adoption 保持原含义。

- [ ] 写失败测试：新建任务默认 git_worktree，旧 apply 拒绝；新 HTTP 准备→检查→批准→撤销；源漂移/旧 approval_hash 返回 422；模型运行时同仓任务交付被锁阻止；旧任务页面仍可打开。
- [ ] 写前端测试：Git 模式显示合并结果与单独检查；确认用显示时冻结的 preparation_id/approval_hash；刷新变化关闭旧确认；冲突目录提示；撤销说明与归档只读；legacy 原按钮不变。
- [ ] 运行新 API/前端测试，Expected: 失败。
- [ ] 接入服务端同一写锁、scope 工作区身份；封装新面板，明确“用户审批的是哪份差异”。不让 Agent 获得合入/撤销工具。
- [ ] 运行相关 Python 测试、全部前端测试和构建，Expected: 全通过；提交。

### Task 5: 真实演示、完整回归与中文交付

**Files:** scripts/probe_git_worktree.py、research/evidence/git-worktree-20261028.md、项目说明.md、开始使用.md、开发记录.md、current_context.md。
**Consumes:** 已接入的真实任务、工具、检查与交付接口。
**Produces:** 可重复临时游戏 clone 演示及真实日志，说明工作树与 Docker 不同职责，旧记录边界。

- [ ] 演示使用现有脚本模型修复资源输入问题，实际工具编辑候选、真实 Docker 检查，Git 合并和撤销；打印并保存源/候选/合并/撤销提交、回执、前后文件摘要。原游戏只读，费用 0。
- [ ] 运行 `python -m unittest discover -s tests -q`、前端全部测试/构建、git diff --check，Expected: 全通过或明确已有 skip；日志存 local-data/worktree-migration-20261028。
- [ ] 独立代码审查全改动；Critical/Important 用失败复现后修复，再运行受影响及完整回归。
- [ ] 更新中文材料、验证数字和已知边界；提交，不自动 push。交付实际可运行结果与简短面试表达。

## Execution ledger

Pre-flight Task 1→2→3: GitWorkspace snapshot 与 CheckJobs 保持原协议，GitDelivery 的准备与审批 ID 贯穿撤销；无接口冲突。
Pre-flight Task 2/3→4: 所有交付都经过 GitDelivery，legacy Adoption 不可写新模式；无接口冲突。
Pre-flight Task 4→5: HTTP/CLI 共用服务；演示复用相同接口，不另造捷径；无接口冲突。
