"""Independent, checkpointed code QA over frozen patches and real job receipts."""
import asyncio
import json
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, ConfigDict, Field

from ..jobs import JobStore
from ..models import no_external_tracing
from .store import driver_lock


class CodeDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['read_events','finish']
    reason: str = Field(max_length=1500)


class CodeState(TypedDict, total=False):
    request_id: str
    candidate: dict
    baseline: dict
    candidate_result: dict
    decision: dict
    events: list
    errors: list
    report: dict
    model_attempted: bool
    model_used: bool


class CodeVerificationAgent:
    def __init__(self, root, model, tools):
        self.root, self.model, self.tools = Path(root), model, tools
        self.store = JobStore(root)

    async def run(self, request_id):
        with driver_lock(self.root/'drivers'/request_id), no_external_tracing():
            request = self.store.get(request_id)
            if request['report'] is not None:
                return request['report']

            async def inspect(state):
                candidate = await self.tools.call('inspect_code_candidate', {'manifest_hash':request['manifest_hash']})
                return {'candidate':candidate, 'errors':[], 'events':[]}

            async def baseline(state):
                value = await self.tools.call('run_test_profile', {'request_id':request_id,'variant':'baseline'})
                return {'baseline':value}

            async def candidate(state):
                value = await self.tools.call('run_test_profile', {'request_id':request_id,'variant':'candidate'})
                return {'candidate_result':value}

            async def decide(state):
                # Required test coverage belongs to the domain. Optional model
                # reasoning selects additional event investigation, not PASS.
                if self.model is None or getattr(self.model,'remaining_calls',lambda:1)() == 0:
                    return {'decision':{'action':'read_events','reason':'按预设方案核对测试中实际记录的游戏事件；本次未调用模型。'},'model_attempted':False,'model_used':False}
                before=getattr(self.model,'remaining_calls',lambda:None)()
                def charged():
                    after=getattr(self.model,'remaining_calls',lambda:None)()
                    return isinstance(before,int) and isinstance(after,int) and after<before
                try:
                    prompt = [
                        {'role':'system','content':'你是独立代码 QA，只读冻结候选，不修改代码。固定必要测试已经实际执行；你可以read_events继续检查事件，或finish。只说明证据及限制，不能用解释覆盖程序失败，不承诺全游戏通过。用自然中文，返回一个JSON对象action/reason。'},
                        {'role':'user','content':json.dumps({'goal':request['goal'],'candidate':state['candidate'],
                            'tests':{v:state[k]['result']['tests'] for v,k in [('baseline','baseline'),('candidate','candidate_result')]}},ensure_ascii=False)}]
                    decision = CodeDecision.model_validate(await asyncio.to_thread(self.model.complete,prompt,CodeDecision)).model_dump()
                    return {'decision':decision,'model_attempted':True,'model_used':charged()}
                except Exception as exc:
                    return {'decision':{'action':'read_events','reason':'模型未能给出可用决定，继续确定性事件核对。'},
                            'errors':[type(exc).__name__+': QA model unavailable'],'model_attempted':True,'model_used':charged()}

            async def events(state):
                results=[]
                for receipt in (state['baseline'],state['candidate_result']):
                    results.append(await self.tools.call('query_game_events',{'request_id':request_id,'job_id':receipt['job_id']}))
                return {'events':results}

            async def conclude(state):
                receipts = self.store.receipts(request_id)
                candidates = [r['result'] for r in receipts if r['args']['variant']=='candidate']
                failed = any(r.get('verdict')=='FAIL' or any(t.get('status')=='FAIL' for t in r.get('tests',[])) for r in candidates)
                covered = (len(candidates)==1 and len(receipts)==2 and candidates[0].get('verdict')=='PASS'
                    and candidates[0].get('exit_code')==0 and len(candidates[0].get('tests',[]))==4
                    and len({t.get('name') for t in candidates[0]['tests']})==4
                    and all(t.get('status')=='PASS' for t in candidates[0]['tests']))
                verdict = 'FAIL' if failed else 'PASS' if covered else 'INCONCLUSIVE'
                summary = {'PASS':'候选通过本次约定的4项规则与事件检查，可以审阅后采纳到本地测试版本。',
                    'FAIL':'候选仍有明确问题，请带着失败证据提出新的修复；旧候选和报告会保留。',
                    'INCONCLUSIVE':'本次没有完整可靠的检查结果，暂不能判断是否修好。'}[verdict]
                report = {'schema_version':'qa-report-v1','kind':'code','request_id':request_id,
                    'manifest_hash':request['manifest_hash'],'goal':request['goal'],'verdict':verdict,
                    'structural_verdict':'PASS','summary':summary,'jobs':receipts,
                    'charged_battles':0,'charged_test_runs':len(receipts),
                    'test_labels':state['candidate']['test_labels'],'observations':state['events'],
                    'agent_decision_note':state['decision']['reason'],'decision_note_is_not_verdict':True,
                    'errors':state['errors'],'model_used':state.get('model_used',False),'model_attempted':state.get('model_attempted',False),
                    'limitations':['只覆盖所列4项必要检查，不代表全游戏或Unity构建通过。',
                                   '当前单机、受控自有代码测试；不是通用不可信代码执行服务。']}
                self.store.complete(request_id,report)
                return {'report':report}

            graph=StateGraph(CodeState)
            for name,node in [('inspect',inspect),('baseline',baseline),('candidate',candidate),('decide',decide),('events',events),('conclude',conclude)]:
                graph.add_node(name,node)
            graph.add_edge(START,'inspect');graph.add_edge('inspect','baseline');graph.add_edge('baseline','candidate')
            graph.add_edge('candidate','decide')
            graph.add_conditional_edges('decide',lambda s:'events' if s['decision']['action']=='read_events' else 'conclude')
            graph.add_edge('events','conclude');graph.add_edge('conclude',END)
            async with AsyncSqliteSaver.from_conn_string(str(self.root/'code-qa-checkpoints.sqlite')) as saver:
                compiled=graph.compile(checkpointer=saver)
                config={'configurable':{'thread_id':request_id}}
                prior=await compiled.aget_state(config)
                if prior.values and not prior.next:
                    return prior.values['report']
                result=await compiled.ainvoke(None if prior.values else {'request_id':request_id},config)
                return result['report']
