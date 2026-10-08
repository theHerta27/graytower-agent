"""Dedicated SDK process; launched only by runtime_adapter.run_runtime."""
from __future__ import annotations

from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

from .file_tools import FileTools, edit_handler
from .runtime_adapter import VERSION, model_catalog, runtime_config, safe_environment, thread_params


def run(request):
    # CodexConfig.env merges the parent environment; scrub this dedicated worker
    # first. Never perform this operation in an API server or caller process.
    clean = safe_environment(os.environ, Path(__file__).resolve().parents[2])
    os.environ.clear()
    os.environ.update(clean)
    from codex_cli_bin import bundled_codex_path
    from openai_codex.client import CodexClient, CodexConfig
    from openai_codex.generated.v2_all import ReviewStartResponse, ListMcpServerStatusResponse
    from .candidates import CodingWorkspace
    from ..domain import CandidateRepository

    if version('openai-codex') != VERSION or version('openai-codex-cli-bin') != VERSION:
        raise ValueError('Coding requires the tested SDK and its exact default Runtime pair')
    control, workspace = Path(request['control']), Path(request['workspace'])
    profile = request['preparation'].get('profile')
    home = control / 'codex-home'
    home.mkdir()
    (home / 'models.json').write_text(json.dumps(model_catalog(profile=profile), ensure_ascii=False), encoding='utf-8')
    (home / 'config.toml').write_text(runtime_config(
        home, workspace, Path(request['data']), Path(request['tools_python']), request['endpoint'], request['mode'],
        request['preparation']), encoding='utf-8')
    os.environ['CODEX_HOME'] = str(home)
    if profile == 'shield-damage-python-v1':
        from ..code_candidates import runtime_workspace, TARGET
        candidate_workspace = runtime_workspace(request['data'], workspace, request['preparation'])
        files = FileTools(workspace, control / 'file-control', editable_file=TARGET)
    else:
        files = FileTools(workspace, control / 'file-control')
        candidate_workspace = CodingWorkspace(workspace, CandidateRepository(Path(request['data'])), request['preparation'])
    initial_inspection = candidate_workspace.inspect_changes()
    before_tree = initial_inspection['after_tree_hash']
    original = files.read_file()
    thread_id = ''
    editing = True
    lock = threading.Lock()
    events = []

    def record(value):
        with lock:
            events.append(value)
            with (control / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(value, ensure_ascii=False) + '\n')

    def callback(method, params):
        result = edit_handler(files, thread_id if editing else '')(method, params)
        record({'type': 'host_call', 'method': method, 'params': params, 'result': result})
        return result

    client = CodexClient(CodexConfig(cwd=str(workspace)), approval_handler=callback)
    timer = threading.Timer(request['timeout_seconds'], client.close)
    timer.daemon = True
    result = {'schema': 'coding-runtime-run-v1', 'mode': request['mode'], 'sdk': VERSION, 'runtime': VERSION,
              'runtime_sha256': hashlib.sha256(bundled_codex_path().read_bytes()).hexdigest(),
              'before_sha256': original['sha256'], 'before_tree_hash': before_tree,
              'baseline_tree_hash': initial_inspection['before_tree_hash'], 'status': 'failed'}

    def read_until(next_notification, turn_id):
        while True:
            event = next_notification()
            payload = event.payload
            value = (payload.model_dump(mode='json', by_alias=True) if hasattr(payload, 'model_dump') else payload.params)
            record({'type': 'notification', 'method': event.method, 'params': value})
            if event.method == 'turn/completed' and value.get('turn', {}).get('id') == turn_id:
                return value['turn']

    try:
        client.start()
        timer.start()
        client.initialize()
        started = client.thread_start(thread_params(workspace, request['mode'], profile=profile))
        thread_id = started.thread.id
        result['thread_id'] = thread_id
        result['mcp_status'] = client.request('mcpServerStatus/list', {'threadId': thread_id, 'serverName': 'coding_readonly'},
                                             response_model=ListMcpServerStatusResponse).model_dump(mode='json', by_alias=True)
        available = result['mcp_status']['data']
        if (len(available) != 1 or available[0]['name'] != 'coding_readonly'
                or set(available[0]['tools']) != {'list_workspace', 'read_file', 'check_workspace'}
                or available[0].get('toolsError')):
            raise RuntimeError('The read-only workspace MCP service is unavailable')
        task = client.turn_start(thread_id, request['prompt'])
        result['task_turn'] = read_until(lambda: client.next_turn_notification(task.turn.id), task.turn.id)
        client.unregister_turn_notifications(task.turn.id)
        if result['task_turn']['status'] != 'completed':
            raise RuntimeError('Runtime task did not complete')
        edited = files.read_file()
        review_tree = candidate_workspace.inspect_changes()['after_tree_hash']
        editing = False
        review_instructions = ('Review only this bounded game file edit. Do not edit files or run code. '
                               'Check the requested change and accidental other changes. Return findings supported by the file diff.\n'
                               + json.dumps({'request': request['prompt'], 'before': original, 'after': edited}, ensure_ascii=False))
        review = client.request('review/start', {'threadId': thread_id, 'delivery': 'inline',
                                 'target': {'type': 'custom', 'instructions': review_instructions}},
                                response_model=ReviewStartResponse)
        # Generic review/start does not pre-register the SDK's turn queue. A fast
        # completion can be pruned before a later subscription; query the public
        # durable thread history instead, without patching the SDK router.
        while True:
            history = client.thread_read(thread_id, include_turns=True).model_dump(mode='json', by_alias=True)
            turns = [turn for turn in history['thread']['turns'] if turn['id'] == review.turn.id]
            if turns and turns[0]['status'] != 'inProgress':
                result['review_turn'] = turns[0]
                break
            time.sleep(.1)
        result['review_file_sha256'] = edited['sha256']
        result['review_tree_hash'] = review_tree
        result['after_sha256'] = files.read_file()['sha256']
        result['after_tree_hash'] = candidate_workspace.inspect_changes()['after_tree_hash']
        result['status'] = ('completed' if result['review_turn']['status'] == 'completed'
                            and result['after_sha256'] == edited['sha256']
                            and result['after_tree_hash'] == review_tree else 'failed')
        result['thread'] = client.thread_read(thread_id, include_turns=True).model_dump(mode='json', by_alias=True)
        # Parent events include actual native spawn lifecycle; no inferred Agent count.
        result['native_spawn_events'] = [event for event in events if event.get('method') == 'item/completed'
                                        and event.get('params', {}).get('item', {}).get('type') == 'collabAgentToolCall'
                                        and event['params']['item'].get('tool') == 'spawnAgent']
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        raise
    finally:
        timer.cancel()
        client.close()
        (control / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(run(json.loads(sys.stdin.read())), ensure_ascii=False))
