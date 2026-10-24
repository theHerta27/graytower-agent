# 游戏研发Agent真实任务与领域工具对照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** 在不修改原游戏的前提下，完成三类真实需求的验收准备、可实际使用的游戏诊断工具和一次公平的小规模模型对照，形成能复盘的结果。

**Architecture:** 沿用单Codex Runtime/官方SDK，不添加Agent调度层。standard保留检索、读写、精确替换、可信检查和任意受限Python诊断；game仅额外提供结构化run_scenario。两者相同模型、初始提交、任务要求和调用上限，逐次独立候选。

**Tech Stack:** 既有Python/SDK0.160.0、SQLite、Docker Python3.11.9；无新依赖。

**Spec:** 用户2026-10-24已认可的“真实任务验收→游戏适配对照→案例复盘”，细化约束以下列Global Constraints为准；已有产品边界见项目说明.md。

**最新执行优先级：** 用户随后要求只先完成几项真实任务，暂停领域工具对照；本批仅三题standard各一次，调用分配16／24／8，总48次、cap2.15美元。范围准备后，用户明确选择“暂不调用模型”，因此保持0调用，真实任务与模型案例尚未完成。原计划中涉及game或6单元的步骤均暂停，以此优先级及本计划账本Ruling为准。

## Global Constraints

- 用户已要求开始，沿用现有隔离工作树feature/reliable-game-agent，不再次等待普通实施选择；保留原V1、原游戏、历史授权和本轮过程记录。
- 原游戏5508730只读；所有模型和本地实验只改新候选，不采用、不更新Unity。
- 新收费批次须先封存材料、题目、检查、执行代码与预算，并获得明确授权；历史额度不沿用。准备及等待期间0外部模型调用。
- 三题固定：真实负数资源输入原子性；rules.skill_points_max从固定5改成1..9可配置并保留默认5/旧接口/旧轨迹；核对完全吸收伤害仍削韧的既有正确行为，禁止无依据修改。
- 三题均从相同原提交出发，不将第一题修复带入后题。题目要求公开，独立验收源码与参考修复不发模型。每题每方案一次，standard/game顺序交错，失败不选择性重跑。
- 这是开发pilot，非独立确认集，不据3题宣称总体提升。记录任务正确性、误改、证据、token/费用、Runtime任务耗时；无并行提速或协作收益声明。

## Review Focus

精确替换同ID/不同输入与写后中断；profile与实际工具权限和授权身份一致；诊断参数不能注入宿主代码/路径，错误也保留前后状态；独立验收不能意外进入模型上下文；失败/未知不得重试、删账本或换目录续费。

## Task 1: 版本绑定的精确替换工具

**Files:** workspace.py、tools.py；tests/test_development_workspace.py、test_development_tools.py。
**Interfaces:** ProjectWorkspace.replace_text(operation_id,path,expected_sha256,old_text,new_text)返回原编辑receipt。old_text必须恰好一次，原请求先持久化，可按同ID对账；只编辑既有允许文件。标准和游戏工具均包含replace_text。

- [x] RED：有效片段只改目标、拒绝重复/缺失片段、旧SHA/只读路径、同ID重放/变参、写后中断恢复。
- [x] GREEN：复用write_file持久写入，不另建编辑执行器。工具参数依旧封闭。
- [x] 验证：004九项通过，29674bb保存。

## Task 2: 结构化游戏观察与工具profile

用户已暂停这一方向；代码只作WIP保留，不进入本批standard模型工具，不继续扩建或宣称效果。

**Files:** 新增development/scenario.py；扩展tools.py、runtime.py、runtime_worker.py、service.py；前端仅补工具中文名。
**Interfaces:** scenario_script(scenario_json:str)->str，严格验证不超过8行动的JSON；支持资源变化、普通规则技能、护盾初态与状态到期观察，返回初始/逐步状态、事件、异常，始终OBSERVATION。tool_specs(profile)与instructions(profile)只允许standard/game；默认standard，game额外run_scenario，同一只读候选和Docker作业入口。

- [ ] RED：拒绝额外字段、布尔数、超长/超量动作；参数以JSON数据嵌入，无代码拼接；两个profile的工具、能力hash及运行请求绑定；standard不能调用game工具。
- [ ] GREEN：不复制游戏规则，只调用候选中的真实规则函数；准备与worker双方核对profile。旧准备包保持原件并拒绝过时能力。
- [ ] 验证：纯模块测试、真实Docker观察负数副作用和护盾事件；实际候选/runner/镜像与结果绑定。

## Task 3: 冻结任务、独立验收与真实对照入口

**Files:** 新增research/evals/game-agent-pilot-v1/public/tasks.json、private/acceptance.py；development/evaluation.py；scripts/run_game_agent_pilot.py；tests/test_development_evaluation.py。
**Interfaces:** prepare_pilot(project,root)封存6个单元（standard/game各3题），公开预览不含private验收；run_pilot(root,scope_sha,...)只领取一次；grade_pilot(...)对冻结最终快照运行宿主持有验收和原99项，不把独立验收结果回模型。支持0模型local-check命令。

- [ ] RED：预算合计、封存后漂移拒绝、缺授权不调用、重复运行拒绝、原始首跑结果不覆盖、公开/私有材料隔离。
- [ ] GREEN：复用现有DevelopmentTask与responses账本；每单元最多16次/128k输入/4096输出，峰价保守总上界4.2172416美元，提请总cap4.30美元（实际封存后重新核算）。串行执行，0并行收益声明。
- [ ] 本地检查：原始游戏题1失败/题2缺功能/题3通过；本地临时参考实现仅用于确认验收可通过，不提供给模型。
- [ ] 获明确授权才运行三题真实任务；用户已选择暂不调用，本项未完成。保留0调用，不把准备算效果证明。

## Task 4: 验证、复盘与交付

- [ ] 独立只读收尾审查一次，关键问题一轮RED→GREEN；不派逐任务实现Agent。
- [ ] 完整Python回归；若前端工具标签修改则前端测试/构建。保存所有失败及环境原因。
- [ ] 实际有模型结果后写成功/失败案例、描述性对照；未运行就明确待授权，不伪造提升。
- [ ] 同步开发记录、current_context与简历AI资料，保留工作树与计划，不自动推送。
