"""Bounded model context. Full tool evidence lives outside the prompt."""
import json
from copy import deepcopy

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def clipped(text, byte_limit):
    raw = text.encode('utf-8')
    if len(raw) <= byte_limit:
        return text
    return raw[:max(0, byte_limit-160)].decode('utf-8', errors='ignore') + '\n[正文已缩短；需要源码细节时请按行重新读取。完整结果保留在任务记录。]'


def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True)


def _omitted(value,byte_limit):
    """An explicit evidence stub is preferable to an incomplete JSON string."""
    summary={'context_omitted':True}
    if isinstance(value,dict):
        for key in ('id','version','start_char','next_char','total_chars','sha256','job_id','status','verdict',
                    'matches_current_candidate','start_line','start_column','next_line','next_column',
                    'path','document_id','end_line','end_column','total_lines','tree_hash',
                    'candidate_tree_hash','check_set','exit_code'):
            item=value.get(key)
            if item is None or isinstance(item,(str,int,bool)):
                if key in value:summary[key]=clipped(item,500) if isinstance(item,str) else item
        result=value.get('result')
        if isinstance(result,dict):
            summary['result']={k:result[k] for k in ('verdict','exit_code','test_counts','resources_removed') if k in result}
    elif isinstance(value,list):
        summary.update(items=[],total_items=len(value))
        for item in value:
            excerpt=({k:(clipped(v,400) if isinstance(v,str) else v) for k,v in item.items()
                      if k in ('path','line','id','text')} if isinstance(item,dict) else item)
            summary['items'].append(excerpt)
            if len(_json(summary).encode('utf-8'))>byte_limit:
                summary['items'].pop();break
    summary['note']='正文已移出上下文，完整证据保留在任务记录；需要时重读本页起点，不要据此跳过未显示正文。'
    while len(_json(summary).encode('utf-8'))>byte_limit and len(summary)>1:
        summary.pop(next(key for key in reversed(summary) if key!='context_omitted'))
    return _json(summary)


def _compact_content(content,byte_limit=6000):
    try:value=json.loads(content)
    except (ValueError,TypeError):
        if len(content.encode('utf-8'))<=byte_limit and not content.lstrip().startswith(('{','[')):return content
        value=None
    return content if value is not None and len(content.encode('utf-8'))<=byte_limit else _omitted(value,byte_limit)


