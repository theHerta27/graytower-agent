# JSON 决定兼容与 Config 首次确认集

日期：2026-10-05；实施起点：Git `4e2030d`，分支 `v1-business-acceptance`。V1 单机、本地服务、SQLite边界未扩大。

## 本轮业务结果

策划说“只将击破手战技倍率定为1.48，其他配置不要动，交给我确认”，Config读取实际规则与Schema，生成仅一项1.4→1.48的冻结候选，程序预检通过，保持待确认、未应用。该候选现可在[本机工作台](http://127.0.0.1:8766/)查看；生成使用真实Config图和DeepSeek，页面读取的是其实际文件，不是fixture或重新生成的样例。

另外11个冻结需求按原顺序完成：共4个候选（1.48、1.62、1.7、1.43）、4个澄清、4个拒绝。全部第一次调用完成，无修正、失败或未知调用。独立助手随后按冻结标准复核24项语义criterion，**12/12通过**。复核者是开发相关助手，非被测DeepSeek、非盲、非真人；调用成功和语义通过分别核验。

## 技术取舍与验证

上一批2次响应各返回双Decision，安装版LangChain工具解析器只取第一个。这轮源码和离线复现还发现：JSON parser会补齐截断JSON或截取第一个对象，普通invoke也只交回第一个completion choice。因此只改method或提示词不足。

当前Config/Verification默认使用DeepSeek JSON Output：LangChain ChatDeepSeek负责模型接入、消息和用量，公开generate接口保留所有choice；业务适配层只接受一个choice、正常stop终态和一个完整JSON对象，再做Pydantic严格校验。拒绝混合文本、数组、连续对象、重复key、NaN/Infinity与数值溢出、额外字段、错误类型、截断和意外工具调用。SDK提前抛出的length/filter异常仍保留completion及usage，记为失败。正常业务工具继续由图决定后调用确定性领域/MCP入口，没有新增自由执行权限。

保留显式function_calling兼容选项和exact-one检查，但没有自动重试或切换provider。未修改LangChain/OpenAI/DeepSeek/A2A安装包，不维护SDK fork；Coding Runtime的协议适配不因本次修复自动视为完成。

官方JSON Output要求显式JSON格式并提示空输出/截断风险；本项目在此基础上严格拒绝无效输出。[DeepSeek JSON Output](https://api-docs.deepseek.com/zh-cn/guides/json_mode/)。安装版来源可查`.venv/Lib/site-packages/langchain_openai/chat_models/base.py`及`langchain_core/utils/json.py`；依赖仍由`requirements-v1.lock.txt`固定。

### 真实协议回归

只选上轮已封存ledger中第2、5次异常的**原始输入**，固定顺序2/5/2/5；不包含历史答案。每份仅增加JSON schema指令，各首次响应均完整合法，**4/4结构回归通过**。模型提出读取Trace，但本测试不执行决定、工具、图或模拟；旧报告和账本不变。它是已知输入的兼容回归，不是4个独立QA任务、总体故障率保证、QA全链路的新验收或多Agent收益证据。

### Config确认集

沿用此前冻结的`research/evals/config-qa-v1`，首次执行`confirm-c01..12`。每题独立数据目录，仅把该题自然需求与正常Schema/规则/catalog发给模型；`expected`、`criteria`、其他题目、源码、旧答案均不进入payload。每题最多一次确定性反馈修正、全局24次；实际12次全部首答，无选题替换、选择性重跑或prompt调参。

独立复核：24项criterion逐项有原文、理由和完整observation hash，12 PASS、0 FAIL、0待复核；父任务另运行冻结评分器复验。复核文件为`local-data/config-confirmation-v2/independent-reviews.json`（SHA256 `9eee6ddc50fd29871fe2b4b86a7d9ca4abc22bd71441210150feece79bc1376c`），明细及非计分问题见同目录`independent-review-notes.md`。完整confirmation包分母15，结果12 PASS＋3 NOT_RUN。包内3道合成QA解释确认题未运行，不包含在本次12道Config分母；不会把它们计为通过。

## 费用、范围与证据

用户明确授权master scope `8f1aaf8c5f795f35283dcbb7c0ddf6ef5709df68dc868630028e67cd90eb3ed3`，上限28调用、USD1.10、0新战斗。两份子scope分别4次/USD0.10、24次/USD1.00，互不挪额度。Config完整首轮最大15,414字符，离线长修正压力输入最大30,370，因此事前冻结31k上限；协议回归16k。输出均2048 tokens；保守费用上界USD1.055616，不代表预计实耗。

| 批次 | 已用/授权调用 | 输入token | 缓存输入 | 输出token | 峰价估USD |
|---|---:|---:|---:|---:|---:|
| 旧异常上下文JSON回归 | 4/4 | 9,380 | 4,736 | 578 | 0.002115216 |
| Config首次确认 | 12/24 | 55,539 | 5,632 | 1,019 | 0.016228692 |
| 合计 | 16/28 | 64,919 | 10,368 | 1,597 | **0.018343908** |

全部16次completed、0failed、0unknown；新增战斗0、候选确认0、基线应用0。Config批次端到端21.406秒，模型调用合计14.452秒；仅作本轮记录，没有串并行对照，不能宣称提速。未用12次已关闭。费用按2026-10-05官方峰价与实际usage估算，非账单金额。[官方价格](https://api-docs.deepseek.com/quick_start/pricing/)。

- 集中范围/用户授权/关闭：`local-data/json-config-acceptance-v2/`。
- 四次回归原始输入、exact wire、账本、结果：`local-data/json-decision-regression-v2/`。
- 十二题原始输出、候选、账本、逐题复核：`local-data/config-confirmation-v2/`。
- 实际候选页面、只读副本来源与截图：`local-data/config-confirmation-demo-v1/`。
- v1准备保留，因执行前代码审查修复更换为v2；未覆盖旧准备，v1无付费调用。v2是在任何新真实结果前重新封存并获授权。

## 工程检查与产品展示

149项Python测试：147通过、2个既有真实模拟opt-in跳过；pip check通过。前端源文件未变，本轮未重复构建；实际浏览器读取第一道真实候选，显示1.4→1.48、确定性预检通过、待确认/尚未应用及模型关闭。未点击确认，SQLite确认/请求/Job均为0。源码与旧71项seal核对：62项当前字节不变，9项演进文件由Git4e2030d保存并核对，旧模型账本不改。

新测试验证完整wire与preview一致、所有上述响应负例、SDK失败用量、未知预留占额度、每题/共享额度、批次一次执行、输入篡改与fixture来源。独立代码审查发现多choice取首、fixture无工厂可走真实网关两项P2，均已复现修复并复查。

![真实首题候选页面](../../local-data/config-confirmation-demo-v1/candidate-1.48.jpg)

## 下一步与边界

本轮完成的是单决定协议兼容与窄Config能力确认，不能标整个M3完成。QA新版本尚需完整业务链确认；更广Verification任务集、Coding稳定SDK/Runtime正式接入、Unity可玩和完整自动测试、NPC记忆/行动链继续按既定路线。后续优先推进稳定Coding Runtime正式入口与共享QA衔接，同时把QA完整链验收纳入集成批次，避免为同一问题反复追加小额示例。

自然语言可用性也需后续打磨：模型仍使用“审计范围”等工程词；首题proposal_message对预检/确认顺序表述不够清晰，而程序最终消息与页面正确显示已经预检、等待确认。保留原文，不把本次窄rubric通过等同于全部文案完美。
