# 给简历撰写AI的项目资料

> **2026-10-25当前主线优先说明：** 已在同一next工作树实施LangGraph＋LangChain单研发Agent，替换新默认路径的Codex Runtime，新增有限上下文、基本恢复和SQLite项目记忆。当前事实与简历建议请先读[项目说明](项目说明.md)。下方10月23日资料中的Runtime路线、无记忆和不支持模型任务恢复表述属于历史，不能再作为新默认架构介绍。
>
> 路径仍为 `D:\Desktop\mihoyo-agent-project-next`，游戏为 `D:\Desktop\graytower-game`；GitHub仍为私密仓库 https://github.com/theHerta27/mihoyo-agent-project ，分支 `feature/reliable-game-agent`。**2026-10-25已按用户要求推送框架改造提交e04d058，远端SHA已核对；main仍是旧版本。** 主入口agent.py/model.py/context.py/memory.py位于src/agent_workbench/development，候选/检查/采用领域模块继续复用。
>
> 新框架已完成脚本模型＋真实Docker工程链路，不把它写成DeepSeek成功率。此前34次真实Runtime调用及失败保留，新框架仍待真实模型任务确认。不写多Agent/A2A为当前主线，不要求优于通用Agent，不虚构商业用户或提升比例。

整理日期：2026年10月23日。用于读取本地材料、核对事实并撰写Agent开发岗简历。**重点是简单、具体、能解释清楚，不堆技术名词，不把目标当成成果。**

**10月24日补充：** 已准备三项真实任务并在原游戏中确认待修问题/正确行为，补了精确片段替换；用户随后选择暂不调用模型，因此仍无新链路真实模型修复成绩。原游戏99项通过不能写成99个修复任务；可选领域诊断和对照已暂停，不增列为当前卖点。

## 1. 项目是什么

推荐名称：**灰塔——面向游戏规则的代码修复Agent**。

一句话介绍：开发者描述游戏规则问题，Agent在隔离候选中阅读和修改代码、调用真实检查并获取反馈，最后交付代码差异和检查记录，由人决定采用或恢复。

项目面向个人游戏开发者，目前适配自研回合制游戏“灰塔”的Python规则与配置。它是个人工程项目，不是已经在企业团队上线的商业产品，也不支持任意游戏、任意语言。

做这个项目的原因：AI生成补丁不等于问题已修好。游戏里的伤害、护盾、战技点和回合时序存在关联，需要检查真实行为；同时不能让AI直接覆盖开发项目，也不能让模型的一句“通过”代替执行依据。

建议作为**一个项目**介绍。主线是“代码调查与修改→真实验证→人工交付”，不拆成Coding、Config、Verification、NPC四个独立求职项目。

## 2. 本地目录与GitHub

| 用途 | 本地绝对路径 | 说明 |
| --- | --- | --- |
| **当前主线，优先读取** | `D:\Desktop\mihoyo-agent-project-next` | 当前研发助手实现；同一工作台Git仓库的独立工作树，不是另一个GitHub仓库 |
| **真实游戏代码** | `D:\Desktop\graytower-game` | Python游戏规则、配置、测试及已有Unity等游戏资产；当前Agent只适配其中允许的规则和配置范围 |
| 工作台旧版V1 | `D:\Desktop\mihoyo-agent-project` | 保留旧四能力、固定案例和历史实验；当前主线材料优先于这里的旧方案 |
| 早期Coding参考 | `D:\Desktop\herta-agent-coding` | 历史草稿，不是当前主线入口 |
| 早期游戏底座 | `D:\Desktop\combat-foundation` | 历史底座，不要与当前graytower-game混淆 |
| Codex参考源码 | `D:\Desktop\codex-main` | 调研参考；不是当前成品自行编写的Runtime源码 |

GitHub地址（私密，需要有权限的账号登录）：

- 工作台仓库：https://github.com/theHerta27/mihoyo-agent-project
- **当前主线分支，读取代码应使用此链接：** https://github.com/theHerta27/mihoyo-agent-project/tree/feature/reliable-game-agent
- 已推送的代码提交：https://github.com/theHerta27/mihoyo-agent-project/commit/79742cecb1cbb39845c90b5c68c55cdfb9537223
- 配套游戏仓库：https://github.com/theHerta27/graytower-game

