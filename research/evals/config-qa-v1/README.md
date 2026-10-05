# Config / QA V1 小规模业务验收包

日期：2026-10-05。状态：题目和判分规则已在任何本包真实模型调用之前冻结；**尚无真实模型成绩**。此目录没有联网、读密钥或执行付费调用的程序。`tests/test_business_acceptance.py` 只检验评分器，fixture 不算真实 Agent 验收。

## 范围与划分

目标是判断策划需求有没有被正确理解、已有证据有没有被正确解释。范围限定本机 SQLite、可信数值 Config 和只读 QA 解释；不扩大到代码候选、Unity、自动优化或生产级功能。

| 分组 | 数量 | 用途 |
| --- | ---: | --- |
| Config 开发 `dev-c01..06` | 6 | 明确目标、中文口语、目标缺失、冲突目标、字段越界、数值越界 |
| Config 确认 `confirm-c01..12` | 12 | 精确候选／需澄清／应拒绝各 4 题；一次固定顺序运行 |
| QA 解释开发 `dev-q01..02` | 2 | 负差值与非共同胜利的业务含义 |
| QA 解释确认 `confirm-q01..03` | 3 | 正／零／负分数差值；胜败／超时转换；重复证据不增 n |

`cases.json` 每题包含自然中文需求、输入、独立于产品函数预先推导的真值、逐项语义期望和判断方法。18 个 Config 需求符合路线的 6 开发＋12 确认设计；5 个解释题是当前切片的附加能力检查，**不代表路线中的 24 个完整 Verification 任务已完成**。

确认题未在真实开发中运行，不能用于调 prompt、筛选模型、选择有利配置或选择性补跑。评分器测试只用开发题与手写输出。题作者是开发助手，读过业务规则与当前公开实现；确认题也可在源码中直接读取。因此这里只保证本包尚未付费运行、未用模型输出调参，不是双盲，也不能证明领域泛化。旧 live 原文、seed 11 错误、历史修复结果均未充当新确认题。数值输入为合成验收收据，专门覆盖用户会面对的解释问题；不得伪称为游戏实际跑出的新战斗证据。

开发可改变实现、模型 prompt 和输出策略，确认题与 rubric 不变。第一次真实确认前还需封存实际产品源码、模型 id、prompt、schema、工具、依赖锁、外发 payload 与费用规则的 hash。若确认结果被用于修复，原成绩完整保留，该集转为已知回归；新独立质量声明须另建版本、另冻结新题，不覆盖此包。`freeze.json` 封存本包文件 hash；任何文件变化都会形成新的包版本，不能沿用旧 seal。

## 执行与判断

Config 使用实际 `ConfigAgent.draft()`、真实候选仓库和确定性预检。每题使用独立本地数据目录；只提交待确认候选，不确认、不应用、不模拟。模型看到原题和正常 repository context，看不到 `expected`、`criteria` 或其他题。保存完整输出、次数、修正反馈、候选 manifest/diff、前后基线指纹及预算收据。正确拒绝必须说明本题真正的范围原因；网络失败、无关理由或达到格式修复上限不能算正确拒绝。正确澄清必须提出能解除本题歧义的问题；“请补充信息”或询问无关字段不算完成。

解释题使用 frozen `input.report`，`facts_for_report()` 的实际结果放入观测记录的 `facts`，模型的原始 `summary` / `limitations` 放入 `output`。程序事实和模型自然语言分别评分：程序方向正确不能抵销模型把负数说成更慢的错误。共同胜利子集以同 `(policy, seed)` 的 baseline/candidate 同时获胜为条件；AV 差值是候选减基线。相同配对重复读取只保留一次；相同 seed 的不同策略仍为不同配对，但不据此宣称独立随机样本。

