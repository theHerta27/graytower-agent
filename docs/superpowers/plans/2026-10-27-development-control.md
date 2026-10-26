# 研发Agent上下文与收尾修复计划

> **For agentic workers:** 使用superpowers:executing-plans与test-driven-development；主线程实现，独立诊断后只做一次整体代码审查。现有隔离工作树feature/reliable-game-agent继续使用。

**Goal:** 让源码读取可准确续读、压缩后的上下文仍可理解，并阻止工具协议文本被当成最终交付。

**Architecture:** 保留一个LangGraph动态决策Agent。确定性程序负责分页、上下文证据索引、剩余额度提示和协议校验；不规定调查/编辑/检查步数，不解析DSML执行，不自动增加调用。

**Tech Stack:** 现有Python、LangGraph、LangChain/ChatDeepSeek、SQLite、Git/Docker；不加新依赖。

**Spec:** current_context.md的本轮后续方向、research/evidence/knowledge-rag-20261027.md，以及local-data/development-control-20261027两份只读诊断。

## Global Constraints

- 基线提交034d520，旧模型记录、分数和授权保持原样；新收费不得复用余额，不自动推送。
- 原游戏、Herta和旧V1只读；修改仍仅发生在隔离候选，人工采用权限不变。
- 精确编辑、Job、稳定模型decision ID/输入冻结与崩溃恢复逻辑保持；不得因错误输出自动重发模型调用。
- 官方协议默认无tools即none，因此“移除tools诱发DSML”只是待验假设；可确定缺陷是没有识别无效交付。
- 本地回放证明程序行为，不宣称DeepSeek修复质量提升。

## Review Focus

长中文/单行源码可续读且没有缺字；旧任务恢复不改变已冻结决策；裁剪不制造无效JSON或孤立工具调用；协议错误保留响应和费用；正常解释/代码引用不被DSML守卫误伤。

## Task 1: 收尾协议（model.py、agent.py及对应测试）

- [x] RED：真实ChatDeepSeek/MockTransport验证final_only显式tool_choice=none且保留工具定义；原DSML响应不得completed，已收费决定重读不发新HTTP；正常工具和中文交付仍通过。
- [x] GREEN：明确关闭工具选择，识别顶层DSML调用文本为已知协议失败，落原始响应和用量后返回可读的未完成状态，不执行文本。

## Task 2: 源码分页与有限上下文（tools.py、context.py、agent.py及测试）

- [x] RED：中文超长页/长单行按next_line/next_column拼回原文；工具正文与压缩JSON保持有效；旧组被移出后仍有路径/范围/来源索引；最近期完整工具配对、预算与候选版本保留。
- [x] GREEN：read_file按序列化字节预算返回实际页与准确续读游标；避免二次正文截断；压缩优先移出旧组、保留短证据索引，必要时用显式省略JSON而非字符串截断。每次决定提供剩余调用提示，不强制模型必须修改。

## Task 3: 验证与交付

- [x] 回放两份真实失败的末条响应，保留新旧行为对照；同一真实游戏副本完成读/改/真实Docker检查业务探针（明确脚本模型）。
- [x] 独立审查，重要问题先RED后修复；完整相关回归与构建，更新中文过程及限制。
- [x] 保存本地分支；如需真实模型开发回归，先封存新范围和预算并具体授权，不改旧分数、不宣称独立质量确认。