2026年10月19日已推送上述工作台分支，并核对远端与本地提交一致。`main`仍保留旧版本，不要只读默认分支后判断新能力不存在。游戏验收所用提交为 `5508730ebbb1410f17697d7ad2a3804f3e062818`。

本说明是10月23日本地新增文档，不表示它已经随10月19日的提交上传。

## 3. 当前实际实现的流程

1. 用户选择灰塔Git项目，输入一个新的规则代码需求；不需要匹配历史演示题号。
2. 系统从已提交的版本建立受限候选，记录基线和文件身份；AI默认不能写原游戏。
3. 用户确认模型材料和费用后，启动一个Codex Runtime任务。Agent可选择检索、读文件、修改候选、开始检查及查询结果，不按固定“读一次→改一次→结束”脚本运行。
4. 检查在本机Docker中执行，反馈真实退出状态、测试结果及日志。工程上支持同一Runtime任务根据失败继续修改、再检查。
5. 页面展示真实源码Diff、修改说明和检查记录。代码改变后，旧检查不再证明当前候选通过。
6. 用户审阅后可以采用、放弃或导出。采用前备份原字节；恢复遇到后来编辑或Git版本变化会停止，避免覆盖。

采用需要当前可信检查通过且没有当前失败，但局部通过不代表所有需求正确。系统不自动提交Git，不自动更新Unity。

## 4. 技术栈各自解决什么

| 技术 | 当前作用 |
| --- | --- |
| **Codex Runtime＋官方Python SDK** | 复用模型与工具调用的主循环、会话及事件机制；项目没有自研或复制一套Runtime |
| **DeepSeek** | 成品模型服务，默认deepseek-flash；通过项目适配的Responses调用链路接入，密钥保留在服务端 |
| **Python＋Starlette** | 提供本地API和业务Service；页面与CLI复用同一套候选、检查和交付逻辑 |
| **Git基线＋候选快照** | 记录来源版本、文件和Diff；当前候选是按允许范围物化的快照，不应误写成“每个任务必然创建完整Git worktree” |
| **Docker** | 在受限环境运行冻结候选的回归和探索诊断，避免把任意宿主命令交给Agent；不宣称通用恶意代码安全 |
| **SQLite＋执行回执** | 保存编辑幂等记录、检查Job和采用备份，中断后核对真实执行结果，未知作业不自动重跑 |
| **React＋TypeScript** | 展示需求、源码前后变化、真实检查、实际工具操作与人工交付按钮 |

**我们增加的工程：** 游戏相关动态工具、路径和权限限制、候选版本管理、检查与候选绑定、真实结果回读、预算确认、采用及恢复、可审阅的本地工作台。

**我们复用的能力：** 官方Runtime和SDK负责Agent的底层推理/工具循环。它们是外部安装依赖，不是本项目自主实现的源码；无需把SDK环境或Runtime二进制当业务源码上传GitHub。

## 5. Agent、检索和协作的准确说法

- 当前是**单Agent＋可信执行工具＋人工交付**。确定性检查程序不是一个独立Agent。
- Agent在工具结果基础上决定下一步调查和修订；路径校验、检查执行、结果身份、预算和采用权限由程序控制。
- 当前代码检索是文字检索，返回文件和行号；支持分段读取及工具结果长度限制。不要写成已实现向量数据库、语义检索、AST符号图或完整RAG系统。
- 新默认路径不启用子Agent、Review、A2A或旧MCP服务，也没有给Codex再套一层LangGraph主循环。
- 旧V1确实保留了LangGraph、MCP、A2A及协作实验，但应作为**历史实现和技术探索**单独解释，不能写成当前默认主线用了全部框架。
- NPC已退出新主线。没有充分证据证明多Agent带来稳定修复质量提升，不以此作为简历成果。

## 6. 哪些有证据，哪些仍待验证

