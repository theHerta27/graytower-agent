"""A fresh, once-only LangGraph developer baseline, separate from legacy pilots.

Preparation and verification are offline. Execution requires the exact sealed
master scope; every child keeps its original fixed grant and its own receipts.
Private acceptance runs only after all model turns have stopped.
"""
from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import time

from .agent import INSTRUCTIONS, agent_specs
from .evaluation import PUBLIC, PRIVATE, grade_cell
from .model import ToolModel
from .sandbox import IMAGE, runner_hash
from .service import DevelopmentTask, run_lock
from .workspace import digest, encoded, editable, git
from ..coding.responses_transport import CallBudget

REPO = Path(__file__).resolve().parents[3]
RUN_ID = 'langgraph-baseline-v1'
CHECK_WAIT_SECONDS = 30
CHECK_POLL_SECONDS = .2
GRANT = {'max_input_bytes': 100000, 'max_output_tokens': 4096,
         'input_usd_per_million': '0.30', 'cached_input_usd_per_million': '0.006',
         'output_usd_per_million': '1.20', 'pricing_checked_on': '2026-10-27'}
ALLOCATIONS = {'resource-atomicity': (18, '0.65'), 'configurable-cap': (24, '0.86'),
               'shield-toughness-review': (10, '0.36')}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(encoded(value)); temporary.replace(path)


def implementation_identity():
    """Seal the current graph, transport, workspace, checks, and CLI source."""
    files = list((REPO/'src/agent_workbench/development').glob('*.py'))
    files += [REPO/'src/agent_workbench/coding/responses_transport.py',
              REPO/'src/agent_workbench/coding/runtime_adapter.py',
              REPO/'src/agent_workbench/models.py', REPO/'scripts/assess_development.py',
              REPO/'pyproject.toml', REPO/'requirements-v1.lock.txt', REPO/'requirements-coding.lock.txt']
    return digest({p.relative_to(REPO).as_posix(): p.read_text(encoding='utf-8-sig') for p in sorted(files)})


def prepare_assessment(project, root):
    """Prepare isolated ordinary tasks; no credentials, model calls, or grading."""
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=False)
    cases = _read(PUBLIC)
    if [case['id'] for case in cases] != list(ALLOCATIONS):
        raise ValueError('public developer baseline cases changed')
    cells = []; previews = []
    for case in cases:
        count, cap = ALLOCATIONS[case['id']]
        grant = {**GRANT, 'max_calls': count, 'cost_cap_usd': cap}
        cell_id = case['id']+'-standard-off'
        task = DevelopmentTask.create(project, root/'tasks'/cell_id, case['request'],
                                      tool_profile='standard', knowledge_mode='off')
        child = task.prepare(RUN_ID, grant)
        cell = {'cell_id': cell_id, 'task_id': case['id'], 'profile': 'standard',
                'knowledge_mode': 'off', 'run_id': RUN_ID, 'grant': grant,
                'baseline_commit': child['baseline_commit'], 'scope_sha256': child['scope_sha256'],
                'request_file_hash': digest(_read(task.root/'request.json')),
                'project_hash': digest(_read(task.root/'project.json')),
                'baseline_tree_hash': digest(task.workspace.baseline)}
        cells.append(cell)
        previews.append({'cell_id': cell_id, **_read(task._batch(RUN_ID)/'outbound-preview.json')})
    maximum = sum(cell['grant']['max_calls'] for cell in cells)
    authorization = {'endpoint': ToolModel.endpoint, 'model': 'deepseek-flash',
                     'thinking': {'type': 'disabled'}, 'knowledge_mode': 'off',
                     'max_calls': maximum, 'cost_cap_usd': '1.90',
                     'allocations': [{'task_id': c['task_id'], 'grant': c['grant']} for c in cells],
                     'actions': '三题各执行一次；固定18/24/10次，共52次。停止后关闭未用额度，不重跑、不调配、不采用原游戏。',
                     'data': '公开需求、封存游戏材料、指令和工具定义、检查反馈、候选Diff与Agent说明；独立grader仅在模型结束后本地运行。'}
    preview = {'schema': 'development-langgraph-assessment-preview-v1',
               'authorization': authorization, 'cells': previews}
    per_call = (Decimal(GRANT['max_input_bytes']+2048)*Decimal(GRANT['input_usd_per_million'])
                + Decimal(GRANT['max_output_tokens'])*Decimal(GRANT['output_usd_per_million']))/1_000_000
    scope = {'schema': 'development-langgraph-assessment-v1', 'engine': 'langgraph',
             **authorization, 'cells': cells, 'created_at_ns': time.time_ns(),
             'conservative_max_usd': str(per_call*maximum), 'preview_hash': digest(preview),
             'implementation_hash': implementation_identity(), 'public_tasks_hash': digest(cases),
             'private_grader_hash': digest(PRIVATE.read_text(encoding='utf-8')),
             'image': IMAGE, 'runner_hash': runner_hash(),
             'instructions_hash': digest(INSTRUCTIONS), 'tools_hash': digest(agent_specs('standard')),
             'limitation': '复用三道公开开发题；不是独立留出集，不据此声称通用成功率或框架质量提升。'}
    scope['scope_sha256'] = digest(scope)
    _save(root/'outbound-preview.json', preview); _save(root/'outbound-scope.json', scope)
    return scope


