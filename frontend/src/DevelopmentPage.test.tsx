import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import DevelopmentPage from './DevelopmentPage';

afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
const task={task_id:'a'.repeat(32),request:'修复我刚发现的问题',project:'D:/my-game',project_name:'my-game',short_version:'abc12345',
  changed_files:[],files:[],patch:'',checks:[],validation:'尚未验证',model_state:'not_started',workflow_state:'candidate',busy:false,
  adoption:null,runs:[],tool_events:[],model_summary:'',tree_hash:'b'.repeat(64)};
function mock(){
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);
    if(url.endsWith('/status'))return new Response(JSON.stringify({default_project:'D:/my-game',key_configured:true,runtime_available:true,checks:[{value:'effects',label:'伤害、护盾与边界'}]}));
    if(url.endsWith('/tasks')&&!init?.method)return new Response(JSON.stringify({tasks:[]}));
    if(url.endsWith('/prepare'))return new Response(JSON.stringify({run_id:'user-1',scope_sha256:'c'.repeat(64),file_count:49,grant:{max_calls:18,cost_cap_usd:'0.95'}}));
    return new Response(JSON.stringify(task));
  });vi.stubGlobal('fetch',fetcher);return fetcher;
}

it('creates a fresh request and clearly labels candidate and real model not started',async()=>{
  const fetcher=mock();render(<DevelopmentPage/>);
  await screen.findByDisplayValue('D:/my-game');
  fireEvent.change(screen.getByLabelText('这次想解决什么问题？'),{target:{value:task.request}});
  fireEvent.click(screen.getByRole('button',{name:'创建隔离候选'}));
  await screen.findByText('原项目尚未改动');
  expect(screen.getByText('尚未调用真实模型')).toBeTruthy();
  expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST'&&String(init.body).includes(task.request))).toBe(true);
});

it('previews model scope but requires both human confirmations before sending',async()=>{
  const fetcher=mock();render(<DevelopmentPage/>);await screen.findByDisplayValue('D:/my-game');
  fireEvent.change(screen.getByLabelText('这次想解决什么问题？'),{target:{value:task.request}});
  fireEvent.click(screen.getByRole('button',{name:'创建隔离候选'}));
  fireEvent.click(await screen.findByRole('button',{name:'让 AI 处理这个需求'}));
  await screen.findByText(/0.95/);
  const start=screen.getByRole('button',{name:'同意并开始真实模型任务'});
  expect(start.hasAttribute('disabled')).toBe(true);
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/run'))).toBe(false);
  fireEvent.click(screen.getByLabelText(/我同意发送上述项目材料/));
  fireEvent.click(screen.getByLabelText(/我同意本批费用上限/));
  await waitFor(()=>expect(start.hasAttribute('disabled')).toBe(false));
});
