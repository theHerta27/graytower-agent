"""Single-host Docker test receipts. No host mounts, credentials or networking."""
from contextlib import closing
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile
import uuid

from .code_candidates import PROFILE, snapshot
from .jobs import canonical, digest, RecoveryRequired

DOCKER = Path('C:/Users/Administrator/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe')
IMAGE = 'sha256:224fc522b610454feb8de92e4745a984ff28acde851c68d0a75d7256b05434a9'
ORACLE = '''import json
from pathlib import Path
import pytest
from combat_core.v2.config import load_bundle, load_scenario
from combat_core.v2.state import initial_state, ShieldInstance
from combat_core.v2.trace import EventRecorder
from combat_core.v2.effects import damage

@pytest.mark.parametrize("shield,hit,hp,remaining", [(100,40,100,60),(20,40,80,0),(0,40,60,0),(20,200,0,0)])
def test_shield_hp_and_events(shield,hit,hp,remaining):
    root=Path('/candidate')
    bundle=load_bundle(root/'configs/combat/v2/baseline.json')
    state=initial_state(bundle,load_scenario(root/'configs/combat/v2/scenario.json'))
    unit=state.units['striker_01']; unit.hp=100; unit.shields=[]
    if shield:
        unit.shields.append(ShieldInstance(source_id='support_01',skill_id='support_ultimate',value=shield,remaining=2,created_seq=1))
    rec=EventRecorder()
    damage(bundle,state,bundle.boss_id,'striker_01',hit,'direct_damage',dict(critical=False,skill_id='boss_strike',damage_type='physical'),rec)
    event=next(e for e in rec.events if e.kind=='direct_damage')
    record={'shield':shield,'hit':hit,'hp':unit.hp,'remaining_shield':sum(s.value for s in unit.shields),'event':event.model_dump(mode='json')}
    with open('/tmp/game-events.jsonl','a') as out: out.write(json.dumps(record)+'\\n')
    assert unit.hp==hp
    assert sum(s.value for s in unit.shields)==remaining
    assert event.payload.hp_loss==100-hp
    assert event.payload.absorbed==min(shield,hit)
    assert event.payload.overkill==max(0,hit-shield-100)
    assert unit.dead==(hp==0)
'''
RUNNER = '''import json, os, subprocess, sys, xml.etree.ElementTree as ET
env={'PATH':os.environ['PATH'],'PYTHONPATH':'/candidate/game-core','PYTHONDONTWRITEBYTECODE':'1','HOME':'/tmp'}
with open('/tmp/test-output.txt','wb') as log:
    run=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','/oracle/test_shield.py','--junitxml=/tmp/result.xml'],cwd='/tmp',env=env,stdout=log,stderr=log,timeout=45)
result={'exit_code':run.returncode,'log':open('/tmp/test-output.txt').read(16000)}
try:
    suites=ET.parse('/tmp/result.xml').getroot()
    result['tests']=[{'name':n.attrib.get('name'),'status':'FAIL' if n.find('failure') is not None else 'ERROR' if n.find('error') is not None else 'SKIP' if n.find('skipped') is not None else 'PASS'} for n in suites.iter('testcase')]
except Exception as error: result['xml_error']=type(error).__name__
try: result['game_events']=[json.loads(s) for s in open('/tmp/game-events.jsonl').read(32000).splitlines()]
except Exception as error: result['event_error']=type(error).__name__
print(json.dumps(result))
'''

SP_ORACLE = '''import json
from pathlib import Path
import pytest
from combat_core.v2.config import load_bundle,load_scenario
from combat_core.v2.state import initial_state
from combat_core.v2.trace import EventRecorder
from combat_core.v2.effects import skill_points

@pytest.mark.parametrize("before,gained,spent,after,overflow",[(3,1,0,4,0),(5,1,0,5,1),(3,0,1,2,0),(5,1,1,5,0)])
def test_skill_points_and_events(before,gained,spent,after,overflow):
    root=Path('/candidate')
    bundle=load_bundle(root/'configs/combat/v2/baseline.json')
    state=initial_state(bundle,load_scenario(root/'configs/combat/v2/scenario.json'))
    state.skill_points=before
    rec=EventRecorder()
    skill_points(state,gained,spent,rec,'striker_01','qa_resource')
    event=next(e for e in rec.events if e.kind=='resource_changed')
    record={'before':before,'gained':gained,'spent':spent,'after':state.skill_points,'event':event.model_dump(mode='json')}
    with open('/tmp/game-events.jsonl','a') as out:out.write(json.dumps(record)+'\\n')
    assert state.skill_points==after
    assert event.payload.before==before
    assert event.payload.after==after
    assert event.payload.gained==gained
    assert event.payload.spent==spent
    assert event.payload.overflow==overflow
'''