def tool_text(value, byte_limit=6000):
    value = deepcopy(value)
    if isinstance(value, dict):
        for key in ('text', 'log', 'patch'):
            if key=='text' and 'next_line' in value and 'sha256' in value:continue
            if isinstance(value.get(key), str):
                value[key] = clipped(value[key], max(600, byte_limit//2))
        result = value.get('result')
        if isinstance(result, dict) and isinstance(result.get('tests'), list):
            tests = result['tests']
            result['test_counts'] = {'total': len(tests), 'passed': sum(t.get('status') == 'PASS' for t in tests)}
            result['tests'] = [t for t in tests if t.get('status') != 'PASS'][:12]
            if isinstance(result.get('log'), str):
                result['log'] = clipped(result['log'], 1800)
    text=_json(value)
    return text if len(text.encode('utf-8'))<=byte_limit else _omitted(value,byte_limit)


def knowledge_text(value):
    """Keep valid JSON and source IDs; full prose is available in bounded pages."""
    def source(hit):
        return {key:hit[key] for key in ('id','version','start_line','end_line')} | {
            'path':clipped(hit['path'],1000),'heading':clipped(hit['heading'],600)}
    if isinstance(value,list):
        results=[source(hit)|{'excerpt':hit['text'][:180]} for hit in value]
        output={'results':results,'matched':len(value),'returned':len(results),'note':'用read_knowledge读取正文，按next_char继续；出处全文保留在任务证据。'}
        while results and len(json.dumps(output,ensure_ascii=False).encode('utf-8'))>5500:
            results.pop();output['returned']=len(results)
    else:
        output=source(value)|{key:value[key] for key in ('text','start_char','next_char','total_chars')}
    text=json.dumps(output,ensure_ascii=False,sort_keys=True)
    if len(text.encode('utf-8'))>5500:
        raise ValueError('knowledge context page exceeds allowance')
    return text


def _history_references(groups):
    references={}
    for group in groups:
        values={m.tool_call_id:m for m in group if isinstance(m,ToolMessage)}
        for message in group:
            if not isinstance(message,AIMessage):continue
            for call in message.tool_calls:
                args=call['args'];body={}
                if call['id'] in values:
                    try:body=json.loads(values[call['id']].content)
                    except (TypeError,ValueError):pass
                ref={'tool':call['name'],'reference':call['id'][:100]}
                for key in ('path','query','job_id','chunk_id'):
                    if isinstance(args.get(key),str):ref[key]=args[key]
                if isinstance(body,dict):
                    for key in ('id','path','version','sha256','tree_hash','status','verdict','start_char','next_char','total_chars','context_omitted'):
                        item=body.get(key)
                        if key in body and (item is None or isinstance(item,(str,int,bool))):ref[key]=item
                    if call['name']=='read_knowledge' and isinstance(body.get('id'),str):ref['chunk_id']=body['id']
                    if 'end_line' in body and not body.get('context_omitted'):
                        ref['range']=[body.get('start_line'),body.get('start_column',0),body['end_line'],body.get('end_column')]
                    else:
                        if 'start_line' in args:ref['requested_start_line']=args['start_line']
                    result=body.get('result')
                    if isinstance(result,dict) and 'verdict' in result:ref['verdict']=result['verdict']
                identity=tuple(ref.get(key) for key in ('tool','path','sha256','query','job_id','chunk_id','version'))
                old=references.pop(identity,None)
                if old and 'range' in ref:ref['earlier_ranges']=(old.get('earlier_ranges',[])+([old['range']] if 'range' in old else []))[-4:]
                references[identity]=ref
    rows=list(references.values())[-12:]
    while rows and len(_json(rows).encode('utf-8'))>2200:rows.pop(0)
    return _json(rows)


def bounded_messages(messages, *, instructions, memories, max_bytes):
    """Keep complete tool-call groups; discard old bodies rather than orphan tools."""
    if max_bytes < 4000:
        raise ValueError('context allowance too small for a safe task')
    memory_text = json.dumps(list(memories), ensure_ascii=False, sort_keys=True)
    base=instructions + '\n项目记忆（仅供调查，当前源码和真实检查优先）：\n' + memory_text
    system=SystemMessage(content=base)
    groups = []
    for message in messages:
        if isinstance(message, ToolMessage) and groups:
            groups[-1].append(message.model_copy(update={'content': _compact_content(str(message.content))}))
        else:
            groups.append([message])
    def size(items):
        return len(json.dumps([m.model_dump() for m in items], ensure_ascii=False).encode('utf-8'))
    def flattened():
        return [system] + [m for group in groups for m in group]
    # Protect the original request and most recent decision + all its tool results.
    removed=[]
    while size(flattened()) > max_bytes and len(groups) > 2:
        removed.append(groups.pop(1))
        system=SystemMessage(content=base+'\n历史工具来源（正文已移出；仅表示位置，旧SHA/旧检查不证明当前候选。索引非完整历史）：\n'+_history_references(removed))
    items = flattened()
    if size(items) > max_bytes:
        # Preserve every call/result pair. Omit older bodies explicitly rather
        # than cutting every JSON result (including the latest one) mid-string.
        for index,message in enumerate(items):
            if size(items)<=max_bytes:break
            if isinstance(message,ToolMessage):
                try:value=json.loads(message.content)
                except (TypeError,ValueError):value=None
                items[index]=message.model_copy(update={'content':_omitted(value,800)})
    if size(items) > max_bytes:
        raise ValueError('context exceeds allowance; shorten the request or tool arguments')
    return items
