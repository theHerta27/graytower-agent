"""Small real boundary probe, not a general container security certification."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agent_workbench.code_sandbox import IMAGE, command
code = '''import os,socket,json
r={'uid':os.getuid(),'credential_names':[k for k in os.environ if k.endswith('API_KEY') or k.endswith('TOKEN')]}
try:
    open('/etc/graytower-write-probe','w').write('x')
    r['root_write']='ALLOWED'
except OSError:
    r['root_write']='DENIED'
s=socket.socket();s.settimeout(1)
r['external_connection_result']=s.connect_ex(('192.0.2.1',443))
print(json.dumps(r))
'''
raw = command('run','--rm','-i','--network','none','--read-only','--cap-drop','ALL',
              '--security-opt','no-new-privileges','--pids-limit','64','--memory','256m','--cpus','1',
              '--tmpfs','/tmp:rw,noexec,nosuid,size=32m', IMAGE, 'python','-I','-B','-', input=code.encode())
result=json.loads(raw)
assert result['uid']==10001 and result['root_write']=='DENIED' and not result['credential_names']
assert result['external_connection_result']!=0
path=ROOT/'local-data/code-sandbox-preflight-v2/boundaries.json'
path.write_text(json.dumps(result,indent=2),encoding='utf-8')
print(raw.decode())