def oracle_for(profile):
    if profile == PROFILE:
        return ORACLE
    if profile == 'skill-points-python-v1':
        return SP_ORACLE
    raise ValueError('unsupported isolated test profile')


def payload_archive(tree, profile=PROFILE):
    data = BytesIO()
    with tarfile.open(fileobj=data, mode='w') as tar:
        import base64
        files = { 'oracle/test_shield.py': oracle_for(profile).encode(), 'oracle/runner.py': RUNNER.encode() }
        for name, item in tree['files'].items():
            if '\\' in name or '..' in Path(name).parts or name.startswith('/') or ':' in name:
                raise ValueError('invalid container source path')
            raw = base64.b64decode(item['content'], validate=True)
            if hashlib.sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('container source hash mismatch')
            files['candidate/'+name] = raw
        for name, raw in files.items():
            info = tarfile.TarInfo(name); info.size = len(raw); info.mode = 0o444
            tar.addfile(info, BytesIO(raw))
    return data.getvalue()


def command(*args, input=None, timeout=90, docker=None):
    env = {k:v for k,v in os.environ.items() if k.upper() in
           {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','USERPROFILE','LOCALAPPDATA'}}
    p = subprocess.run([str(docker or DOCKER), *args], input=input, capture_output=True, timeout=timeout, env=env)
    if p.returncode:
        raise RuntimeError('Docker operation failed: '+p.stderr.decode(errors='replace')[-1000:])
    return p.stdout


def execute_tree(tree, profile=PROFILE):
    actual = command('image', 'inspect', '--format', '{{.Id}}', IMAGE).decode().strip()
    if actual != IMAGE:
        raise ValueError('sandbox image identity mismatch')
    name = 'graytower-test-'+uuid.uuid4().hex
    # Materialize files in a NEVER STARTED container, then seal its filesystem.
    # Docker cannot cp into a read-only rootfs. Candidate execution starts only
    # in the separate restricted container created from this ephemeral image.
    seed = command('create', '--network', 'none', IMAGE).decode().strip()
    image = container = result = None
    try:
        command('cp', '-', seed+':/', input=payload_archive(tree, profile))
        image = command('commit', seed).decode().strip()
        command('rm', '-f', seed, timeout=15)
        seed = None
        container = command('create', '--name', name, '--network', 'none', '--read-only',
                        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64',
                        '--memory', '256m', '--cpus', '1', '--user', '10001:10001',
                        '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', '--workdir', '/tmp',
                        image, 'python', '-I', '-B', '/oracle/runner.py').decode().strip()
        config = json.loads(command('inspect', container))[0]
        output = command('start', '-a', container, timeout=65)
        if len(output) > 100000:
            raise ValueError('sandbox result too large')
        result = json.loads(output)
        result['container_id'] = container
        result['image'] = actual
        result['execution_image'] = image
        result['input_container_never_started'] = True
        result['oracle_hash'] = hashlib.sha256(oracle_for(profile).encode()).hexdigest()
        result['runner_hash'] = hashlib.sha256(RUNNER.encode()).hexdigest()
        result['restrictions'] = {key:config['HostConfig'][key] for key in
            ('NetworkMode','ReadonlyRootfs','CapDrop','SecurityOpt','PidsLimit','Memory','NanoCpus','Binds')}
        tests = result.get('tests', [])
        if len(tests) == 4 and result['exit_code'] == 0 and all(t['status'] == 'PASS' for t in tests):
            result['verdict'] = 'PASS'
        elif result['exit_code'] == 1 and any(t['status'] == 'FAIL' for t in tests):
            result['verdict'] = 'FAIL'
        else:
            result['verdict'] = 'INCONCLUSIVE'
    finally:
        errors = []
        for resource, arguments in [(seed,('rm','-f',seed)),(container,('rm','-f',container)),(image,('image','rm',image))]:
            if resource:
                try:
                    command(*arguments,timeout=15)
                except Exception as exc:
                    errors.append(type(exc).__name__)
        if errors:
            raise RuntimeError('Sandbox cleanup incomplete; retain unknown job for inspection: '+','.join(errors))
        if result is not None:
            result['container_removed'] = True
            result['execution_image_removed'] = True
    return result


class CodeTestJobs:
    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.path = Path(root) / 'code-jobs.sqlite'
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,input TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT,receipt_hash TEXT)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def input(self, workspace, candidate_id, variant, run_id=None):
        manifest = workspace.inspect(candidate_id)['manifest']
        value = {'candidate_id': candidate_id, 'variant': variant, 'profile': PROFILE,
                 'image': IMAGE, 'oracle_hash': hashlib.sha256(ORACLE.encode()).hexdigest(),
                 'runner_hash': hashlib.sha256(RUNNER.encode()).hexdigest()}
        if run_id is not None:
            import re
            if not isinstance(run_id, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}', run_id):
                raise ValueError('invalid code run id')
            value['run_id'] = run_id
        value['profile'] = manifest['profile']
        value['oracle_hash'] = hashlib.sha256(oracle_for(manifest['profile']).encode()).hexdigest()
        if variant not in ('baseline','candidate'):
            raise ValueError('unsupported test variant')
        return value

    def receipt(self, workspace, candidate_id, variant, run_id=None):
        value = self.input(workspace, candidate_id, variant, run_id)
        with closing(self.connect()) as db:
            row = db.execute('SELECT input,state,receipt,receipt_hash FROM jobs WHERE id=?', (digest(value),)).fetchone()
        if row is None:
            return None
        if row[0] != canonical(value):
            raise ValueError('code job identity changed')
        if row[1] != 'completed':
            raise RecoveryRequired('代码测试已启动，但还没有可靠结果；不会自动重跑。')
        result = json.loads(row[2])
        if (digest(result) != row[3] or any(result.get(k) != v for k,v in value.items())
                or result.get('job_id') != digest(value)
                or result.get('tree_hash') != workspace.inspect(candidate_id)['manifest'][variant+'_tree']['sha256']):
            raise ValueError('code receipt integrity or identity failure')
        return result

    def run(self, workspace, candidate_id, variant, *, run_id=None):
        value = self.input(workspace, candidate_id, variant, run_id)
        manifest = workspace.inspect(candidate_id)['manifest']
        existing = self.receipt(workspace, candidate_id, variant, run_id)
        if existing is not None:
            return existing
        with tempfile.TemporaryDirectory(prefix='graytower-replay-') as temporary:
            restored = workspace.restore(Path(temporary) / 'source', candidate_id, variant=variant)
            tree = snapshot(restored)
        job = digest(value)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT input,state,receipt,receipt_hash FROM jobs WHERE id=?', (job,)).fetchone()
            if row:
                if row[0] != canonical(value):
                    raise ValueError('code job identity changed')
                if row[1] != 'completed':
                    raise RecoveryRequired('代码作业已启动但无完成收据；保留现场，不自动重跑。')
                result = json.loads(row[2])
                if digest(result) != row[3]:
                    raise ValueError('code receipt integrity failure')
                return result
            db.execute('INSERT INTO jobs VALUES (?,?,?,NULL,NULL)', (job, canonical(value), 'running'))
        execution = execute_tree(tree) if value['profile']==PROFILE else execute_tree(tree,value['profile'])
        result = execution | {'job_id':job, **value, 'tree_hash':manifest[variant+'_tree']['sha256']}
        with closing(self.connect()) as db, db:
            db.execute('UPDATE jobs SET state=?,receipt=?,receipt_hash=? WHERE id=?', ('completed',canonical(result),digest(result),job))
        return result
