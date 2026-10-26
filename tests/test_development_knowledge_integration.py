"""Knowledge is an explicitly confirmed, frozen input to the real task service."""
import json
import unittest
from langchain_core.messages import AIMessage, ToolMessage
from starlette.testclient import TestClient
import test_development_checks as fixtures
from test_development_agent import ScriptModel, call
from agent_workbench.development.workspace import git
from agent_workbench.development.service import DevelopmentTask
from agent_workbench.development.web import create_app


class KnowledgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.source=self.root/'source'
        path=self.source/'docs/rules.md';path.parent.mkdir()
        path.write_text('# 资源规则\n\n## 非法参数\n\n非法资源参数必须先报错，不能改变战技点。\n\n## 护盾\n\n护盾吸收生命伤害。\n',encoding='utf-8')
        git(self.source,'add','docs/rules.md');git(self.source,'commit','-qm','add rules')
        self.task=DevelopmentTask.create(self.source,self.root/'knowledge-task','修复非法资源参数改变状态的问题。',knowledge_mode='lexical')
        self.grant={'max_calls':4,'max_input_bytes':100000,'max_output_tokens':512,'cost_cap_usd':'0',
                    'input_usd_per_million':'0','cached_input_usd_per_million':'0','output_usd_per_million':'0'}

    def document(self):
        item=self.task.knowledge.import_file(self.task.workspace,'docs/rules.md',headings=['非法参数'])
        self.task.knowledge.set_status(self.task.workspace.metadata['project'],item['id'],'confirmed')
        return item

    def test_pending_excluded_and_confirmed_material_frozen_in_preview(self):
        item=self.task.knowledge.import_file(self.task.workspace,'docs/rules.md',headings=['非法参数'])
        scope=self.task.prepare('pending',self.grant)
        preview=json.loads((self.task._batch('pending')/'outbound-preview.json').read_text(encoding='utf-8'))
        self.assertEqual(preview['knowledge']['documents'],[])
        self.task.knowledge.set_status(self.task.workspace.metadata['project'],item['id'],'confirmed')
        scope=self.task.prepare('confirmed',self.grant)
        preview=json.loads((self.task._batch('confirmed')/'outbound-preview.json').read_text(encoding='utf-8'))
        self.assertEqual(len(preview['knowledge']['documents']),1)
        self.assertNotIn('护盾吸收',json.dumps(preview['knowledge'],ensure_ascii=False))
        self.assertEqual(scope['knowledge_hash'],self.task.knowledge_hash())

    def test_changed_confirmation_blocks_first_model_call(self):
        item=self.document();scope=self.task.prepare('before-change',self.grant)
        self.task.knowledge.set_status(self.task.workspace.metadata['project'],item['id'],'pending')
        model=ScriptModel([AIMessage(content='不应调用')])
        with self.assertRaises(ValueError):self.task.execute('before-change',scope['scope_sha256'],model=model)
        self.assertEqual(model.saved,{})
        self.assertFalse((self.task._batch('before-change')/'claimed').exists())

    def test_agent_can_query_frozen_document_even_if_live_library_changes(self):
        item=self.document();scope=self.task.prepare('query',self.grant)
        def first(messages):
            self.task.knowledge.set_status(self.task.workspace.metadata['project'],item['id'],'pending')
            return call('search_knowledge',{'query':'非法资源参数'},'search-docs')
        def finish(messages):
            value=json.loads(next(m.content for m in reversed(messages) if isinstance(m,ToolMessage)))
            self.assertTrue(value['results'])
            self.assertEqual(value['results'][0]['path'],'docs/rules.md')
            self.assertIn('不能改变战技点',value['results'][0]['excerpt'])
            return AIMessage(content='已查到非法参数规则；本次仅调查，尚未修改。')
        result=self.task.execute('query',scope['scope_sha256'],model=ScriptModel([first,finish]))
        self.assertEqual(result['state'],'completed')
        events=(self.task._batch('query')/'graph/events.jsonl').read_text(encoding='utf-8')
        self.assertIn('search_knowledge',events)

    def test_off_baseline_has_no_new_tools_or_document_material(self):
        off=DevelopmentTask.create(self.source,self.root/'off-task','只调查代码',knowledge_mode='off')
        self.document();off.knowledge=self.task.knowledge
        scope=off.prepare('off',self.grant)
        preview=json.loads((off._batch('off')/'outbound-preview.json').read_text(encoding='utf-8'))
        self.assertNotIn('knowledge',preview)
        self.assertNotIn('search_knowledge',[t['name'] for t in preview['tools']])

    def test_web_import_confirm_preview_search_and_delete_are_local(self):
        with TestClient(create_app(self.root/'web'),base_url='http://127.0.0.1:18790') as client:
            created=client.post('/api/development/tasks',json={'project':str(self.source),'request':'调查资源参数'}).json()
            prefix='/api/development/tasks/'+created['task_id']
            sources=client.get(prefix+'/knowledge-sources')
            self.assertEqual(sources.status_code,200,sources.text)
            self.assertIn('docs/rules.md',[s['path'] for s in sources.json()['sources']])
            preview=client.get(prefix+'/knowledge-source',params={'path':'docs/rules.md'})
            self.assertEqual(preview.status_code,200,preview.text)
            saved=client.post(prefix+'/knowledge',json={'action':'import','path':'docs/rules.md','headings':['非法参数']})
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(saved.json()['status'],'pending')
            identity=saved.json()['id']
            empty=client.post(prefix+'/knowledge-search',json={'query':'资源参数'}).json()['results']
            self.assertEqual(empty,[])
            self.assertEqual(client.post(prefix+'/knowledge',json={'action':'status','id':identity,'status':'confirmed'}).status_code,200)
            hits=client.post(prefix+'/knowledge-search',json={'query':'资源参数'}).json()['results']
            self.assertEqual(hits[0]['path'],'docs/rules.md')
            self.assertEqual(client.post(prefix+'/knowledge',json={'action':'delete','id':identity}).status_code,200)
            self.assertEqual(client.get(prefix+'/knowledge').json()['documents'],[])
            self.assertEqual(client.post(prefix+'/knowledge',json={'action':'import','path':'../secret.md'}).status_code,422)

    def test_long_chinese_knowledge_can_be_read_to_the_end_with_bounded_valid_json(self):
        body='# 长规则\n'+('中文规则约束。'*190)+'结尾独有的重要校验\n'
        (self.source/'docs/long.md').write_text(body,encoding='utf-8')
        git(self.source,'add','docs/long.md');git(self.source,'commit','-qm','long rule')
        task=DevelopmentTask.create(self.source,self.root/'long-task','核对长规则')
        item=task.knowledge.import_file(task.workspace,'docs/long.md')
        task.knowledge.set_status(task.workspace.metadata['project'],item['id'],'confirmed')
        chunk=item['chunks'][0];parts=[]
        steps=[call('search_knowledge',{'query':'中文规则'},'search')]
        def receive_search(messages):
            value=json.loads(next(m.content for m in reversed(messages) if isinstance(m,ToolMessage)))
            self.assertEqual(value['results'][0]['id'],chunk['id'])
            return call('read_knowledge',{'chunk_id':chunk['id']},'read-0')
        steps.append(receive_search)
        for offset in range(0,len(chunk['text']),500):
            def receive_page(messages,offset=offset):
                text=next(m.content for m in reversed(messages) if isinstance(m,ToolMessage))
                self.assertLessEqual(len(text.encode('utf-8')),5500)
                page=json.loads(text);self.assertEqual(page['start_char'],offset)
                parts.append(page['text'])
                if page['next_char'] is not None:
                    return call('read_knowledge',{'chunk_id':chunk['id'],'start_char':page['next_char']},'read-'+str(page['next_char']))
                self.assertEqual(''.join(parts),chunk['text'])
                self.assertIn('结尾独有的重要校验',''.join(parts))
                return AIMessage(content='已完整读取长规则，尚未修改。')
            steps.append(receive_page)
        scope=task.prepare('long',{**self.grant,'max_calls':10})
        self.assertEqual(task.execute('long',scope['scope_sha256'],model=ScriptModel(steps))['state'],'completed')


if __name__=='__main__':unittest.main()
