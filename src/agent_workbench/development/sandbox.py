"""Frozen game inputs in the existing controlled-project Docker boundary."""
import base64
import hashlib
from io import BytesIO
import json
import subprocess
import tarfile
import uuid
from ..code_sandbox import IMAGE, command
from .workspace import clean_name, readable, digest

CHECK_SETS = {
    'rules': ['game-core/tests/v2'],
    'effects': ['game-core/tests/v2/test_effects.py', 'game-core/tests/v2/test_boundaries.py'],
    'scheduler': ['game-core/tests/v2/test_scheduler.py'],
    'session': ['game-core/tests/v2/test_session.py'],
    'resource_inputs': ['/runner/test_resource_inputs.py'],
}
RESOURCE_ORACLE='''from pathlib import Path
import pytest
from combat_core.v2.config import load_bundle,load_scenario
from combat_core.v2.state import initial_state
from combat_core.v2.effects import skill_points
from combat_core.v2.trace import EventRecorder

def setup():
    root=Path('/project/configs/combat/v2')
    return initial_state(load_bundle(root/'baseline.json'),load_scenario(root/'scenario.json')),EventRecorder()

@pytest.mark.parametrize('gained,spent',[(-1,0),(0,-1)])
def test_negative_resource_inputs_rejected_without_side_effect(gained,spent):
    state,rec=setup();state.skill_points=3;before=state.skill_points
    with pytest.raises(ValueError):skill_points(state,gained,spent,rec,'striker_01','input-check')
    assert state.skill_points == before
    assert rec.events == []

@pytest.mark.parametrize('before,gained,spent,after,overflow',[(3,1,0,4,0),(5,1,0,5,1),(3,0,1,2,0),(5,1,1,5,0)])
def test_legal_resource_behavior_and_original_interface(before,gained,spent,after,overflow):
    state,rec=setup();state.skill_points=before
    skill_points(state,gained,spent,rec,'striker_01','input-check')
    assert state.skill_points==after
    event=rec.events[-1]
    assert event.kind=='resource_changed'
    assert (event.payload.before,event.payload.after,event.payload.overflow)==(before,after,overflow)
'''
AUDIT = '''import hashlib,json,sys
def save():
    found={}
    for name,module in list(sys.modules.items()):
        path=getattr(module,'__file__',None)
        if name.startswith('combat_core') and isinstance(path,str):
            try: found[name]={'path':path,'sha256':hashlib.sha256(open(path,'rb').read()).hexdigest()}
            except OSError: pass
    with open('/tmp/imports.json','w') as f:json.dump(found,f)
def pytest_sessionfinish(session,exitstatus):save()
'''
DIAGNOSTIC = '''import runpy
from candidate_audit import save
try:runpy.run_path('/runner/diagnostic.py',run_name='__main__')
finally:save()
'''
RUNNER = '''import json,os,subprocess,sys,xml.etree.ElementTree as ET
plan=json.load(open('/runner/plan.json'))
env={'PATH':os.environ['PATH'],'PYTHONPATH':'/project/game-core:/runner','PYTHONDONTWRITEBYTECODE':'1','HOME':'/tmp','GRAYTOWER_PROJECT_ROOT':'/project'}
if plan['kind']=='diagnostic':args=[sys.executable,'-B','/runner/run_diagnostic.py']
else:args=[sys.executable,'-B','-m','pytest','-q','-c','/dev/null','--rootdir=/project','--import-mode=importlib','-p','no:cacheprovider','-p','candidate_audit',*plan['targets'],'--junitxml=/tmp/result.xml']
with open('/tmp/output.txt','wb') as log:
    try:
        run=subprocess.run(args,cwd='/project',env=env,stdout=log,stderr=log,timeout=100)
        result={'exit_code':run.returncode}
    except subprocess.TimeoutExpired:result={'exit_code':124,'execution_error':'check timeout'}
result['log']=open('/tmp/output.txt','rb').read(24000).decode('utf-8',errors='replace')
if plan['kind']!='diagnostic':
    try:
        suites=ET.parse('/tmp/result.xml').getroot()
        result['tests']=[{'name':n.attrib.get('name'),'classname':n.attrib.get('classname'),'status':'FAIL' if n.find('failure') is not None else 'ERROR' if n.find('error') is not None else 'SKIP' if n.find('skipped') is not None else 'PASS'} for n in suites.iter('testcase')]
    except Exception as e:result['xml_error']=type(e).__name__
try:result['imports']=json.load(open('/tmp/imports.json'))
except OSError:result['imports']={}
print(json.dumps(result))
'''