当前 `explain_report()` 只接受已完成的 SQLite request，并没有通用“任意 JSON 报告＋任意问题”接口。本包不增加该产品接口。真实收费解释批次需先准备隔离的合成收据上下文并冻结所用 prompt/适配方式，或在获得授权后只测模型的同结构只读解释能力；后者结果必须标作“合成证据解释测评”，不能当成产品 `explain` 入口或真实 QA 全链路通过。合成收据不得写入历史运行目录，不得计为真实战斗。具体自然中文问题是验收意图；如适配器把问题传入模型，必须如实记录这是与当前 CLI 的差异。

`evaluate.py` 只做两类事：精确核对行为证据；合并外部语义复核。它没有关键词匹配评分，不发起模型裁判调用，也不会自行判断中文的真假。复核者可为独立助手（`independent_assistant`）或真人（`human`），被测模型自评分不接受。没有有效复核即 `PENDING_REVIEW`，不会因为出现“澄清”“拒绝”“负值”“小样本”而 PASS。独立助手复核可完成本地评估流程，不以用户再阅卷作为工程阻塞；它须明确标作助手判断，不能冒称真人标注。

每个 criterion 由复核者读完整原文后填 `pass` / `fail`，引用真实输出并解释为什么满足或违反本题期望。遗漏应说明遗漏了什么，可留空引文。一个解释即使包含正确句子，只要另有矛盾主张，该项仍 FAIL。对于澄清或拒绝，review reason 必须指出原请求中的歧义／越界对象与回答是否对应。独立助手应使用单独上下文，看到冻结需求、rubric 和完整原文，不接收被测模型自己的评分；不能由产生答案的同一模型运行自签为独立。复核身份是审计字段，评分器不能验证填表者诚实，也不是证据签名系统。

程序硬检查失败优先于复核通过。任何必需 criterion 未评，保持待复核；任何一项失败则整题失败。只有全部硬检查和全部语义项通过，才记本题 PASS。每题 `review_source` 与汇总 `review_sources` 保留真人／独立助手／无有效复核三类来源。这里的 PASS 是“按所标来源复核，本题处理正确”，不等于真人验收、候选总体 QA PASS 或数值优化成功。

## 本地记录格式

观测 JSON 是按 case id 索引的对象，以下为结构示例，不是运行证据：

```json
{
  "dev-c03": {
    "output": {
      "status": "needs_input",
      "message": "你希望战技倍率具体调到多少？目前没有生成或应用候选。"
    },
    "audit": {
      "source": "fixture",
      "completed": true,
      "baseline_unchanged": true,
      "battle_count": 0,
      "candidate_created": false
    }
  }
}
```

`output` 保存原始产品结果，不用人工改写成正确答案。Config 候选须有实际 `candidate.diff`、`candidate.validation.passed`、`requires_confirmation`；解释题另含实际 `facts`。`audit` 由独立执行记录填写，不取模型的自述；真实 provider 调用才标 `live`，不能因为程序或模型 fixture 跑通就标 live。程序不验证底层 receipt 的真实性，正式评审应核对账本与原文件。

复核 JSON 同样按 case id 索引，每条含 `source: "independent_assistant"`（真人才填 `human`）、`reviewer`、`case_id`、`observation_sha256` 和 `criteria`。hash 用 `evaluate.observation_hash(observation)` 取得，绑定整个观测记录；修改输出／事实／审计后旧复核失效。每个 criterion 的值形如：

```json
{
  "verdict": "pass",
  "quote": "你希望战技倍率具体调到多少？",
  "reason": "用户只说加强、没有给倍率；该问题明确询问缺失目标，没有擅自选值。"
}
```

评分命令只读本地 JSON 并打印结果：

```powershell
.\.venv\Scripts\python.exe -B research\evals\config-qa-v1\evaluate.py --split development --observations observations.json --reviews independent-reviews.json
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_business_acceptance.py -v
```

