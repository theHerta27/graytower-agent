"""Real pinned SDK/Runtime + local scripted provider + real controlled Docker.

This proves tool feedback reaches the same native Agent thread. The decisions
are scripted; it is deliberately NOT evidence of LLM problem-solving quality.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from agent_workbench.development.workspace import ProjectWorkspace
from agent_workbench.development.runtime import run_runtime
from agent_workbench.development.checks import CheckJobs
from agent_workbench.coding.responses_transport import responses_endpoint


def output_text(value):
    if isinstance(value,str):return value
    return ''.join(part.get('text','') for part in value)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--runtime-python',type=Path,required=True)
    args=parser.parse_args()
    root=args.data.resolve();root.mkdir(parents=True,exist_ok=False)
    source=root/'source';source.mkdir()
    def git(*values):
        subprocess.run(['git','-c','safe.directory='+source.as_posix(),'-C',str(source),*values],check=True,capture_output=True)
    git('init','-q');git('config','user.email','protocol-fixture@example.invalid');git('config','user.name','Protocol Fixture')
    target='game-core/combat_core/v2/effects.py'
    for name,text in {target:'VALUE = 1\n',
        'game-core/tests/v2/test_value.py':'from combat_core.v2.effects import VALUE\ndef test_expected_value():\n    assert VALUE == 3\n'}.items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(text.encode())
    git('add','.');git('commit','-qm','protocol fixture only')
    workspace=ProjectWorkspace.create(source,root/'task')
    sequence=[];requests=[]
    def send(body):
        step=len(sequence)
        outputs={item['call_id']:json.loads(output_text(item['output'])) for item in body['input'] if item.get('type')=='function_call_output'}
        specs={t['name']:t for t in body['tools']}
        assert 'spawn_agent' not in specs and 'exec_command' not in specs,specs
        if step==0:name,params='project_status',{}
        elif step==1:name,params='read_file',{'path':target}
        elif step==2:name,params='write_file',{'path':target,'expected_sha256':outputs['c1']['sha256'],'content':'VALUE = 2\n'}
        elif step in (3,7):name,params='start_check',{'check_set':'rules'}
        elif step in (4,8):
            job=outputs['c'+str(step-1)]['job_id']
            jobs=CheckJobs(workspace.control/'checks')
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                saved=jobs.read(job)
                if saved['status']=='completed':break
                time.sleep(.2)
            assert saved['status']=='completed',saved
            name,params='read_check',{'job_id':job}
        elif step==5:
            assert outputs['c4']['result']['verdict']=='FAIL',outputs['c4']
            name,params='read_file',{'path':target}
        elif step==6:name,params='write_file',{'path':target,'expected_sha256':outputs['c5']['sha256'],'content':'VALUE = 3\n'}
        elif step==9:
            assert outputs['c8']['result']['verdict']=='PASS',outputs['c8']
            assert outputs['c8']['matches_current_candidate']
            name,params=None,None
        else:raise ValueError('unexpected extra Runtime call')
        if name:
            assert name in specs
            item={'type':'function_call','name':name,'arguments':json.dumps(params),'call_id':'c'+str(step),'id':'fc'+str(step)}
        else:item={'type':'message','role':'assistant','id':'m-final','content':[{'type':'output_text','text':'本地协议夹具完成：收到真实FAIL，修订后收到真实PASS。不是模型质量评测。'}]}
        sequence.append(name or 'final');requests.append(body)
        rid='fixture-'+str(step)
        events=[{'type':'response.created','response':{'id':rid}},
                {'type':'response.output_item.added','output_index':0,'item':item},
                {'type':'response.output_item.done','output_index':0,'item':item},
                {'type':'response.completed','response':{'id':rid,'output':[item],
                    'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}}}]
        return ''.join('data: '+json.dumps(e,ensure_ascii=False)+'\n\n' for e in events).encode()
    grant={'max_calls':12,'max_input_bytes':150000,'max_output_tokens':512,'cost_cap_usd':'0',
        'input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0','fixture_only':True}
    with responses_endpoint(root/'protocol-gateway',grant,send) as (endpoint,budget):
        receipt=run_runtime(runtime_python=args.runtime_python,tools_python=Path(sys.executable),
            workspace_control=workspace.control,control=root/'runtime',endpoint=endpoint,
            prompt='协议夹具：将VALUE修为3，读取可信检查失败后修订。',timeout_seconds=160)
        summary={'sequence':sequence,'budget':budget.summary(),'runtime':receipt['runtime'],
            'status':receipt['status'],'thread_id':receipt['thread_id'],'new_provider_calls':0,
            'checks':receipt['checks'],'source_unchanged':not subprocess.check_output(['git','-C',str(source),'status','--porcelain']).strip(),
            'limitation':'Scripted decisions and minimal rules; not real model quality or real game acceptance.'}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    assert len(sequence)==10 and receipt['status']=='completed'
    assert len(receipt['thread']['thread']['turns'])==1,'unexpected Review or extra turn'
    assert [j['result']['verdict'] for j in receipt['checks']]==['FAIL','PASS']
    assert summary['source_unchanged']
    print(json.dumps({k:v for k,v in summary.items() if k!='checks'},ensure_ascii=False))


if __name__=='__main__':main()