def runner_hash():
    return digest({'runner':RUNNER,'audit':AUDIT,'diagnostic':DIAGNOSTIC,
                   'resource_oracle':RESOURCE_ORACLE,'check_sets':CHECK_SETS})


def validate_definition(payload):
    identity=payload['identity'];kind=identity['check_set']
    if (kind not in (*CHECK_SETS,'diagnostic') or identity.get('image')!=IMAGE
        or identity.get('runner_hash')!=runner_hash() or identity.get('targets')!=CHECK_SETS.get(kind,[])
        or identity.get('tree_hash')!=digest(payload['tree'])):
        raise ValueError('frozen check definition changed; admit a new check instead of executing different materials')


class CheckNotStarted(RuntimeError):
    """Preflight proved candidate execution has not started; safe to retry later."""


def archive(payload):
    validate_definition(payload)
    kind = payload['identity']['check_set']
    plan = {'kind': kind, 'targets': CHECK_SETS.get(kind, [])}
    files = {'runner/check.py': RUNNER.encode(), 'runner/plan.json': json.dumps(plan).encode(),
             'runner/candidate_audit.py': AUDIT.encode(), 'runner/run_diagnostic.py': DIAGNOSTIC.encode()}
    if kind=='resource_inputs':files['runner/test_resource_inputs.py']=RESOURCE_ORACLE.encode()
    if kind == 'diagnostic':
        files['runner/diagnostic.py'] = payload['diagnostic'].encode('utf-8')
    for name, value in payload['tree']['files'].items():
        clean_name(name)
        if not readable(name):
            raise ValueError('file outside execution catalog')
        raw = base64.b64decode(value['content'], validate=True)
        if hashlib.sha256(raw).hexdigest() != value['sha256']:
            raise ValueError('frozen input hash mismatch')
        files['project/'+name] = raw
    data = BytesIO()
    with tarfile.open(fileobj=data, mode='w') as tar:
        for name, raw in files.items():
            info = tarfile.TarInfo(name); info.size = len(raw); info.mode = 0o444
            tar.addfile(info, BytesIO(raw))
    return data.getvalue()


def execute(payload, resource_record):
    validate_definition(payload)
    try:
        if command('image','inspect','--format','{{.Id}}',IMAGE,timeout=15).decode().strip()!=IMAGE:
            raise RuntimeError('image identity mismatch')
    except (RuntimeError,OSError,subprocess.TimeoutExpired) as exc:
        raise CheckNotStarted('Docker或固定测试镜像不可用，尚未启动候选执行；检查引擎和镜像后可再次开始检查。'+type(exc).__name__) from exc
    seed = image = container = None
    result = None
    try:
        seed = command('create', '--network', 'none', IMAGE).decode().strip()
        resource_record({'seed': seed})
        command('cp', '-', seed+':/', input=archive(payload))
        image = command('commit', seed).decode().strip()
        resource_record({'seed': seed, 'image': image})
        command('rm', '-f', seed, timeout=15); seed = None
        container = command('create', '--name', 'graytower-development-'+uuid.uuid4().hex,
            '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--pids-limit', '64', '--memory', '384m', '--cpus', '1', '--user', '10001:10001',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=48m', '--workdir', '/project', image,
            'python', '-I', '-B', '/runner/check.py').decode().strip()
        resource_record({'container': container, 'image': image})
        raw = command('start', '-a', container, timeout=120)
        if len(raw) > 100_000:
            raise ValueError('execution output exceeds limit')
        result = json.loads(raw)
        result.update(image=IMAGE, execution_image=image, container_id=container,
            runner_hash=runner_hash(), execution='real controlled-project Docker job')
    finally:
        errors = []
        for resource, args in [(seed, ('rm','-f',seed)), (container, ('rm','-f',container)), (image, ('image','rm',image))]:
            if resource:
                try: command(*args, timeout=20)
                except Exception as e: errors.append(type(e).__name__)
        if errors:
            raise RuntimeError('cleanup incomplete: '+','.join(errors))
        resource_record({'cleaned': True})
        if result is not None:
            result['resources_removed'] = True
    return result