缺失记录保留为 NOT_RUN，仍计入固定分母；混用开发／确认记录会拒绝。分别报告每类的通过数/总题数、待复核、基础设施失败、模型错误、首次成功与修正后成功、实际 usage、费用和耗时。一次重试不是新题；重复解释、重复 receipt、修复重跑都不增加独立 n。12 道 Config 确认和 3 道解释确认只支持逐题描述，不给总体成功率保证。

## 本轮待授权的真实批次与费用

具体执行方案为项目中的 `scripts/evaluate_config_development.py`：依次运行 **6 个 Config 开发题 `dev-c01..06`＋固定 `dev-c01` 真实候选的 QA**。本批仍待新授权；本包尚无付费调用。此方案取代此前 USD0.10 的近期建议以及覆盖全部题目的粗略预算。确认集、合成解释题和额外模型解释附录均不在此次调用范围内。

Config 每题最多一次确定性反馈后的生成修正，共最多 12 次；QA 最多 4 次。全部阶段共用一个持久模型账本，总计最多 **16 次模型调用、4 场战斗、新批次 USD0.50**，失败和未知调用也消耗额度。QA 只接受 `dev-c01` 实际生成、通过预检且精确为 1.4→1.6 的候选；该题失败就不执行 QA，不另选成功题代替。获授权的演示操作仅按该候选 manifest 确认并委托 QA，不应用到基线。

脚本冻结每次输入上限 18,000 字符、输出上限 2,048 tokens；按其费用依据——2026-10-05 输入未命中缓存 USD0.30／百万 tokens、输出 USD1.20／百万 tokens——不计缓存优惠。输入按每字符最多 4 个 UTF-8 字节并增加 2,048 token 协议余量保守预留，最坏金额为：

```text
16 × [((18,000 × 4 + 2,048) × 0.30 + 2,048 × 1.20) / 1,000,000]
= USD0.394752 < 新批次 cap USD0.50
```

外发材料限六个开发需求及其 Config preview、同题的有界修正反馈、该固定候选的 diff/预检、4 场配对指标、必要的有界 Trace 片段，以及结构化决策与动态资源余量。以脚本生成的 `local-data/config-development-v1/outbound-scope.json` 和预览为具体审阅对象。旧 8 次批次已经关闭，不重置旧账本，也不把旧授权扩用到本批。触顶、provider 异常或未知结果原样保留，不自动追加调用挑最好成绩。

## 当前代码限制

- Config 只支持 `skills.breaker_skill.multiplier`，基线 1.4，候选必须为实际变化且在 `(1.4, 1.7]`；这不是任意策划表编辑能力。语言理解由模型完成，合法 Schema 不能保证符合需求。
- QA action 仅 `simulate` / `read_trace` / `finish`，没有真正的澄清会话或拒绝动作；本包把需要澄清／拒绝的题放在 Config，避免虚报 QA 已支持。QA 总体只交付 FAIL / INCONCLUSIVE，不能靠解释提升为 PASS。
- `facts_for_report()` 已做配对去重、共同胜利过滤和精确分数。`render_report()` 已显示全部胜负／超时转换，在没有共同胜利或没有已完成收据时明确说明，也会显示模型额度耗尽。它仍不自动核验模型草稿；本包需要同时看事实与完整草稿。
- 模型网关已提供持久账本 `remaining_calls()`，失败和未知调用不返还额度；QA 每次决策前刷新模型与战斗余量，额度耗尽即保留证据并停止。通用网关仍没有美元总 cap 动态扣账；本批脚本用共享 16 次账本、每次输入／输出硬上限及上述保守费用上界限制支出。CLI 默认每数据目录 8 次不是本批额度，不能分散目录规避总账。
- 本包没有执行当前真实服务的独立新任务。一次干净真实 Config→A2A→MCP→游戏→报告与重复委托仍是单独门槛；合成解释和评分器 fixture 不能替代它。A2A 取消／终态续输入、Unity、代码候选和总体统计效力均不在本包验收结论里。