| 事实 | 能说明什么／不能说明什么 |
| --- | --- |
| 匹配Python3.11.9环境后，完整游戏规则99项通过 | 证明对应基线的规则回归可真实执行；不是99个AI修复任务，也不是模型修复成功率 |
| 真实SDK/Runtime＋真实Docker完成“失败→修订→通过” | 决定来自本地脚本响应，证明工具反馈链路可用；不能冒充真实模型自主修复 |
| 页面在临时游戏clone走通创建、手工加注释、99项检查、采用和恢复 | 证明页面及交付链路，真实原游戏未改；不是AI完成了修复 |
| 完整工作台Python回归286项：282通过、4项既有跳过；随后状态小修后新模块57项通过 | 工程回归记录，两个数字有重叠，不相加；不声称最终又跑过全量287项 |
| 前端18项通过，TypeScript/Vite构建通过 | 对应页面工程检查，不是用户满意度或业务效率评估 |
| 真实原游戏有负数战技点输入的状态副作用问题，额外检查4PASS／2FAIL | 作为未注入的真实待修问题保留；新链路尚没有真实模型完成该题的验收记录 |

**当前不足：** 新主线真实模型自主修复质量、独立任务成功率、效率收益和费用实绩尚未验收。10月18日这轮工程交付没有外部模型调用，不代表整个历史项目从未调用真实模型。旧V1有真实DeepSeek调用和修复记录，但不可移作新链路的成绩。

不写“修复成功率达到X%”“显著提高效率”“多Agent提升X%”“生产级通用沙箱”“已完成Unity自动发布”等没有对应证据的结论。

## 7. 建议另一个AI读取的材料

以本说明、当前源码及实际证据为准；老文档中的“目标版简历”“待实现方案”不作为已完成事实。

| 材料 | 本地绝对路径 |
| --- | --- |
| 当前业务与技术说明 | `D:\Desktop\mihoyo-agent-project-next\项目说明.md` |
| 开发过程与失败记录 | `D:\Desktop\mihoyo-agent-project-next\开发记录.md` |
| 当前状态（优先读顶部，下面有历史） | `D:\Desktop\mihoyo-agent-project-next\current_context.md` |
| 中文使用说明 | `D:\Desktop\mihoyo-agent-project-next\开始使用.md` |
| 本轮工程证据摘要 | `D:\Desktop\mihoyo-agent-project-next\research\evidence\development-delivery-20261018.json` |
| 页面采用/恢复实际回执 | `D:\Desktop\mihoyo-agent-project-next\local-data\delivery-browser-20261018\result.json` |
| 本地开发命令原始记录 | `D:\Desktop\mihoyo-agent-project\local-data\development-logs\20261018` |
| GitHub上传核对记录 | `D:\Desktop\mihoyo-agent-project\local-data\development-logs\20261019` |

当前源码主目录：`D:\Desktop\mihoyo-agent-project-next\src\agent_workbench\development`。

优先检查：`runtime.py`／`runtime_worker.py`（官方SDK接入）、`tools.py`（工具和参数边界）、`workspace.py`（候选与Diff）、`checks.py`／`sandbox.py`／`check_worker.py`（执行和回执）、`adoption.py`（采用恢复）、`service.py`／`web.py`（业务与API）。文件均位于上述development目录。

前端入口：`D:\Desktop\mihoyo-agent-project-next\frontend\src\DevelopmentPage.tsx`。

游戏规则：`D:\Desktop\graytower-game\game-core\combat_core\v2`；可信回归：`D:\Desktop\graytower-game\game-core\tests\v2`。

这项任务只需阅读核对，不需要读取或输出密钥、启动收费模型、修改游戏源码或执行新实验。

## 8. 简历怎么组织

用一段背景加三点实现即可，聚焦：**Agent工具接入、真实验证、隔离交付。** 技术取舍解释为：复用成熟Runtime，把工程投入放在游戏上下文、可信工具和修改交付上。

难点可以选择本人能解释清楚的两项：

1. 检查结果必须对应实际执行的代码版本，不能让修改后的候选沿用旧通过结果。
2. 模型说明与真实执行结果分开，探索诊断不当作可信验收。
3. 中断、重复请求和丢响应不能导致重复副作用；采用可以恢复，但不能覆盖后来编辑。

不要虚构商业使用规模、团队职责或个人手写贡献。项目使用AI辅助开发；个人职责和掌握程度需要向求职者本人确认，不从仓库代码量或提交记录推断。最终简历只保留本人理解并能够复盘的内容。
