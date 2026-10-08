"""Bounded negative checks of local container settings, not escape certification."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from agent_workbench.code_sandbox import command,IMAGE

SETTINGS=['--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
          '--pids-limit','64','--memory','256m','--cpus','1','--user','10001:10001',
          '--tmpfs','/tmp:rw,noexec,nosuid,size=32m']
BOUNDARY="""import os,json,socket
r={'uid':os.getuid(),'credential_names':[k for k in os.environ if k.endswith(('API_KEY','TOKEN'))]}
for name in ['/etc/graytower-test','/host','/var/run/docker.sock']:
 try:
  with open(name,'wb') as f:f.write(b'x')
  r[name]='ALLOWED'
 except OSError:r[name]='DENIED'
r['proc_status']=[s for s in open('/proc/self/status') if s.startswith(('CapEff:','NoNewPrivs:'))]
s=socket.socket();s.settimeout(1);r['network_result']=s.connect_ex(('192.0.2.1',443))
print(json.dumps(r))
"""
def probe(code,timeout):
    container=command('create',*SETTINGS,IMAGE,'python','-I','-B','-c',code).decode().strip()
    result={'container_id':container}
    try:
        settings=json.loads(command('inspect',container))[0]['HostConfig']
        result['settings']={k:settings[k] for k in ('Binds','NetworkMode','ReadonlyRootfs','Memory','PidsLimit','CapDrop','SecurityOpt')}
        assert not settings['Binds'] and settings['Memory']==256*1024*1024
        try:result['output']=command('start','-a',container,timeout=timeout).decode()
        except subprocess.TimeoutExpired:result['host_timeout']=True
        except RuntimeError:result['nonzero_exit']=True
        result['state']=json.loads(command('inspect',container))[0]['State']
    finally:
        command('rm','-f',container,timeout=15)
        result['removed']=not bool(command('ps','-aq','--filter','id='+container).strip())
        assert result['removed']
    return result

def run(path):
    if path.exists():raise ValueError('do not overwrite prior evidence')
    path.parent.mkdir(parents=True,exist_ok=True)
    basic=probe(BOUNDARY,10);facts=json.loads(basic['output'])
    assert facts['uid']==10001 and not facts['credential_names'] and facts['network_result']!=0
    assert all(facts[p]=='DENIED' for p in ('/etc/graytower-test','/host','/var/run/docker.sock'))
    memory=probe('x=bytearray(512*1024*1024);print(len(x))',15)
    assert memory['state']['OOMKilled']
    timeout=probe('while True: pass',2)
    assert timeout.get('host_timeout')
    path.write_text(json.dumps({'image':IMAGE,'basic':basic,'memory':memory,'timeout':timeout,
        'limits':'Actual settings and bounded failure probes; no claim of general malicious-code isolation or hard-kill recovery.'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'root_read_only':True,'no_host_mounts':True,'memory_limit':True,'timeout_cleanup':True,'all_removed':True}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);run(p.parse_args().output.resolve())