def _scope_only(root, scope_hash):
    scope = _read(root/'outbound-scope.json'); body = dict(scope); body.pop('scope_sha256', None)
    if (scope.get('scope_sha256') != scope_hash or digest(body) != scope_hash
            or scope.get('schema') != 'development-langgraph-assessment-v1'
            or digest(_read(root/'outbound-preview.json')) != scope['preview_hash']
            or implementation_identity() != scope['implementation_hash']
            or digest(_read(PUBLIC)) != scope['public_tasks_hash']
            or digest(PRIVATE.read_text(encoding='utf-8')) != scope['private_grader_hash']
            or IMAGE != scope['image'] or runner_hash() != scope['runner_hash']
            or digest(INSTRUCTIONS) != scope['instructions_hash']
            or digest(agent_specs('standard')) != scope['tools_hash']):
        raise ValueError('assessment authorization, materials, implementation, or grading changed')
    return scope


def _child(root, cell):
    task = DevelopmentTask(root/'tasks'/cell['cell_id'])
    child = _read(task._batch(cell['run_id'])/'outbound-scope.json')
    body = dict(child); body.pop('scope_sha256', None)
    if (child.get('schema') != 'development-langgraph-v1'
            or child.get('scope_sha256') != cell['scope_sha256'] or digest(body) != cell['scope_sha256']
            or child.get('grant') != cell['grant'] or child.get('endpoint') != ToolModel.endpoint
            or child.get('model') != 'deepseek-flash'
            or child['request_hash'] != digest(task.request) or task.tool_profile != 'standard'
            or getattr(task, 'knowledge_mode', 'off') != 'off'
            or digest(_read(task.root/'request.json')) != cell['request_file_hash']
            or digest(_read(task.root/'project.json')) != cell['project_hash']
            or digest(task.workspace.baseline) != cell['baseline_tree_hash']
            or child['preview_hash'] != digest(_read(task._batch(cell['run_id'])/'outbound-preview.json'))):
        raise ValueError('assessment child request, scope, baseline, or preview changed')
    return task, child


def verify_assessment(root, scope_hash):
    """Reject stale authorization before claiming any child or constructing a model."""
    root = Path(root).resolve(); scope = _scope_only(root, scope_hash)
    if (root/'claimed').exists() or (root/'batch-close.json').exists():
        raise ValueError('assessment already started or closed; inspect saved receipts, never rerun')
    for cell in scope['cells']:
        task, child = _child(root, cell)
        if (child['candidate_tree_hash'] != task.workspace.inspect()['tree_hash']
                or (task._batch(cell['run_id'])/'claimed').exists()):
            raise ValueError('assessment child already started or candidate changed')
        preview = _read(task._batch(cell['run_id'])/'outbound-preview.json')
        if preview.get('memories', []) != task.memory.retrieve(
                task.workspace.metadata['project'], task.request, task.workspace.metadata['baseline_commit']):
            raise ValueError('assessment project memory changed after preparation')
        source = Path(task.workspace.metadata['project'])
        if (git(source, 'rev-parse', 'HEAD').decode().strip() != cell['baseline_commit']
                or git(source, 'status', '--porcelain', '--untracked-files=no').strip()):
            raise ValueError('source Git baseline changed after preparation')
        # The prepared gateway is validation only. The live graph has its own
        # model ledger; neither may hide calls before master authorization.
        for name in ('gateway', 'model'):
            database = task._batch(cell['run_id'])/name/'responses-ledger.sqlite'
            if database.exists():
                with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
                    grant = json.loads(db.execute('SELECT body FROM grant_info WHERE id=1').fetchone()[0])
                    count = db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]
                if grant != cell['grant'] or count:
                    raise ValueError('assessment child allowance changed or already consumed')
    return scope


