# 研发资料检索小评测

本包用于本地词法检索验收：2份文档中的6个完整已审章节、12条人工标注查询（dev 6条、holdout 6条），以及8项代表性业务任务清单。它不执行模型、不运行Docker、不修改游戏，也不读取独立验收真值。

这里的确认是 **audit_fixture_only**：评测在全新输出目录创建自己的Task和SQLite KnowledgeBase，并按清单自动确认。这不是向实际工作台资料库导入或确认资料的授权。原游戏只读，候选不编辑。真实LangGraph三题基线与后续知识对照另行验收，本包没有任务质量增益结论。

## 固定资料

`corpus.json`绑定游戏 `D:/Desktop/graytower-game`、HEAD `5508730ebbb1410f17697d7ad2a3804f3e062818`、确切路径、heading、原Git blob及完整章节SHA-256。原文完整导入，不截掉一句后重写成“干净来源”。清单选择：

- DESIGN：4.4 速度与行动值。
- IMPLEMENTATION_SPEC：3.1 Weakness配置与削韧判定、4.1 固定策略集合、5.1 时间/被动/同刻行动、5.2 原子动作/状态次序、6. Combat Trace与报告。

不导入混有旧Unity状态的3.2、文首状态、未来权限、计划、历史验收、修复记录或模型结论。规则源码和Pydantic契约仍由代码工具读取，不放入Markdown知识库。不同版本、源hash或片段hash一律拒绝，不能悄悄使用当前文档代替冻结版本。

Git blob通常使用LF，而Windows工作区可能使用CRLF；本包hash按Git原始字节计算，不能直接使用工作区文件hash替换。每个heading单独导入，形成独立document_id，再映射回清单source ID。

## 执行与产物

在项目根目录、已有依赖齐备的Python环境中执行，输出目录必须不存在且在原游戏项目外：

```powershell
python scripts/evaluate_knowledge.py --project D:/Desktop/graytower-game --output D:/Desktop/mihoyo-agent-project-next/local-data/knowledge-rag-20261027/retrieval-eval-01
```

失败目录保留诊断，不复用原目录。无需API Key，费用0。CLI只提供本地检索评测，没有运行真实模型或付费任务的分支。Python接口为 `evaluate_retrieval(project, output, corpus_path=默认, queries_path=默认)`，自定义清单主要用于独立Gitfixture测试。

输出包含：冻结的 `corpus.json/queries.json/snapshot.json`、`source-map.json`、完整逐条 `results.json`、中文 `evaluation-report.md`、产物与实现hash的 `manifest.json`，以及隔离Task/资料库。快照在第一条查询前写入。每条结果保留原文、来源/版本/行号、document_id/chunk_id、匹配原因、排名、耗时和未召回项。若失败则保留 `failure.json`。

## 指标与标注边界

期望相关单位是来源/章节ID。每条查询取检索API原始前5个chunk，使用chunk.document_id映射章节。相同章节的多个chunk仍占用名次，不把结果去重后重新提升排名；Recall分子对相关章节去重。

- Hit@K：至少一个预期相关章节出现在前K项。
- Recall@K：前K项召回的不同预期相关章节数，除以该查询全部预期相关章节数。
- 两者仅在expected非空查询上求宏平均，分别报告all/dev/holdout的K=1、3、5；无分母为null。
- expected为空的问题单独报告false-positive@K（前K出现任何结果即误召回），不混入Hit/Recall分母。

含一条英文同义表达（haste gauge carryover）用于暴露词法漏召回，以及一条库中无资料的烹饪问题。查询在运行前固定，不根据分数反复改题，不添加同义词把漏召回修成命中。holdout未用于调参，但作者已审阅相同规则文档，仍只是小样本留出；不能声称盲测、总体泛化或真实研发成功率。

## 业务任务清单

`tasks.json`共8项。前三项 resource-atomicity、configurable-cap、shield-toughness-review明确沿用已有公开开发基线；其独立验收只在冻结候选后本地执行，不由此包运行。后五项为速度距离、同刻排序、状态/DOT、控制免疫、零胜利AV规则核查，均是 `manual_with_evidence`、`pending`，没有独立可执行grader。合理不改代码可以是review任务的正确结果。

8项清单不构成“8题自动修复基准”。只有三题真实任务完成并复核最终解释、独立验收和费用收据后，才能分别报告该批实际表现；检索分数不能代替任务结果，也不能单独证明资料检索提升了模型质量。

## 本地测试

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p test_knowledge_evaluation.py -v
```

覆盖手算宏平均/重复chunk排名/负查询、错版本和源hash、片段hash、非法期望来源、输出隔离、真实临时Git项目完整执行及保留同义漏召回。真实游戏完整评测由总集成时另行运行并保留所有结果，本包不预填分数。
