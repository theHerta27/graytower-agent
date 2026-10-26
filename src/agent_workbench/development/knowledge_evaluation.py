"""Zero-model, audit-fixture retrieval evaluation in a new isolated directory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time

from .knowledge import KnowledgeBase, MAX_FILE, search_knowledge
from .workspace import clean_name, digest, encoded, git

REPO = Path(__file__).resolve().parents[3]
PACK = REPO/'research/evals/knowledge-rag-v1'
KS = (1, 3, 5)
CONFIRMATION = 'audit_fixture_only'


def retrieval_metrics(rows, ks=KS):
    """Macro section recall; duplicate chunks retain their original ranks.

    Hit/recall exclude questions whose expected set is empty. Those questions
    measure false positives separately. Missing denominators are unknown.
    """
    positives = [row for row in rows if row['expected']]
    negatives = [row for row in rows if not row['expected']]
    result = {'queries': len(rows), 'relevant_queries': len(positives),
              'unrelated_queries': len(negatives), 'hit_at_k': {},
              'recall_at_k': {}, 'false_positive_at_k': {}}
    for k in ks:
        if type(k) is not int or k < 1:
            raise ValueError('metric K must be a positive integer')
        intersections = [len(set(row['expected']) & set(row['retrieved_source_ids'][:k]))
                         for row in positives]
        result['hit_at_k'][str(k)] = sum(bool(n) for n in intersections)/len(positives) if positives else None
        result['recall_at_k'][str(k)] = (sum(n/len(set(row['expected']))
            for row, n in zip(positives, intersections))/len(positives)) if positives else None
        count = sum(bool(row['retrieved_source_ids'][:k]) for row in negatives)
        result['false_positive_at_k'][str(k)] = {
            'count': count, 'denominator': len(negatives), 'rate': count/len(negatives) if negatives else None}
    return result


def _read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 200_000:
        raise ValueError('evaluation manifest exceeds supported size')
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('evaluation manifest must be an object')
    return value, raw


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', value):
        raise ValueError('invalid evaluation identifier')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('invalid corpus hash')
    return value


def _validate_inputs(project, corpus, queries):
    if corpus.get('schema') != 'knowledge-retrieval-corpus-v1' or corpus.get('confirmation') != CONFIRMATION:
        raise ValueError('unsupported corpus or audit fixture confirmation')
    if Path(corpus.get('project', '')).resolve() != project:
        raise ValueError('corpus belongs to another project')
    head = git(project, 'rev-parse', 'HEAD').decode().strip()
    if corpus.get('game_head') != head:
        raise ValueError('corpus game version differs from current HEAD')
    sources = corpus.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 30:
        raise ValueError('require a bounded nonempty corpus')
    ids, selections = set(), set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('invalid corpus source')
        source_id = _id(source.get('id'))
        path = clean_name(source.get('path'))
        if path != 'README.md' and not (path.startswith('docs/') and path.endswith('.md')):
            raise ValueError('corpus requires README or docs Markdown')
        if Path(source.get('source_path', '')).resolve() != (project/path).resolve():
            raise ValueError('corpus source path differs from selected project')
        heading = source.get('heading')
        if not isinstance(heading, str) or not heading.strip() or len(heading) > 1000:
            raise ValueError('corpus requires an exact nonempty heading')
        if source_id in ids or (path, heading) in selections:
            raise ValueError('duplicate corpus source or section')
        ids.add(source_id); selections.add((path, heading))
        # Git content, never a possibly changed working-copy Markdown file.
        raw = git(project, 'show', head+':'+path)
        if len(raw) > MAX_FILE or hashlib.sha256(raw).hexdigest() != _sha(source.get('sha256')):
            raise ValueError('corpus source hash differs from frozen Git blob')
        _sha(source.get('section_sha256'))
    if queries.get('schema') != 'knowledge-retrieval-queries-v1':
        raise ValueError('unsupported query manifest')
    cases = queries.get('queries')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise ValueError('require a bounded nonempty query list')
    query_ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('invalid query case')
        query_id = _id(case.get('id'))
        if query_id in query_ids or case.get('split') not in ('dev', 'holdout'):
            raise ValueError('duplicate query or invalid split')
        query_ids.add(query_id)
        text, expected = case.get('query'), case.get('expected')
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ValueError('query must be nonempty and at most 500 characters')
        if (not isinstance(expected, list) or any(not isinstance(s, str) or s not in ids for s in expected)
                or len(expected) != len(set(expected))):
            raise ValueError('query expected sources must be unique corpus section IDs')
    return head


def _write(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encoded(value))


def _format(value):
    return '无分母' if value is None else f'{value:.4f}'


def _report(result):
    lines = ['# 本地资料检索评测', '',
        f"游戏HEAD：`{result['game_head']}`。模型调用0次，费用0美元。",
        '本次只在全新输出目录创建Task和KnowledgeBase；自动确认仅属于审计fixture，不改变实际工作台资料库。', '',
        '相关单位是清单中的来源/章节ID。排名保持原始chunk顺序，同章节多个chunk占用多个名次；Recall对相关章节去重。',
        'Hit@K与Recall@K仅对expected非空查询求宏平均；无相关资料问题单列误召回，不作为命中。', '',
        '| 划分 | 相关查询数 | Hit@1 | Hit@3 | Hit@5 | Recall@1 | Recall@3 | Recall@5 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for split, scores in result['metrics'].items():
        values = [_format(scores[name][str(k)]) for name in ('hit_at_k', 'recall_at_k') for k in KS]
        lines.append('| '+split+' | '+str(scores['relevant_queries'])+' | '+' | '.join(values)+' |')
    lines.extend(['', '## 无相关资料问题', ''])
    for split, scores in result['metrics'].items():
        neg = scores['false_positive_at_k']['5']
        lines.append(f"- {split}：{neg['count']}/{neg['denominator']}条问题在前5项出现结果；误召回率{_format(neg['rate'])}。")
    lines.extend(['', '## 逐条查询', ''])
    for row in result['queries']:
        expected = ', '.join(row['expected']) or '无相关资料'
        missing = ', '.join(row['missing_at_5']) or '无'
        lines.extend([f"### {row['id']}（{row['split']}）", '', row['query'], '',
            f"期望：{expected}；前5未召回：{missing}；耗时：{row['elapsed_ms']:.3f}毫秒。", ''])
        if not row['results']:
            lines.append('未返回结果。')
        for rank, hit in enumerate(row['results'], 1):
            lines.append(f"{rank}. `{hit['source_id']}` / `{hit['heading']}`；`{hit['path']}:{hit['start_line']}-{hit['end_line']}`；版本`{hit['version']}`；chunk `{hit['id']}`；{hit['reason']}。")
        if not row['expected'] and row['results']:
            lines.append('此问题无相关资料，上述结果全部计为误召回。')
        if row.get('note'):
            lines.append('标注说明：'+row['note'])
        lines.append('')
    lines.extend(['## 限制', '', result['limitation'], '',
        '留出查询未用于修改检索实现或反复改题；作者已审阅同一规则文档，因此这只是小样本留出，不能声称盲测或总体泛化。',
        '词法匹配不理解同义表达；相关片段也可能被共同词汇挤出前K。返回来源不保证模型正确使用，更不代表完成真实代码任务。',
        '输入清单、快照、ID映射、逐条结果与SHA-256清单均保存在同目录；结果保留漏召回，不自动重试或调整题目。', ''])
    return '\n'.join(lines)


def evaluate_retrieval(project, output, corpus_path=PACK/'corpus.json', queries_path=PACK/'queries.json'):
    """Evaluate frozen audited sections without invoking any Agent or job.

    A failed attempt is left in place for inspection; output cannot be reused.
    The imported fixture has its own database and no production confirmation.
    """
    project, output = Path(project).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('require a fresh evaluation output directory')
    if output.is_relative_to(project) or project.is_relative_to(output):
        raise ValueError('evaluation output must be outside source project')
    corpus, corpus_raw = _read(corpus_path)
    queries, queries_raw = _read(queries_path)
    head = _validate_inputs(project, corpus, queries)
    output.mkdir(parents=True, exist_ok=False)
    try:
        # Import lazily: metrics themselves do not need graph/model packages.
        from .service import DevelopmentTask
        kb = KnowledgeBase(output/'knowledge.sqlite')
        task = DevelopmentTask.create(project, output/'task', '仅评测冻结研发资料检索；不运行模型、不编辑候选。',
                                      knowledge=kb, knowledge_mode='lexical')
        if task.workspace.metadata['baseline_commit'] != head:
            raise ValueError('project version changed during evaluation preparation')
        prepared = []
        for source in corpus['sources']:
            preview = kb.preview_file(task.workspace, source['path'])
            if preview['version'] != head or preview['sha256'] != source['sha256']:
                raise ValueError('corpus source version or hash changed')
            selected = [section for section in preview['sections'] if section['heading'] == source['heading']]
            if len(selected) != 1 or hashlib.sha256(selected[0]['text'].encode()).hexdigest() != source['section_sha256']:
                raise ValueError('corpus section missing, ambiguous or section hash changed')
            document = kb.import_file(task.workspace, source['path'], [source['heading']])
            # This pack selects full leaf sections; never include unreviewed children.
            if any(chunk['heading'] != source['heading'] for chunk in document['chunks']):
                raise ValueError('corpus section includes unreviewed child headings')
            prepared.append((source, document))
        source_map = {}
        for source, document in prepared:
            kb.set_status(task.workspace.metadata['project'], document['id'], 'confirmed')
            source_map[document['id']] = source['id']
        snapshot = kb.snapshot(task.workspace.metadata['project'], head)
        # Persist the exact retrieval input before executing the first query.
        (output/'corpus.json').write_bytes(corpus_raw)
        (output/'queries.json').write_bytes(queries_raw)
        _write(output/'snapshot.json', snapshot)
        _write(output/'source-map.json', source_map)
        rows = []
        for case in queries['queries']:
            started = time.perf_counter()
            hits = search_knowledge(snapshot, case['query'], limit=5)
            elapsed = (time.perf_counter()-started)*1000
            for hit in hits:
                hit['source_id'] = source_map[hit['document_id']]
            retrieved = [hit['source_id'] for hit in hits]
            rows.append({**case, 'retrieved_source_ids': retrieved, 'results': hits,
                         'elapsed_ms': elapsed, 'missing_at_5': sorted(set(case['expected'])-set(retrieved))})
        result = {'schema': 'knowledge-retrieval-results-v1', 'game_head': head,
            'project': str(project), 'confirmation': CONFIRMATION, 'model_calls': 0, 'cost_usd': '0',
            'snapshot_sha256': digest(snapshot), 'source_map': source_map,
            'queries': rows, 'metrics': {split: retrieval_metrics(rows if split == 'all' else
                [row for row in rows if row['split'] == split]) for split in ('all', 'dev', 'holdout')},
            'limitation': '仅测固定已审章节和人工标注查询的词法召回；不测端到端修复率、模型解释正确性或研发任务质量增益。'}
        _write(output/'results.json', result)
        (output/'evaluation-report.md').write_text(_report(result), encoding='utf-8')
        files = ('corpus.json', 'queries.json', 'snapshot.json', 'source-map.json', 'results.json', 'evaluation-report.md')
        manifest = {'schema': 'knowledge-retrieval-artifacts-v1', 'game_head': head, 'confirmation': CONFIRMATION,
            'files': {name: hashlib.sha256((output/name).read_bytes()).hexdigest() for name in files},
            'retriever_sha256': hashlib.sha256(Path(__file__).with_name('knowledge.py').read_bytes()).hexdigest(),
            'evaluator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        _write(output/'manifest.json', manifest)
        return result
    except Exception as error:
        _write(output/'failure.json', {'schema': 'knowledge-retrieval-failure-v1', 'game_head': head,
            'error_type': type(error).__name__, 'message': str(error), 'model_calls': 0, 'cost_usd': '0'})
        raise