def _poll_checks(task, result):
    pending = result.get('agent', {}).get('pending', []) or result.get('agent', {}).get('jobs', [])
    if not pending:
        return False
    deadline = time.monotonic()+CHECK_WAIT_SECONDS
    while True:
        values = [task.jobs.read(item['job_id'], task.workspace) for item in pending]
        if all(value['status']=='completed' for value in values):
            return True
        if any(value['status'] not in ('running', 'completed') for value in values):
            return False  # Includes unknown and not_started: never relaunch.
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(CHECK_POLL_SECONDS, max(0, deadline-time.monotonic())))


def _accounting(task, cell, result):
    database = task._batch(cell['run_id'])/'model/responses-ledger.sqlite'
    usage = {'input_tokens': 0, 'output_tokens': 0, 'cached_input_tokens': 0,
             'usage_records': 0, 'missing_usage_records': 0, 'ledger_available': database.exists()}
    if database.exists():
        budget = CallBudget(database.parent, cell['grant']).summary()
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT usage FROM calls ORDER BY id').fetchall()
        for (raw,) in rows:
            if raw is None:
                usage['missing_usage_records'] += 1; continue
            value = json.loads(raw)
            usage['input_tokens'] += value['input_tokens']
            usage['output_tokens'] += value['output_tokens']
            usage['cached_input_tokens'] += value.get('input_tokens_details', {}).get('cached_tokens', 0)
            usage['usage_records'] += 1
    else:
        budget = {'reserved': 0, 'completed': 0, 'failed': 0, 'unknown': 0, 'known_cost_usd': '0',
                  'unknown_cost_reserved_usd': '0', 'max_calls': cell['grant']['max_calls'],
                  'cost_cap_usd': cell['grant']['cost_cap_usd'], **result.get('budget', {})}
    if not 0 <= budget['reserved'] <= cell['grant']['max_calls']:
        raise ValueError('child model ledger exceeds its fixed allowance')
    return budget, usage


def _unavailable_accounting(cell, result):
    """Keep the durable run summary if token details cannot be read afterward."""
    budget = dict(result.get('budget', {}))
    if not budget or type(budget.get('reserved')) is not int or not 0 <= budget['reserved'] <= cell['grant']['max_calls']:
        count = cell['grant']['max_calls']
        maximum = (Decimal(GRANT['max_input_bytes']+2048)*Decimal(GRANT['input_usd_per_million'])
                   + Decimal(GRANT['max_output_tokens'])*Decimal(GRANT['output_usd_per_million']))/1_000_000
        budget = {'reserved': count, 'completed': 0, 'failed': 0, 'unknown': count,
                  'known_cost_usd': '0', 'unknown_cost_reserved_usd': str(maximum*count),
                  'max_calls': count, 'cost_cap_usd': cell['grant']['cost_cap_usd'],
                  'counts_are_conservative_upper_bounds': True}
    usage = {'input_tokens': 0, 'output_tokens': 0, 'cached_input_tokens': 0,
             'usage_records': 0, 'missing_usage_records': budget['reserved'], 'ledger_available': False}
    return budget, usage


