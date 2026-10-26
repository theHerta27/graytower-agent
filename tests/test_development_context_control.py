"""Lossless source cursors and honest, protocol-complete bounded context."""
import json
import unittest
from langchain_core.messages import AIMessage,HumanMessage,ToolMessage
import test_development_checks as fixtures
from agent_workbench.development.context import bounded_messages,tool_text
from agent_workbench.development.tools import DevelopmentTools


class ContextControlTests(unittest.TestCase):
    def setUp(self):
        fixtures.DevelopmentCheckTests.setUp(self)
        self.tools=DevelopmentTools(self.workspace,self.jobs)
        self.path='game-core/combat_core/v2/effects.py'

    def decoded(self,text):
        try:return json.loads(text)
        except json.JSONDecodeError:self.fail('tool context was cut into invalid JSON')

    def read_all(self,text):
        old=self.workspace.read_file(self.path)
        self.workspace.write_file('long-source',self.path,old['sha256'],text)
        line,column=1,0;parts=[];cursors=set()
        for _ in range(200):
            self.assertNotIn((line,column),cursors);cursors.add((line,column))
            page=self.tools.dispatch('read_file',{'path':self.path,'start_line':line,'start_column':column,'max_lines':200},'read')
            wire=tool_text(page)
            self.assertLessEqual(len(wire.encode('utf-8')),5500)
            self.assertEqual(self.decoded(wire)['text'],page['text'])
            self.assertIn('next_line',page,'source page has no exact continuation cursor')
            parts.append(page['text'])
            if page['next_line'] is None:break
            line,column=page['next_line'],page['next_column']
        else:self.fail('source cursor did not terminate')
        self.assertEqual(''.join(parts),text)
        self.assertEqual((self.root/'source'/self.path).read_text(),'VALUE = 1\n')

    def test_chinese_source_pages_can_reconstruct_every_line(self):
        self.read_all(''.join(f'line_{i} = "'+('护盾规则'*30)+'"\n' for i in range(90)))

    def test_one_long_unicode_line_can_resume_inside_the_line(self):
        self.read_all('RULE = "'+('盾🛡规则'*2500)+'"\nNEXT = 1\n')

    def test_oversize_generic_tool_results_stay_valid_json(self):
        for value in ({'path':self.path,'text':'很长内容'*5000,'patch':'x'*15000},
                      [{'path':self.path,'line':n,'text':'盾'*400} for n in range(100)]):
            wire=tool_text(value)
            self.assertLessEqual(len(wire.encode('utf-8')),6000)
            self.decoded(wire)

    def test_compaction_keeps_source_references_and_valid_tool_bodies(self):
        history=[HumanMessage(content='调查规则')]
        for index in range(20):
            identity='read-'+str(index)
            args={'path':self.path,'start_line':index*10+1,'max_lines':10}
            history.extend([AIMessage(content='',tool_calls=[{'name':'read_file','args':args,'id':identity}]),
                ToolMessage(content=json.dumps({'path':self.path,'sha256':'a'*64,'start_line':index*10+1,
                    'end_line':index*10+10,'text':'规则内容'*300},ensure_ascii=False),tool_call_id=identity,name='read_file')])
        messages=bounded_messages(history,instructions='尊重原项目权限',memories=[],max_bytes=14000)
        self.assertLessEqual(len(json.dumps([m.model_dump() for m in messages],ensure_ascii=False).encode()),14000)
        self.assertIn('历史工具来源',messages[0].content)
        self.assertIn(self.path,messages[0].content)
        for message in messages:
            if isinstance(message,ToolMessage):self.decoded(message.content)
        self.assertEqual(messages[-1].tool_call_id,'read-19')

    def test_a_large_latest_batch_is_omitted_explicitly_not_cut_into_invalid_json(self):
        calls=[{'name':'read_file','args':{'path':self.path},'id':'read-'+str(i)} for i in range(8)]
        history=[HumanMessage(content='核对规则'),AIMessage(content='',tool_calls=calls)]
        history += [ToolMessage(content=json.dumps({'path':self.path,'text':'规则'*1000},ensure_ascii=False),
                    tool_call_id=call['id'],name='read_file') for call in calls]
        messages=bounded_messages(history,instructions='尊重权限',memories=[],max_bytes=14000)
        tools=[m for m in messages if isinstance(m,ToolMessage)]
        self.assertEqual([m.tool_call_id for m in tools],[c['id'] for c in calls])
        values=[self.decoded(m.content) for m in tools]
        self.assertTrue(any(v.get('context_omitted') for v in values))

    def test_invalid_tool_argument_cannot_poison_later_history_compaction(self):
        bad={'name':'read_file','args':{'path':[]},'id':'bad'}
        good={'name':'read_file','args':{'path':self.path},'id':'good'}
        history=[HumanMessage(content='核对规则'),AIMessage(content='',tool_calls=[bad]),
            ToolMessage(content='{"error":"invalid argument type: path"}',tool_call_id='bad',name='read_file'),
            AIMessage(content='',tool_calls=[good]),ToolMessage(content=json.dumps({'path':self.path,'text':'x'*4500}),tool_call_id='good',name='read_file')]
        try:messages=bounded_messages(history,instructions='尊重权限',memories=[],max_bytes=4000)
        except TypeError:self.fail('a rejected tool argument poisoned compaction')
        self.assertIn('历史工具来源',messages[0].content)
        self.assertEqual(messages[-1].tool_call_id,'good')

    def test_knowledge_history_keeps_distinct_chunk_identities_and_character_pages(self):
        history=[HumanMessage(content='调查资料')]
        identities=['1'*64,'2'*64]
        for index,identity in enumerate(identities):
            call={'name':'read_knowledge','args':{'chunk_id':identity,'start_char':500},'id':'knowledge-'+str(index)}
            value={'id':identity,'path':f'docs/rules-{index}.md','version':'b'*40,
                   'start_line':11,'end_line':90,'start_char':500,'next_char':1000,'total_chars':1200,'text':'规则'*200}
            history += [AIMessage(content='',tool_calls=[call]),ToolMessage(content=json.dumps(value,ensure_ascii=False),tool_call_id=call['id'],name='read_knowledge')]
        call={'name':'read_file','args':{'path':self.path},'id':'latest'}
        history += [AIMessage(content='',tool_calls=[call]),ToolMessage(content=json.dumps({'text':'x'*4500}),tool_call_id='latest',name='read_file')]
        messages=bounded_messages(history,instructions='尊重权限',memories=[],max_bytes=4000)
        refs=json.loads(messages[0].content.split('历史工具来源',1)[1].split('\n',1)[1])
        self.assertEqual({ref.get('chunk_id') for ref in refs},set(identities))
        for index,identity in enumerate(identities):
            ref=next(ref for ref in refs if ref['chunk_id']==identity)
            self.assertEqual(ref['path'],f'docs/rules-{index}.md')
            self.assertEqual(ref['version'],'b'*40)
            self.assertEqual((ref['start_char'],ref['next_char']),(500,1000))

    def test_omitted_knowledge_body_retains_a_usable_continuation_cursor(self):
        identity='3'*64
        call={'name':'read_knowledge','args':{'chunk_id':identity},'id':'knowledge'}
        value={'id':identity,'document_id':'d'*64,'path':'docs/rules.md','version':'b'*40,
               'start_line':11,'end_line':90,'start_char':500,'next_char':1000,'total_chars':1200,'text':'规则'*3000}
        history=[HumanMessage(content='调查资料'),AIMessage(content='',tool_calls=[call]),
                 ToolMessage(content=json.dumps(value,ensure_ascii=False),tool_call_id='knowledge',name='read_knowledge')]
        result=json.loads(bounded_messages(history,instructions='尊重权限',memories=[],max_bytes=4000)[-1].content)
        self.assertTrue(result['context_omitted'])
        self.assertIn('id',result)
        self.assertEqual((result['id'],result['version']),(identity,'b'*40))
        self.assertEqual((result['start_char'],result['next_char']),(500,1000))


if __name__=='__main__':unittest.main()
