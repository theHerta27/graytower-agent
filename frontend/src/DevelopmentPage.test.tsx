import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import DevelopmentPage from './DevelopmentPage';

afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
const task={task_id:'a'.repeat(32),request:'修复我刚发现的问题',project:'D:/my-game',project_name:'my-game',short_version:'abc12345',
  changed_files:[],files:[],patch:'',checks:[],validation:'尚未验证',model_state:'not_started',workflow_state:'candidate',busy:false,
  adoption:null,runs:[],tool_events:[],model_summary:'',tree_hash:'b'.repeat(64)};
function mock(current:unknown=task,route?:(url:string,init?:RequestInit)=>unknown){
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);
    const routed=route?.(url,init);if(routed!==undefined)return new Response(JSON.stringify(routed));
    if(url.endsWith('/status'))return new Response(JSON.stringify({default_project:'D:/my-game',key_configured:true,runtime_available:true,checks:[{value:'effects',label:'伤害、护盾与边界'}]}));
    if(url.endsWith('/tasks')&&!init?.method)return new Response(JSON.stringify({tasks:[]}));
    if(url.endsWith('/prepare'))return new Response(JSON.stringify({run_id:'user-1',scope_sha256:'c'.repeat(64),file_count:49,grant:{max_calls:18,cost_cap_usd:'0.95'}}));
    return new Response(JSON.stringify(current));
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

async function createTask(){
  await screen.findByDisplayValue('D:/my-game');
  fireEvent.change(screen.getByLabelText('这次想解决什么问题？'),{target:{value:task.request}});
  fireEvent.click(screen.getByRole('button',{name:'创建隔离候选'}));
  await screen.findByRole('button',{name:'让 AI 处理这个需求'});
}

it('shows the saved question and resumes the original run with the user answer',async()=>{
  const fetcher=mock({...task,model_state:'waiting_user',resumable_run:{run_id:'saved-run',scope_sha256:'saved-scope',status:'waiting_user',question:'护盾耗尽时需要清除哪个效果？'}},
    url=>url.endsWith('/resume')?{...task,model_state:'completed',model_summary:'已经根据回复完成修改'}:undefined);
  render(<DevelopmentPage/>);await createTask();
  expect(screen.getByText('护盾耗尽时需要清除哪个效果？')).toBeTruthy();
  expect(screen.getByRole('button',{name:'让 AI 处理这个需求'}).hasAttribute('disabled')).toBe(true);
  const resume=screen.getByRole('button',{name:'回复并继续'});
  expect(resume.hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByLabelText('回复这个问题'),{target:{value:'只清除当前护盾效果。'}});
  fireEvent.click(resume);
  await screen.findByText('已经根据回复完成修改');
  const sent=fetcher.mock.calls.find(([url])=>String(url).endsWith('/resume'));
  expect(JSON.parse(String(sent?.[1]?.body))).toEqual({run_id:'saved-run',scope_sha256:'saved-scope',answer:'只清除当前护盾效果。'});
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/prepare'))).toBe(false);
});

it('continues a saved check wait without asking for a new grant or an answer',async()=>{
  const fetcher=mock({...task,model_state:'waiting_checks',resumable_run:{run_id:'check-run',scope_sha256:'check-scope',status:'waiting_checks',note:'真实检查尚未结束。'}},
    url=>url.endsWith('/resume')?{...task,model_state:'completed'}:undefined);
  render(<DevelopmentPage/>);await createTask();
  expect(screen.getByText('真实检查尚未结束。')).toBeTruthy();
  expect(screen.getByText(/原批次的剩余额度/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'继续这次任务'}));
  await waitFor(()=>expect(screen.getByText('AI 已结束，请审阅结果')).toBeTruthy());
  const sent=fetcher.mock.calls.find(([url])=>String(url).endsWith('/resume'));
  expect(JSON.parse(String(sent?.[1]?.body))).toEqual({run_id:'check-run',scope_sha256:'check-scope'});
  expect(screen.queryByRole('checkbox',{name:/我同意/})).toBeNull();
});

it('loads project memory only on demand and confirms a pending proposal',async()=>{
  let memories=[{id:'memory-1',content:'护盾规则以 Python 为准。',source:'agent:saved-run',version:'baseline-full',kind:'constraint',status:'pending'}];
  const fetcher=mock(task,(url,init)=>{
    if(!url.endsWith('/memories'))return;
    if(init?.method==='POST')memories=memories.map(m=>({...m,status:'confirmed'}));
    return {memories,version:'baseline-full'};
  });
  render(<DevelopmentPage/>);await createTask();
  expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/memories'))).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'项目记忆'}));
  await screen.findByText('护盾规则以 Python 为准。');
  expect(screen.getByText('待确认')).toBeTruthy();
  expect(screen.getByText(/agent:saved-run/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'确认这条记忆'}));
  await screen.findByText('已确认');
  const sent=fetcher.mock.calls.find(([url,init])=>String(url).endsWith('/memories')&&init?.method==='POST');
  expect(JSON.parse(String(sent?.[1]?.body))).toEqual({action:'update',id:'memory-1',status:'confirmed'});
  expect(screen.queryByRole('button',{name:'确认这条记忆'})).toBeNull();
});

