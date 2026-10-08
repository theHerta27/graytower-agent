"""Real Docker preflight on controlled fault/reference fix, zero model calls."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agent_workbench.code_candidates import prepare_shield_case, TARGET
from agent_workbench.code_sandbox import CodeTestJobs

parser = argparse.ArgumentParser()
parser.add_argument('--data', type=Path, required=True)
args = parser.parse_args()
root = args.data.resolve()
workspace = prepare_shield_case(root / 'control', root / 'workspace')
target = workspace.path / TARGET
raw = target.read_bytes()
target.write_bytes(raw.replace(b'hp_loss=min(u.hp,amount)', b'hp_loss=min(u.hp,left)'))
candidate = workspace.freeze('D-01工程参考补丁：修复护盾抵消后仍扣生命。')
jobs = CodeTestJobs(root)
baseline = jobs.run(workspace, candidate['candidate_id'], 'baseline')
fixed = jobs.run(workspace, candidate['candidate_id'], 'candidate')
repeated = jobs.run(workspace, candidate['candidate_id'], 'candidate')
assert repeated == fixed
assert baseline['verdict']=='FAIL' and fixed['verdict']=='PASS'
result = {'mode':'engineering_reference_preflight', 'new_model_calls':0,
          'candidate':candidate,'baseline':baseline,'fixed':fixed,'repeated_receipt_same':True,
          'limitations':['Reference fix, not Coding Agent solving or independent QA Agent acceptance.',
                         'Four bounded shield tests; not all game regressions or a general untrusted-code security proof.']}
(root / 'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'candidate_id':candidate['candidate_id'],'baseline':baseline['verdict'],'fixed':fixed['verdict'],'same_receipt':repeated==fixed}))
