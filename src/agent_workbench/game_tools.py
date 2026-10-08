"""Shared local MCP game tools. No model credentials or candidate authoring here."""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from fractions import Fraction

from pydantic import StrictInt

from .domain import CandidateRepository
from .jobs import JobStore, canonical
from .domain._shared import digest, valid_hash


def validate_game_result(result, manifest_hash, seeds, policies):
    """Bind every paired row and Trace to the admitted execution before receipting."""
    plan = {'manifest_hash': manifest_hash, 'seeds': seeds, 'policies': policies}
    units = 2 * len(seeds) * len(policies)
    identity = result.get('identity', {})
    if (result.get('manifest_hash') != manifest_hash
            or any(canonical(identity.get(key)) != canonical(value) for key, value in plan.items())
            or identity.get('execution_hash') != digest(plan)
            or type(result.get('completed_battles')) is not int or result['completed_battles'] != units):
        raise ValueError('game result identity/coverage mismatch')
    expected = {(seed, policy) for seed in seeds for policy in policies}
    rows, refs = result.get('rows', []), result.get('trace_refs', [])
    if not isinstance(rows, list) or not isinstance(refs, list) or len(rows) != len(expected) or len(refs) != units:
        raise ValueError('game result missing or duplicate row/trace')
    actual, summaries = set(), {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get('seed')) is not int or not isinstance(row.get('policy'), str):
            raise ValueError('invalid game row identity')
        key = (row['seed'], row['policy'])
        if key not in expected or key in actual:
            raise ValueError('foreign or duplicate game row')
        actual.add(key)
        for variant in ('baseline', 'candidate'):
            summary = row.get(variant, {})
            if (type(summary.get('seed')) is not int or summary['seed'] != key[0]
                    or summary.get('strategy') != key[1] or summary.get('outcome') not in ('win', 'loss', 'timeout')
                    or Fraction(summary.get('elapsed_av', '0')) <= 0):
                raise ValueError('game summary identity/outcome mismatch')
            summaries[(*key, variant)] = valid_hash(summary.get('trace_sha256'))
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict) or type(ref.get('seed')) is not int or not isinstance(ref.get('policy'), str):
            raise ValueError('invalid trace identity')
        key = (ref['seed'], ref['policy'], ref.get('variant'))
        if key not in summaries or key in seen or ref.get('sha256') != summaries[key]:
            raise ValueError('foreign, duplicate or mismatched trace')
        if ref.get('artifact_id') != ref['sha256'] or ref.get('schema') != 'combat-trace-v2':
            raise ValueError('wrong trace artifact reference')
        seen.add(key)


def _trace_excerpt(trace, reference):
    """Project observed events, never infer effectiveness or a cross-version cause."""
    events = trace['events']
    event_fields = ('event_id', 'kind', 'actor_id', 'target_id', 'av', 'turn_id', 'action_id', 'cause_event_id')
    payload_fields = {'skill_id', 'target_ids', 'reason_code', 'amount', 'hp_loss', 'absorbed',
                      'overkill', 'critical', 'damage_type', 'outcome', 'reason', 'before', 'after',
                      'from_phase', 'to_phase', 'entered', 'weaknesses', 'buff_id'}

    def scalar(value):
        return value is None or type(value) in (str, int, float, bool)

    projected, actions, finishes, landmarks = [], {}, [], []
    for index, event in enumerate(events):
        payload = {key: value for key, value in event['payload'].items() if key in payload_fields
                   and (scalar(value) or isinstance(value, list) and all(scalar(item) for item in value))}
        projected.append({**{key: event.get(key) for key in event_fields},
                          'skill_id': payload.get('skill_id'), 'payload': payload})
        kind, action = event['kind'], event.get('action_id')
        if kind in ('decision', 'direct_damage', 'break_damage', 'dot_damage'):
            if action is not None:
                actions.setdefault(action, []).append(index)
            else:
                landmarks.append(index)
        elif kind == 'battle_finished':
            finishes.append(index)
        elif kind in ('phase_changed', 'unit_died', 'break_triggered'):
            landmarks.append(index)

    # Reserve the ending and its action context before taking earlier action
    # groups. A group is never byte-sliced into incomplete JSON or half an action.
    groups = []
    if finishes:
        last = finishes[-1]
        groups.append([last])
        groups.append(actions.get(events[last].get('action_id'), []))
    groups.extend(actions.values())
    groups.extend([index] for index in landmarks)
    identity = {key: reference[key] for key in ('seed', 'policy', 'variant')}
    selected = set()
    excerpt = canonical({**identity, 'events': []})
    if len(excerpt) > 6000:
        raise ValueError('trace identity exceeds excerpt limit')
    for group in groups:
        proposed = selected.union(group)
        bounded = canonical({**identity, 'events': [projected[index] for index in sorted(proposed)]})
        if len(bounded) <= 6000:
            selected, excerpt = proposed, bounded
    return excerpt, {
        'view': 'combat-trace-excerpt-v1', 'total_events': len(events), 'selected_events': len(selected),
        'omitted_events': len(events) - len(selected), 'excerpt_characters': len(excerpt),
        'partial_trace': True, 'single_variant': True, 'causal_comparison': False,
        'rule': '先保留最后battle_finished，再尝试其action的决策/伤害组；随后按原始顺序选各action的决策/伤害组；余量选阶段、死亡、击破与无action伤害事件。每组整体纳入，超过6000字符则跳过，最后按原始事件顺序显示。',
        'projection': '仅保留事件身份、行动关联及白名单payload标量/标量数组；省略状态快照、其他payload字段和未选事件。',
        'limit': '这是单个版本的部分事件摘录，不是完整Trace或版本对照；不能据此确认倍率已生效、总体效果或因果关系。',
    }


