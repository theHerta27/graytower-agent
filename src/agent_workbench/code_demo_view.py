"""Read the closed D-01 trial and verified receipts. Never execute or resume it."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from .code_candidates import CodeWorkspace, TARGET
from .coding.runtime_adapter import validate_runtime_receipt
from .jobs import digest


def load_code_demo(root):
    if root is None:
        return {'available':False}
    root=Path(root).resolve()
    result=json.loads((root/'result.json').read_text(encoding='utf-8'))
    closed=json.loads((root/'closed.json').read_text(encoding='utf-8'))
    prep=json.loads((root/'data/control/preparation.json').read_text(encoding='utf-8'))
    if closed.get('closed') is not True or result['budget']!=closed['budget']:
        raise ValueError('code demo is not a closed trial')
    workspace=CodeWorkspace(root/'data/control',root/'workspace',prep)
    candidate=workspace.inspect(result['candidate']['candidate_id'])
    if candidate!=result['candidate']:
        raise ValueError('code demo manifest differs from its frozen candidate')
    manifest=candidate['manifest']
    if manifest['provenance'].get('runtime_receipt')!=result['runtime_receipt']:
        raise ValueError('code candidate provenance differs from the Runtime receipt')
    receipt=workspace.artifacts.read_ref(result['runtime_receipt'],'coding-runtime-receipt-v1')
    tree=workspace.artifacts.read_ref(manifest['candidate_tree'],'code-tree-v1')
    validate_runtime_receipt(receipt,{'after_tree_hash':manifest['candidate_tree']['sha256'],
                                      'after_hash':tree['files'][TARGET]['sha256']})
    with closing(sqlite3.connect((root/'data/code-jobs.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        for label,variant in [('baseline','baseline'),('candidate_tests','candidate')]:
            saved=result[label]
            row=db.execute('SELECT state,receipt,receipt_hash FROM jobs WHERE id=?',(saved['job_id'],)).fetchone()
            if (row is None or row[0]!='completed' or json.loads(row[1])!=saved or digest(saved)!=row[2]
                    or saved['candidate_id']!=candidate['candidate_id'] or saved['variant']!=variant
                    or saved['tree_hash']!=manifest[variant+'_tree']['sha256']):
                raise ValueError('code demo test receipt mismatch')
    summary='\n\n'.join(item['text'] for item in receipt['task_turn']['items']
                         if item.get('type')=='agentMessage' and isinstance(item.get('text'),str))
    review='\n\n'.join(item.get('review',item.get('text','')) for item in receipt['review_turn']['items']
                        if item.get('type') in ('exitedReviewMode','agentMessage'))
    children=set()
    for event in receipt.get('native_spawn_events',[]):
        item=event.get('params',{}).get('item',{})
        if item.get('status')=='completed':children.update(item.get('receiverThreadIds',[]))
    return {'available':True,'request':manifest['request'],'candidate_id':candidate['candidate_id'],
            'patch':workspace.artifacts.read_ref(manifest['patch'],'code-patch-v1')['text'],
            'summary':summary,'review':review,'baseline_tests':result['baseline']['tests'],
            'candidate_tests':result['candidate_tests']['tests'],
            'calls':result['budget']['reserved'],'cost_usd':result['budget']['known_cost_usd'],
            'autonomous_children':len(children),'applied':False,'new_calls_on_read':0}