def _run_cell(root, cell, api_key, model_factory):
    task, _ = _child(root, cell); folder = task._batch(cell['run_id'])
    started = time.monotonic(); model = None
    result = {'state': 'not_started', 'closed': False}
    try:
        model = model_factory(task, cell) if model_factory else ToolModel(
            folder/'model', cell['grant'], agent_specs('standard'), api_key=api_key)
        result = task.execute(cell['run_id'], cell['scope_sha256'], model=model)
        while result.get('state') == 'waiting_checks' and _poll_checks(task, result):
            result = task.execute(cell['run_id'], cell['scope_sha256'], model=model, resume=True)
    except Exception as exc:
        saved = folder/'run-result.json'
        result = _read(saved) if saved.exists() else {
            **result, 'state': 'unknown' if (folder/'claimed').exists() else 'not_started'}
        result = {**result, 'error_type': type(exc).__name__}
    finally:
        if model is not None and hasattr(model, 'close'):
            try:
                model.close()
            except Exception as exc:
                result = {**result, 'close_error_type': type(exc).__name__}
    # Keep the original failed/paused receipt, then explicitly close the child
    # to prevent an ordinary resume from spending this batch's unused calls.
    _save(folder/'execution-result.json', result)
    accounting_error = None
    try:
        budget, usage = _accounting(task, cell, result)
    except Exception as exc:
        budget, usage = _unavailable_accounting(cell, result)
        accounting_error = type(exc).__name__
    closed = {'closed': True, 'scope_sha256': cell['scope_sha256'], 'state': result.get('state', 'unknown'),
              'unused_calls_closed': cell['grant']['max_calls']-budget['reserved'],
              'budget': budget, 'reason': 'fixed once-only assessment; no automatic rerun or reallocation'}
    _save(folder/'batch-close.json', closed)
    (folder/'claimed').mkdir(exist_ok=True)
    _save(folder/'run-result.json', {**result, 'closed': True, 'assessment_closed': True})
    record = {**cell, 'run_state': result.get('state', 'unknown'),
              'elapsed_seconds': round(time.monotonic()-started, 3), 'result': result,
              'budget': budget, 'usage': usage, 'unused_calls_closed': closed['unused_calls_closed'],
              'handoff_completed': result.get('state') == 'completed'}
    if accounting_error:
        record['accounting_error_type'] = accounting_error
    try:
        tree = task.workspace.snapshot(); identity = digest(tree)
        _save(task.root/'final-candidate.json', tree)
        record.update(final_tree_hash=identity, changed_files=sorted(
            n for n in set(tree['files'])|set(task.workspace.baseline['files'])
            if tree['files'].get(n) != task.workspace.baseline['files'].get(n)))
        task.export()
    except Exception as exc:
        record.update(final_tree_hash=None, snapshot_error_type=type(exc).__name__)
    record['record_sha256'] = digest(record)
    _save(root/'model-results'/f"{cell['cell_id']}.json", record)
    return record


def run_assessment(root, scope_hash, api_key, model_factory=None):
    """Consume one exact master authorization. A claimed root is never resumed."""
    root = Path(root).resolve(); scope = verify_assessment(root, scope_hash)
    if model_factory is None and (not isinstance(api_key, str) or not api_key.strip()):
        raise ValueError('an explicit execution credential is required')
    try:
        (root/'claimed').mkdir()
    except FileExistsError:
        raise ValueError('assessment already claimed; never repeat paid trials') from None
    _save(root/'claimed/authorization.json', {'scope_sha256': scope_hash, 'started_at_ns': time.time_ns()})
    records = []
    for cell in scope['cells']:
        _scope_only(root, scope_hash)
        records.append(_run_cell(root, cell, api_key, model_factory))
        _save(root/'model-results.json', records)
    _save(root/'batch-close.json', {'scope_sha256': scope_hash, 'closed': True,
          'unused_calls_closed': sum(r['unused_calls_closed'] for r in records),
          'reserved_calls': sum(r['budget']['reserved'] for r in records),
          'max_calls': scope['max_calls'], 'reason': 'three fixed attempts finished or stopped; all remaining allowance closed'})
    return grade_assessment(root)


def grade_assessment(root):
    """Grade frozen candidates once; unavailable/unknown grading stays inconclusive."""
    root = Path(root).resolve()
    with run_lock(root):
        return _grade_assessment(root)