it('adds a versioned memory, edits its content and removes it without calling a model',async()=>{
  let memories:{id:string;content:string;source:string;version:string;kind:string;status:string}[]=[];
  const fetcher=mock(task,(url,init)=>{
    if(!url.endsWith('/memories'))return;
    if(init?.method==='POST'){
      const body=JSON.parse(String(init.body));
      if(body.action==='add')memories=[{id:'manual-1',content:body.content,source:'user',version:body.version,kind:body.kind,status:'confirmed'}];
      if(body.action==='update')memories=memories.map(m=>({...m,...body}));
      if(body.action==='delete')memories=[];
    }
    return {memories,version:'baseline-full'};
  });
  render(<DevelopmentPage/>);await createTask();
  fireEvent.click(screen.getByRole('button',{name:'项目记忆'}));
  await screen.findByText('还没有项目记忆。');
  fireEvent.change(screen.getByLabelText('新增记忆内容'),{target:{value:'不要修改可信测试。'}});
  fireEvent.click(screen.getByRole('button',{name:'确认并添加记忆'}));
  await screen.findByText('不要修改可信测试。');
  let writes=fetcher.mock.calls.filter(([url,init])=>String(url).endsWith('/memories')&&init?.method==='POST');
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({action:'add',content:'不要修改可信测试。',kind:'constraint',version:'baseline-full'});
  fireEvent.click(screen.getByRole('button',{name:'修改记忆'}));
  fireEvent.change(screen.getByLabelText('修改记忆内容'),{target:{value:'可信测试只能阅读。'}});
  fireEvent.click(screen.getByLabelText('修改为跨版本约定'));
  fireEvent.click(screen.getByRole('button',{name:'保存记忆修改'}));
  await screen.findByText('可信测试只能阅读。');
  expect(screen.queryByText('不要修改可信测试。')).toBeNull();
  writes=fetcher.mock.calls.filter(([url,init])=>String(url).endsWith('/memories')&&init?.method==='POST');
  expect(JSON.parse(String(writes[1][1]?.body))).toEqual({action:'update',id:'manual-1',content:'可信测试只能阅读。',kind:'constraint',version:'*'});
  const card=screen.getByRole('article');
  expect(within(card).getByText(/跨版本/)).toBeTruthy();
  fireEvent.click(within(card).getByRole('button',{name:'删除记忆'}));
  await screen.findByText('还没有项目记忆。');
  expect(fetcher.mock.calls.some(([url])=>/\/(run|resume|prepare)$/.test(String(url)))).toBe(false);
});

it('offers backend-supported lessons as cross-version memories',async()=>{
  let added=false;
  const fetcher=mock(task,(url,init)=>{
    if(!url.endsWith('/memories'))return;
    if(init?.method==='POST')added=true;
    return {memories:added?[{id:'lesson-1',content:'失败检查要保留原始日志。',source:'user',version:'*',kind:'lesson',status:'confirmed'}]:[],version:'baseline-full'};
  });
  render(<DevelopmentPage/>);await createTask();
  fireEvent.click(screen.getByRole('button',{name:'项目记忆'}));
  await screen.findByText('还没有项目记忆。');
  fireEvent.change(screen.getByLabelText('新增记忆内容'),{target:{value:'失败检查要保留原始日志。'}});
  expect(within(screen.getByLabelText('记忆类型')).getByRole('option',{name:'经验记录'})).toBeTruthy();
  fireEvent.change(screen.getByLabelText('记忆类型'),{target:{value:'lesson'}});
  fireEvent.click(screen.getByLabelText('跨版本约定'));
  fireEvent.click(screen.getByRole('button',{name:'确认并添加记忆'}));
  await screen.findByText('失败检查要保留原始日志。');
  const sent=fetcher.mock.calls.find(([url,init])=>String(url).endsWith('/memories')&&init?.method==='POST');
  expect(JSON.parse(String(sent?.[1]?.body))).toEqual({action:'add',content:'失败检查要保留原始日志。',kind:'lesson',version:'*'});
});

it('shows interrupted source changes and visible model preflight failure',async()=>{
  mock({...task,candidate_state:'采用中断：原项目可能已部分写入，请继续采用或恢复。',
    adoption:{operation_id:'op',state:'prepared',note:'采用中断：原项目可能已部分写入，请继续采用或恢复。'},
    runs:[{run_id:'x',state:'not_started',budget:null,error_message:'材料已变化，请重新准备。'}]});
  render(<DevelopmentPage/>);await screen.findByDisplayValue('D:/my-game');
  fireEvent.change(screen.getByLabelText('这次想解决什么问题？'),{target:{value:task.request}});
  fireEvent.click(screen.getByRole('button',{name:'创建隔离候选'}));
  await screen.findByText(/原项目可能已部分写入/);
  expect(screen.queryByText('原项目尚未改动')).toBeNull();
  expect(screen.getByText('材料已变化，请重新准备。')).toBeTruthy();
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
