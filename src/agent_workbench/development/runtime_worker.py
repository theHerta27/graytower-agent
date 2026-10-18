"""Credential-free SDK process. Codex owns planning, model calls and tool loop."""
from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from ..coding.runtime_adapter import VERSION, model_catalog, safe_environment
from .runtime import INSTRUCTIONS, build_config, parameters
from .workspace import ProjectWorkspace, encoded
from .checks import CheckJobs
from .tools import DevelopmentTools


def run(request):
    clean=safe_environment(os.environ,Path(__file__).resolve().parents[2])
    os.environ.clear();os.environ.update(clean)
    from codex_cli_bin import bundled_codex_path
    from openai_codex.client import CodexClient,CodexConfig
    if version('openai-codex')!=VERSION or version('openai-codex-cli-bin')!=VERSION:
        raise ValueError('require the tested SDK/Runtime pair '+VERSION)
    control=Path(request['control'])
    workspace=ProjectWorkspace.open(request['workspace_control'])
    home=control/'codex-home';home.mkdir()
    catalog=model_catalog()
    catalog['models'][0]['model_messages']['instructions_template']=INSTRUCTIONS
    (home/'models.json').write_bytes(encoded(catalog))
    (home/'config.toml').write_text(build_config(home,workspace.path,request['endpoint']),encoding='utf-8')
    os.environ['CODEX_HOME']=str(home)
    jobs=CheckJobs(workspace.control/'checks',python=request['tools_python'])
    tools=DevelopmentTools(workspace,jobs)
    thread_id='';lock=threading.Lock()
    def record(value):
        with lock:
            with (control/'events.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(value,ensure_ascii=False)+'\n')
    def callback(method,params):
        result=tools.handle(method,params,thread_id)
        record({'type':'host_call','method':method,'params':params,'result':result})
        return result
    client=CodexClient(CodexConfig(cwd=str(workspace.path)),approval_handler=callback)
    timer=threading.Timer(request['timeout_seconds'],client.close);timer.daemon=True
    result={'schema':'development-runtime-v1','status':'failed','mode':'single','sdk':VERSION,'runtime':VERSION,
            'runtime_sha256':hashlib.sha256(bundled_codex_path().read_bytes()).hexdigest(),
            'before_tree_hash':workspace.inspect()['tree_hash']}
    try:
        client.start();timer.start();client.initialize()
        thread_id=client.thread_start(parameters(workspace.path)).thread.id
        result['thread_id']=thread_id
        task=client.turn_start(thread_id,request['prompt'])
        while True:
            event=client.next_turn_notification(task.turn.id)
            payload=event.payload
            value=payload.model_dump(mode='json',by_alias=True) if hasattr(payload,'model_dump') else payload.params
            record({'type':'notification','method':event.method,'params':value})
            if event.method=='turn/completed' and value.get('turn',{}).get('id')==task.turn.id:
                result['turn']=value['turn'];break
        client.unregister_turn_notifications(task.turn.id)
        result['thread']=client.thread_read(thread_id,include_turns=True).model_dump(mode='json',by_alias=True)
        result['status']='completed' if result['turn']['status']=='completed' else 'failed'
    except Exception as exc:
        result['error_type']=type(exc).__name__
        raise
    finally:
        timer.cancel();client.close()
        result['after_tree_hash']=workspace.inspect()['tree_hash']
        result['checks']=jobs.list(workspace)
        (control/'result.json').write_bytes(encoded(result))
    return result


if __name__=='__main__':print(json.dumps(run(json.loads(sys.stdin.read())),ensure_ascii=False))
