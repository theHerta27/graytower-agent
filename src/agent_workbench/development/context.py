"""Bounded model context. Full tool evidence lives outside the prompt."""
import json
from copy import deepcopy

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def clipped(text, byte_limit):
    raw = text.encode('utf-8')
    if len(raw) <= byte_limit:
        return text
    return raw[:max(0, byte_limit-160)].decode('utf-8', errors='ignore') + '\n[正文已缩短；需要源码细节时请按行重新读取。完整结果保留在任务记录。]'


def tool_text(value, byte_limit=6000):
    value = deepcopy(value)
    if isinstance(value, dict):
        for key in ('text', 'log', 'patch'):
            if isinstance(value.get(key), str):
                value[key] = clipped(value[key], max(600, byte_limit//2))
        result = value.get('result')
        if isinstance(result, dict) and isinstance(result.get('tests'), list):
            tests = result['tests']
            result['test_counts'] = {'total': len(tests), 'passed': sum(t.get('status') == 'PASS' for t in tests)}
            result['tests'] = [t for t in tests if t.get('status') != 'PASS'][:12]
            if isinstance(result.get('log'), str):
                result['log'] = clipped(result['log'], 1800)
    return clipped(json.dumps(value, ensure_ascii=False, sort_keys=True), byte_limit)


def bounded_messages(messages, *, instructions, memories, max_bytes):
    """Keep complete tool-call groups; discard old bodies rather than orphan tools."""
    if max_bytes < 4000:
        raise ValueError('context allowance too small for a safe task')
    memory_text = json.dumps(list(memories), ensure_ascii=False, sort_keys=True)
    system = SystemMessage(content=instructions + '\n项目记忆（仅供调查，当前源码和真实检查优先）：\n' + memory_text)
    groups = []
    for message in messages:
        if isinstance(message, ToolMessage) and groups:
            groups[-1].append(message.model_copy(update={'content': clipped(str(message.content), 6000)}))
        else:
            groups.append([message])
    def size(items):
        return len(json.dumps([m.model_dump() for m in items], ensure_ascii=False).encode('utf-8'))
    def flattened():
        return [system] + [m for group in groups for m in group]
    # Protect the original request and most recent decision + all its tool results.
    removed = []
    while size(flattened()) > max_bytes and len(groups) > 2:
        group = groups.pop(1)
        for message in group:
            if isinstance(message, AIMessage):
                removed.extend(c['name']+'#'+c['id'] for c in message.tool_calls)
    if removed:
        system = SystemMessage(content=system.content + '\n较早工具正文已移出上下文，操作类型：' + ', '.join(removed[-20:])
            + '。需要旧结论依据时重新读取源码或检查。')
    items = flattened()
    if size(items) > max_bytes:
        # A large last tool batch remains protocol complete; narrow only tool bodies.
        tools = sum(isinstance(m, ToolMessage) for m in items)
        allowance = max(160, (max_bytes-size([m for m in items if not isinstance(m, ToolMessage)])-1000)//max(1, tools))
        items = [m.model_copy(update={'content': clipped(str(m.content), allowance)}) if isinstance(m, ToolMessage) else m for m in items]
    if size(items) > max_bytes:
        raise ValueError('context exceeds allowance; shorten the request or tool arguments')
    return items
