"""Prepare one inspectable D-01 trial; no live requests without its explicit scope hash."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
from decimal import Decimal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from agent_workbench.code_candidates import prepare_shield_case, runtime_workspace
from agent_workbench.coding.runtime_adapter import run_runtime, validate_runtime_receipt, PYTHON_INSTRUCTIONS
from agent_workbench.coding.responses_transport import CallBudget, responses_endpoint, deepseek_sender
from agent_workbench.code_sandbox import CodeTestJobs, ORACLE, RUNNER, IMAGE

RUNTIME_PYTHON=Path('D:/Desktop/mihoyo-agent-project/research/.venv-coding/Scripts/python.exe')
PROMPT='战斗里护盾抵消伤害后，角色的生命仍然减少。请阅读实际Python规则，定位并修复这个问题，保持其余战斗机制不变，说明完全吸收和伤害超过护盾时应该如何处理。只能修改effects.py，检查范围后交付，独立测试随后运行。'


def save(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')


def sources():
    paths=list((ROOT/'src/agent_workbench').rglob('*.py'))+[Path(__file__)]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def runtime_identity():
    script=('import json,hashlib,importlib.metadata; from codex_cli_bin import bundled_codex_path; '
            'print(json.dumps({"sdk":importlib.metadata.version("openai-codex"),'
            '"runtime":importlib.metadata.version("openai-codex-cli-bin"),'
            '"binary_sha256":hashlib.sha256(bundled_codex_path().read_bytes()).hexdigest()}))')
    return json.loads(subprocess.check_output([str(RUNTIME_PYTHON),'-I','-c',script],text=True,encoding='utf-8',timeout=20))


def prepare(root):
    root.mkdir(parents=True,exist_ok=False)
    workspace=prepare_shield_case(root/'data/control',root/'workspace')
    tree=workspace.artifacts.read_ref(workspace.preparation['baseline_tree'],'code-tree-v1')
    # The sealed preview includes all readable game files, never the oracle or credentials.
    preview={'prompt':PROMPT,'instructions':PYTHON_INSTRUCTIONS,
             'files':[workspace.read_file(name) for name in sorted(tree['files'])],
             'additional_material':'native tool results, candidate diff, Agent/child analysis and native Review',
             'not_sent':['test oracle and reference fix','project adapter source','credentials','unrelated repository files']}
    save(root/'outbound-preview.json',preview)
    grant={'max_calls':18,'max_input_bytes':140000,'max_output_tokens':2048,'cost_cap_usd':'0.85',
           'input_usd_per_million':'0.30','cached_input_usd_per_million':'0.006','output_usd_per_million':'1.20'}
    bound=(Decimal(142048)*Decimal('0.30')+Decimal(2048)*Decimal('1.20'))*18/Decimal(1000000)
    scope={'schema':'python-coding-demo-grant-v1','case':'D-01-controlled-fault','prompt':PROMPT,'mode':'auto',
           'endpoint':'https://api.deepseek.com/responses','model':'deepseek-flash','coding_grant':grant,
           'conservative_max_usd':str(bound),'prepared':workspace.preparation,
           'preview_sha256':hashlib.sha256((root/'outbound-preview.json').read_bytes()).hexdigest(),
           'implementation_sources':sources(), 'runtime_python':str(RUNTIME_PYTHON),'runtime_identity':runtime_identity(),
           'local_checks':{'baseline_and_candidate':4,'total_test_cases':8,'new_battles':0,'test_image':IMAGE,
                 'oracle_sha256':hashlib.sha256(ORACLE.encode()).hexdigest(),'runner_sha256':hashlib.sha256(RUNNER.encode()).hexdigest()},
           'limits':['No applying candidate','No unbounded code execution','No new QA model call',
                     'Functional trial, not collaboration comparison','Failures/unknown calls consume budget; no automatic retry']}
    save(root/'outbound-scope.json',scope)
    print(json.dumps({'prepared':str(root),'scope_sha256':hashlib.sha256((root/'outbound-scope.json').read_bytes()).hexdigest(),
                      'readable_game_files':len(tree['files']),'max_usd':str(bound)}))


def run(root,expected):
    scope_path=root/'outbound-scope.json'
    if (root/'closed.json').exists() or hashlib.sha256(scope_path.read_bytes()).hexdigest()!=expected:
        raise ValueError('scope closed or changed')
    scope=json.loads(scope_path.read_text(encoding='utf-8'))
    if scope['implementation_sources']!=sources():raise ValueError('execution code changed after scope sealing')
    if scope['runtime_identity']!=runtime_identity():raise ValueError('SDK/Runtime identity changed after sealing')
    if hashlib.sha256((root/'outbound-preview.json').read_bytes()).hexdigest()!=scope['preview_sha256']:
        raise ValueError('preview changed')
    authorization=json.loads((root/'authorization.json').read_text(encoding='utf-8'))
    if authorization.get('scope_sha256')!=expected or authorization.get('authorized') is not True:
        raise ValueError('explicit user authorization record missing')
    key=os.environ.get('DEEPSEEK_API_KEY')
    if not key:raise ValueError('local provider credential missing')
    workspace=runtime_workspace(root/'data',root/'workspace',scope['prepared'])
    if workspace.inspect_changes()['changed_files']:raise ValueError('prepared source is no longer untouched')
    grant=scope['coding_grant']|{'authorization_sha256':expected}
    budget=CallBudget(root/'coding-calls',grant)
    if budget.summary()['reserved']:raise ValueError('trial already claimed; do not reset or replay')
    # Durable claim precedes Runtime launch. A hard stop never becomes a fresh trial.
    save(root/'trial-claim.json',{'scope_sha256':expected,'case':scope['case']})
    try:
        with responses_endpoint(root/'coding-calls',grant,deepseek_sender(key)) as (endpoint,_):
            receipt=run_runtime(runtime_python=RUNTIME_PYTHON,tools_python=Path(sys.executable),
                workspace=workspace.path,data=root/'data',control=root/'runtime-control',preparation=workspace.preparation,
                endpoint=endpoint,mode=scope['mode'],prompt=scope['prompt'],timeout_seconds=240)
        validate_runtime_receipt(receipt,workspace.inspect_changes())
        ref=workspace.artifacts.put(receipt,'coding-runtime-receipt-v1')
        candidate=workspace.freeze(scope['prompt'],provenance={'source':'official Codex Runtime with DeepSeek', 'runtime_receipt':ref})
        jobs=CodeTestJobs(root/'data')
        before=jobs.run(workspace,candidate['candidate_id'],'baseline')
        after=jobs.run(workspace,candidate['candidate_id'],'candidate')
        save(root/'result.json',{'candidate':candidate,'baseline':before,'candidate_tests':after,
             'runtime_receipt':ref,'budget':budget.summary(),
             'limits':['Code QA Agent and UI integration pending; these are direct trusted container tests.',
                       'No independent task or multi-agent quality claim.']})
        print(json.dumps({'candidate_id':candidate['candidate_id'],'baseline':before['verdict'],'candidate':after['verdict']}))
    finally:
        save(root/'closed.json',{'closed':True,'budget':budget.summary(),'reason':'single trial ended; unused budget closed'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','run']);parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--authorization-sha256')
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.data.resolve())
    elif not args.authorization_sha256:parser.error('run requires explicit authorization hash')
    else:run(args.data.resolve(),args.authorization_sha256)