def _grade_assessment(root):
    root = Path(root).resolve(); scope = _read(root/'outbound-scope.json')
    _scope_only(root, scope['scope_sha256'])
    if not (root/'batch-close.json').exists():
        raise ValueError('close the model batch before independent grading; active or interrupted batch is not retried')
    closure = _read(root/'batch-close.json')
    if not closure.get('closed') or closure.get('scope_sha256') != scope['scope_sha256']:
        raise ValueError('batch closure does not match the frozen assessment')
    records = []
    for cell in scope['cells']:
        path = root/'model-results'/f"{cell['cell_id']}.json"
        if not path.exists():
            continue  # A process interruption does not fabricate missing attempts.
        record = _read(path); body = dict(record); body.pop('record_sha256', None)
        if digest(body) != record.get('record_sha256'):
            raise ValueError('assessment result record changed')
        task, _ = _child(root, cell); tree = None
        if record['final_tree_hash'] is not None:
            tree = _read(task.root/'final-candidate.json')
            if digest(tree) != record['final_tree_hash']:
                raise ValueError('frozen final candidate changed after model execution')
            original = task.workspace.baseline['files']; final = tree['files']
            if any(not editable(n) and original.get(n) != final.get(n) for n in set(original)|set(final)):
                raise ValueError('frozen candidate changed trusted read-only material')
            native_hash = record.get('result', {}).get('agent', {}).get('tree_hash')
            if record['handoff_completed'] and native_hash is not None and native_hash != record['final_tree_hash']:
                raise ValueError('frozen candidate differs from completed graph evidence')
        records.append((record, task, tree))
    results = []
    for record, task, tree in records:
        folder = root/'grading'/record['cell_id']; verdict_path = folder/'grade-result.json'
        identity = {'tree_hash': record['final_tree_hash'], 'private_grader_hash': scope['private_grader_hash'],
                    'image': scope['image'], 'runner_hash': scope['runner_hash'], 'cell_id': record['cell_id']}
        if verdict_path.exists():
            saved = _read(verdict_path)
            if saved['identity'] != identity:
                raise ValueError('saved grading belongs to another candidate')
            grade = saved['grade']
        else:
            attempt = folder/'grade-attempt.json'
            grade = {'verdict': 'INCONCLUSIVE', 'note': 'candidate or original grading attempt unavailable; not automatically repeated'}
            if tree is not None and not attempt.exists():
                _save(attempt, identity)
                try:
                    grade = grade_cell(task, record, folder, tree=tree)
                except Exception as exc:
                    grade = {**grade, 'error_type': type(exc).__name__}
            _save(verdict_path, {'identity': identity, 'grade': grade})
        results.append({**record, 'grade': grade,
                        'candidate_pass_and_handoff_completed': record['handoff_completed'] and grade.get('verdict') == 'PASS',
                        'semantic_review':'pending', 'task_success':None})
    summary = {'schema': 'development-langgraph-assessment-results-v1', 'scope_sha256': scope['scope_sha256'],
               'results': results, 'attempted_cells': len(results), 'planned_cells': len(scope['cells']),
               'reserved_calls': sum(r['budget']['reserved'] for r in results),
               'failed_calls': sum(r['budget'].get('failed', 0) for r in results),
               'unknown_requests': sum(r['budget'].get('unknown', 0) for r in results),
               'known_cost_usd': str(sum((Decimal(r['budget']['known_cost_usd']) for r in results), Decimal(0))),
               'unknown_cost_reserved_usd': str(sum((Decimal(r['budget'].get('unknown_cost_reserved_usd', '0')) for r in results), Decimal(0))),
               'unused_calls_closed': sum(r['unused_calls_closed'] for r in results),
               'usage': {name: sum(r['usage'][name] for r in results) for name in
                         ('input_tokens', 'output_tokens', 'cached_input_tokens', 'usage_records', 'missing_usage_records')},
               'limitation': scope['limitation'],
               'human_semantic_review': '模型最终解释与引用尚需人工复核；候选验收与完整任务交付分别记录。'}
    _save(root/'results.json', summary)
    return summary
