"""Real LangChain/HTTP boundary for reasoning tools; no external model."""
import json
import tempfile
import unittest
from pathlib import Path
import httpx
from langchain_core.messages import HumanMessage,ToolMessage
from test_development_model import grant,response,KEY
from agent_workbench.development.model import ToolModel
from agent_workbench.development.tools import tool_specs
from agent_workbench.coding.responses_transport import CallBudget


class ReasoningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_reasoned_tools_preserve_reasoning_across_durable_replay_and_next_request(self):
        requests=[];caps=grant();caps['model_profile']='reasoned'
        def handler(req):
            payload=json.loads(req.content);requests.append(payload)
            if len(requests)==1:
                value=response(tool=True);value['choices'][0]['message']['reasoning_content']='opaque provider reasoning'
                return httpx.Response(200,json=value)
            self.assertEqual(payload['messages'][1]['reasoning_content'],'opaque provider reasoning')
            return httpx.Response(200,json=response(content='已经检查并交付。'))
        first=ToolModel(self.root,caps,tool_specs(),api_key=KEY,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        messages=[HumanMessage(content='先读再交付')]
        answer=first.complete(messages,'first')
        self.assertEqual(requests[0]['thinking'],{'type':'enabled'})
        self.assertEqual(requests[0]['reasoning_effort'],'high')
        self.assertNotIn('temperature',requests[0])
        replay=ToolModel(self.root,caps,tool_specs(),api_key=KEY,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertEqual(replay.complete(messages,'first'),answer)
        final=replay.complete(messages+[answer,ToolMessage(content='真实工具结果',tool_call_id='call-read')],'second',final_only=True)
        self.assertEqual(final.content,'已经检查并交付。')
        self.assertEqual(len(requests),2)
        self.assertEqual(requests[-1]['tool_choice'],'none')

    def test_larger_reasoning_output_is_explicitly_bounded_and_grant_cannot_change(self):
        caps=grant();caps.update(model_profile='reasoned',max_output_tokens=16384)
        self.assertEqual(CallBudget(self.root,caps).grant['max_output_tokens'],16384)
        changed={**caps,'max_output_tokens':4096}
        with self.assertRaises(ValueError):CallBudget(self.root,changed)
        legacy=grant();legacy['max_output_tokens']=16384
        with self.assertRaises(ValueError):CallBudget(self.root/'legacy',legacy)

    def test_review_catalog_has_execution_but_no_candidate_edit_tools(self):
        names={item['name'] for item in tool_specs('review')}
        self.assertIn('start_diagnostic',names)
        self.assertNotIn('write_file',names)
        self.assertNotIn('replace_text',names)


if __name__=='__main__':unittest.main()
