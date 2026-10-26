# 灰塔研发资料检索与小规模验收实施计划

> **For agentic workers:** 使用superpowers:executing-plans；独立模块可委派并行，最后独立审查。用户已明确批准推进，普通步骤不重复确认。

**Goal:** 在现有单Agent中接通有出处和版本的研发资料检索，交付可用的页面与本地评测，并准备新LangGraph真实任务验收。

**Architecture:** 保留LangGraph决策循环和LangChain模型/工具组件。SQLite管理资料与FTS5/BM25检索；中文双字及英文标识符预处理。模型只能读冻结的已确认资料，不拥有导入/确认/删除工具。当前真实基线明确关闭新增知识工具；不更改旧实验和授权。

**Tech Stack:** 现有Python、SQLite FTS5、LangGraph、LangChain Core/DeepSeek、Starlette、React/TypeScript、Git、Docker；不新增LlamaIndex、Embedding服务或向量数据库。

**Spec:** 用户已认可“先现有LangGraph真实任务验收，后研发资料检索及6～10项代表性任务评测”，并确认框架采用需说明职责/成本。工程可并行准备；真实收费先执行无新增知识的基线，再决定新增知识的模型对照。本文将该已批准方向具体化，不提出另一轮大架构。

## Global Constraints

- 只在next既有feature/reliable-game-agent工作树实施；原游戏、Herta、旧V1、封存实验只读；本轮不自动推送。
- 新收费任务必须在材料、接口、调用次数、费用cap封存后得到具体授权；旧批次全部关闭，不重用余额。
- 本机单服务/SQLite；一个Agent，人工采用/恢复入口不变；模型没有发布和资料确认权限。
- 来源仅为当前游戏Git基线中明确选择的README/docs Markdown；按章节预览/导入，先pending再人工confirmed。
- 资料快照按项目与基线版本筛选，初次发送前核对变化；恢复只读本次封存快照；保留原始来源/行号/内容身份。
- 不把旧计划当现行规范，不把参考补丁、评分真值或同题修复记录送入模型。
- 不以脚本模型、工程测试数或几道开发题冒称真实模型成功率/稳定质量提升。

## Review Focus

- 导入路径越界、符号链接或过大文本必须拒绝，不能打开任意本机文件。
- pending/旧版本/另一项目资料不能进入工具结果；准备后确认状态或正文变化使初次发送失效。
- 查询FTS语法不能注入；相同文档多次导入幂等；冻结检索不能受运行中数据库变化影响。
- 旧的off任务/暂停恢复保持相同工具契约；新知识调用与引用在实际过程可见。
- 真实模型基线与知识对照分开，失败/未知计入预算，不自动重跑，候选验收与完整交付分别记录。

## Task 1: 资料与冻结检索

**Files:** development/knowledge.py、tests/test_development_knowledge.py；资料审计在本轮local-data。

**Interfaces:** KnowledgeBase(database).sources(workspace)、preview_file(workspace,path)、import_file(workspace,path,headings=None)、list(project,version=None)、set_status(project,id,status)、delete(project,id)、snapshot(project,version)。search_knowledge(snapshot,query,limit=5)、read_knowledge(snapshot,chunk_id)。

- [x] 写失败测试：真实Git章节导入与行号、状态/版本/项目过滤、非法路径、幂等、中文/英文查询、冻结后删改不影响已有快照。
- [x] 实现SQLite资料存储、Markdown章节切片和FTS5/BM25；返回片段ID、出处、版本、匹配依据；不调用模型。
- [x] 跑模块测试并保存RED→GREEN结果。

## Task 2: 新框架真实任务基线入口

**Files:** development/assessment.py、tests/test_development_assessment.py、scripts/assess_development.py。

**Interfaces:** prepare_assessment(project,root)、verify_assessment(root,scope_hash)、run_assessment(root,scope_hash,api_key,model_factory=None)。复用既有3公开任务及本地独立grader，明确knowledge_mode='off'，不修改旧evaluation.py/旧批次。

- [x] 写失败测试：完整封存、错scope零调用、每题一次/恢复不重发、失败计入、不发私有grader、终止收据保留。
- [x] 实现Chat接口deepseek-flash非思考基线，18/24/10次合52次；100000B输入/4096输出，峰价保守cap分别0.65/0.86/0.36美元，总cap1.90美元。
- [x] 先离线脚本边界验证，再准备真实材料；授权未到不调用。

## Task 3: 图、服务、页面

**Files:** development/agent.py、service.py、web.py、__main__.py、frontend/src/DevelopmentPage.tsx及相应测试。

**Interfaces:** create新增knowledge_mode='lexical'或'off'，历史缺省按off；KnowledgeBase与memory分别注入，prepare含冻结知识快照。agent_specs增加可选search_knowledge/read_knowledge，原off工具契约不变。模型按需查资料，原循环和采用权限不变。

- [x] 测试先行，接通预览/导入章节/确认/删除/本地试搜；页面标清历史资料和适用版本。
- [x] 封存所有可检索资料，不仅初始命中；初次运行检查资料变化，恢复不查询可变库。
- [x] 页面展示真实检索与来源，不要求用户选择检索算法；高级开关用于基线。
- [x] 跑前后端回归与构建。

## Task 4: 评测、业务验证和交付

**Files:** scripts/evaluate_knowledge.py、research/evals/knowledge-rag-v1/*、中文说明和开发记录。

- [x] 先使用审计通过的章节构造少量标注检索查询，区分调试/保留查询；运行本地检索评测，报告Hit@K和Recall@K，不冒称端到端修复率。
- [x] 准备6～10项代表性业务任务清单和独立验收要求，不制造50个“自然BUG”；旧3题明确为开发基线。
- [x] 真实浏览器与真实Git/Docker验证产品入口；独立代码审查，重要问题复现后修复。
- [x] 具体授权到达后仅跑已封存真实基线，保留全部失败及用量；否则交付工程与可亲测入口，明确真实模型待验收。
- [x] 更新当前方案/路线/中文说明/透明开发记录，完整回归；本轮不自动推送GitHub。