class GameTools:
    def __init__(self, root):
        self.root = Path(root)
        self.repo = CandidateRepository(self.root)
        self.store = JobStore(self.root)

    def inspect_candidate(self, manifest_hash):
        candidate = self.repo.get(manifest_hash)
        m = candidate['manifest']
        return {k: candidate[k] for k in ('manifest_hash', 'diff', 'validation')} | {
            'intent': m['request'], 'profile': m['profile'], 'kind': m['kind'],
            'input_refs': {k: m[k] for k in ('baseline', 'candidate', 'scenario', 'rules', 'schema')}}

    def run_simulation(self, request_id, seeds, policies):
        from .domain._shared import check_plan
        check_plan(seeds, policies)
        request = self.store.get(request_id)
        args = {'seeds': seeds, 'policies': policies}
        units = 2*len(seeds)*len(policies)
        def execute():
            result = self.repo.verify(request['manifest_hash'], seeds, policies)
            validate_game_result(result, request['manifest_hash'], seeds, policies)
            return result
        receipt = self.store.run(request_id, args, units, execute)
        validate_game_result(receipt['result'], request['manifest_hash'], seeds, policies)
        return receipt

    def read_trace(self, request_id, artifact_hash):
        refs = [ref for j in self.store.receipts(request_id) for ref in j['result'].get('trace_refs', [])]
        if artifact_hash not in {r['sha256'] for r in refs}:
            raise ValueError('trace is outside this request evidence')
        trace = self.repo.read_artifact(artifact_hash)
        # Preserve the hash-checked full trace. The tool returns a separate,
        # explicitly partial event projection instead of slicing giant snapshots.
        reference = next(r for r in refs if r['sha256'] == artifact_hash)
        excerpt, selection = _trace_excerpt(trace, reference)
        return {'artifact_hash': artifact_hash, 'characters': len(canonical(trace)),
                'excerpt': excerpt, 'truncated': True, 'selection': selection, 'reference': reference}


def serve(root):
    from mcp.server import MCPServer
    game = GameTools(root)
    server = MCPServer('local-combat-tools', version='v1', log_level='WARNING')

    def logged(name, args, result):
        with (Path(root) / 'tool-calls.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(canonical({'tool': name, 'arguments': args, 'ok': True}) + '\n')
        return result

    @server.tool(structured_output=True)
    def inspect_candidate(manifest_hash: str) -> dict[str, Any]:
        """Read a frozen numeric candidate; independently check its identity and rules."""
        return logged('inspect_candidate', {'manifest_hash': manifest_hash}, game.inspect_candidate(manifest_hash))

    @server.tool(structured_output=True)
    def run_simulation(request_id: str, seeds: list[StrictInt], policies: list[str]) -> dict[str, Any]:
        """Run approved paired battles within the durable request budget; reuse receipts."""
        return logged('run_simulation', {'request_id': request_id, 'seeds': seeds, 'policies': policies},
                      game.run_simulation(request_id, seeds, policies))

    @server.tool(structured_output=True)
    def read_trace(request_id: str, artifact_hash: str) -> dict[str, Any]:
        """Read bounded decision/damage/end events from ONE variant; not causal proof."""
        return logged('read_trace', {'request_id': request_id, 'artifact_hash': artifact_hash},
                      game.read_trace(request_id, artifact_hash))

    @server.tool(structured_output=True)
    def read_receipts(request_id: str) -> dict[str, Any]:
        """Read validated completed job receipts only; never launch a simulation."""
        return logged('read_receipts', {'request_id': request_id},
                      {'receipts': game.store.receipts(request_id)})

    server.run(transport='stdio')


class ToolClient:
    def __init__(self, client):
        self.client = client

    async def call(self, name, args):
        result = await self.client.call_tool(name, args)
        if result.is_error:
            raise ValueError('game tool rejected request: ' + str(result.content)[:800])
        if result.structured_content is None:
            raise ValueError('game tool omitted structured result')
        return result.structured_content


@asynccontextmanager
async def connect_tools(root, *, module='agent_workbench.game_tools'):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.upper() in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH')}
    env.update(PYTHONUTF8='1', PYTHONPATH=str(Path(__file__).resolve().parents[1]), LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false')
    if module not in ('agent_workbench.game_tools','agent_workbench.code_tools'):
        raise ValueError('unsupported local tool service')
    params = StdioServerParameters(command=sys.executable, args=['-X', 'utf8', '-m', module, '--data', str(root)], env=env)
    with (root / 'mcp-stderr.log').open('a', encoding='utf-8') as errors:
        async with Client(stdio_client(params, errlog=errors), cache=None) as client:
            yield ToolClient(client)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    serve(parser.parse_args().data)
