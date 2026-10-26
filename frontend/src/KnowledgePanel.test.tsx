import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import KnowledgePanel from './KnowledgePanel';
import DevelopmentPage from './DevelopmentPage';

afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
const baseline='baseline-current';
const document={id:'doc-1',path:'docs/rules.md',title:'护盾规则',version:baseline,status:'pending',headings:['护盾耗尽'] as string[]|null,chunk_count:1};
function mock(initial:typeof document[]=[]){
  let documents=[...initial];
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);let data:unknown;
    if(url.endsWith('/knowledge-sources'))data={sources:[{path:'docs/rules.md'}]};
    else if(url.includes('/knowledge-source?'))data={path:'docs/rules.md',title:'护盾规则',version:baseline,sha256:'source-hash',sections:[
      {heading:'护盾耗尽',start_line:3,end_line:5,text:'护盾耗尽后清除当前护盾效果。'},
      {heading:'其他约定',start_line:7,end_line:9,text:'所有配置必须经过检查。'}]};
    else if(url.endsWith('/knowledge-search'))data={results:[{id:'chunk-1',document_id:'doc-1',path:'docs/rules.md',title:'护盾规则',heading:'护盾耗尽',text:'护盾耗尽后清除当前护盾效果。',version:baseline,start_line:3,end_line:5,score:1.25,reason:'匹配：护盾'}]};
    else if(url.endsWith('/knowledge')){
      if(init?.method==='POST'){
        const body=JSON.parse(String(init.body));
        if(body.action==='import')documents=[{...document,headings:body.headings}];
        if(body.action==='status')documents=documents.map(item=>({...item,status:body.status}));
        if(body.action==='delete')documents=[];
      }
      data={documents,version:baseline,mode:'lexical'};
    }else throw new Error('Unexpected route '+url);
    return new Response(JSON.stringify(data));
  });vi.stubGlobal('fetch',fetcher);return fetcher;
}

it('previews baseline sections and imports only selected headings as pending',async()=>{
  const fetcher=mock();const changed=vi.fn();render(<KnowledgePanel taskId="task-1" busy={false} onChanged={changed}/>);
  await screen.findByText('还没有导入研发资料。');
  fireEvent.change(screen.getByLabelText('选择基线资料'),{target:{value:'docs/rules.md'}});
  await screen.findByText('护盾耗尽后清除当前护盾效果。');
  const importButton=screen.getByRole('button',{name:'导入所选章节（待确认）'});
  expect(importButton.hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('checkbox',{name:/选择章节：护盾耗尽/}));
  fireEvent.click(importButton);
  const card=await screen.findByRole('article',{name:'护盾规则'});
  expect(within(card).getByText('待确认')).toBeTruthy();
  const writes=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({action:'import',path:'docs/rules.md',headings:['护盾耗尽']});
  expect(changed).toHaveBeenCalledTimes(1);
});

it('renders whole-document imports with null headings and keeps them available for confirmation',async()=>{
  mock([{...document,headings:null}]);render(<KnowledgePanel taskId="task-1" busy={false} onChanged={()=>{}}/>);
  const card=await screen.findByRole('article',{name:'护盾规则'});
  expect(within(card).getByText('整份文档')).toBeTruthy();
  expect(within(card).getByRole('button',{name:'确认资料'}).hasAttribute('disabled')).toBe(true);
});

it.each([
  [{heading:'',start_line:1,end_line:3,text:'没有标题的规则说明。'}],
  [{heading:'',start_line:1,end_line:2,text:'前言内容。'},{heading:'护盾耗尽',start_line:3,end_line:5,text:'护盾规则。'}],
])('offers whole-document import for untitled content without sending an empty heading (%#)',async(...sections)=>{
  const fetcher=mock();
  vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>String(input).includes('/knowledge-source?')
    ?new Response(JSON.stringify({path:'docs/rules.md',title:'护盾规则',version:baseline,sha256:'source-hash',sections}))
    :fetcher(input,init));
  render(<KnowledgePanel taskId="task-1" busy={false} onChanged={()=>{}}/>);
  await screen.findByText('还没有导入研发资料。');
  fireEvent.change(screen.getByLabelText('选择基线资料'),{target:{value:'docs/rules.md'}});
  await screen.findByText(sections[0].text);
  expect(screen.queryByRole('checkbox',{name:'选择章节：'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'导入整份文档（待确认）'}));
  const card=await screen.findByRole('article',{name:'护盾规则'});
  expect(within(card).getByText('整份文档')).toBeTruthy();
  expect(within(card).getByText('待确认')).toBeTruthy();
  const writes=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({action:'import',path:'docs/rules.md',headings:null});
});

it('retains section selections after a failed import and collapses them after a successful retry',async()=>{
  const fetcher=mock();let rejectImport=true;
  vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(init?.method==='POST'&&JSON.parse(String(init.body)).action==='import'&&rejectImport){
      rejectImport=false;return new Response(JSON.stringify({error:'章节暂时不能导入，请重试。'}),{status:400});
    }
    return fetcher(input,init);
  });
  render(<KnowledgePanel taskId="task-1" busy={false} onChanged={()=>{}}/>);
  await screen.findByText('还没有导入研发资料。');
  fireEvent.change(screen.getByLabelText('选择基线资料'),{target:{value:'docs/rules.md'}});
  const selected=await screen.findByRole('checkbox',{name:'选择章节：护盾耗尽'});
  fireEvent.click(selected);
  fireEvent.click(screen.getByRole('button',{name:'导入所选章节（待确认）'}));
  await screen.findByRole('alert');
  expect((screen.getByLabelText('选择基线资料') as HTMLSelectElement).value).toBe('docs/rules.md');
  expect((selected as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'导入所选章节（待确认）'}));
  const card=await screen.findByRole('article',{name:'护盾规则'});
  expect(within(card).getByText('待确认')).toBeTruthy();
  expect((screen.getByLabelText('选择基线资料') as HTMLSelectElement).value).toBe('');
  expect(screen.queryByRole('checkbox',{name:'选择章节：护盾耗尽'})).toBeNull();
  expect(screen.queryByRole('button',{name:'导入所选章节（待确认）'})).toBeNull();
});

it('requires explicit current-version applicability before confirmation, then allows deletion',async()=>{
  const fetcher=mock([document]);const changed=vi.fn();render(<KnowledgePanel taskId="task-1" busy={false} onChanged={changed}/>);
  let card=await screen.findByRole('article',{name:'护盾规则'});
  expect(within(card).getByRole('button',{name:'确认资料'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(within(card).getByRole('checkbox',{name:/我已核对所选章节适用于当前基线版本/}));
  fireEvent.click(within(card).getByRole('button',{name:'确认资料'}));
  await within(card).findByText('已确认');
  card=screen.getByRole('article',{name:'护盾规则'});
  fireEvent.click(within(card).getByRole('button',{name:'删除资料'}));
  await screen.findByText('还没有导入研发资料。');
  expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST').map(([,init])=>JSON.parse(String(init?.body)))).toEqual([
    {action:'status',id:'doc-1',status:'confirmed'},{action:'delete',id:'doc-1'}]);
  expect(changed).toHaveBeenCalledTimes(2);
});

it('searches locally and exposes source lines, version and chunk identity',async()=>{
  const fetcher=mock([{...document,status:'confirmed'}]);render(<KnowledgePanel taskId="task-1" busy={false} onChanged={()=>{}}/>);
  await screen.findByRole('article',{name:'护盾规则'});
  fireEvent.change(screen.getByLabelText('检索研发资料'),{target:{value:'护盾耗尽'}});
  fireEvent.click(screen.getByRole('button',{name:'本地试搜'}));
  const result=await screen.findByRole('article',{name:'检索结果：护盾规则 · 护盾耗尽'});
  expect(within(result).getByText('docs/rules.md:3–5')).toBeTruthy();
  expect(within(result).getByText('版本：baseline-current')).toBeTruthy();
  fireEvent.click(within(result).getByText('引用与匹配详情'));
  expect(within(result).getByText(/片段 ID：chunk-1/)).toBeTruthy();
  expect(within(result).getByText(/匹配：护盾/)).toBeTruthy();
  const writes=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');
  expect(writes).toHaveLength(1);
  expect(String(writes[0][0])).toBe('/api/development/tasks/task-1/knowledge-search');
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({query:'护盾耗尽'});
});

it('labels historical documents and disables mutations while the task is busy',async()=>{
  const fetcher=mock([{...document,version:'older-baseline',status:'confirmed'}]);
  render(<KnowledgePanel taskId="task-1" busy={true} onChanged={()=>{}}/>);
  const card=await screen.findByRole('article',{name:'护盾规则'});
  expect(within(card).getByText('旧版本 · 不参与检索')).toBeTruthy();
  expect(within(card).getByRole('button',{name:'删除资料'}).hasAttribute('disabled')).toBe(true);
  expect(within(card).queryByRole('button',{name:'确认资料'})).toBeNull();
  fireEvent.click(within(card).getByRole('button',{name:'删除资料'}));
  await waitFor(()=>expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0));
});

it('clears old search results after a document mutation',async()=>{
  mock([{...document,status:'confirmed'}]);render(<KnowledgePanel taskId="task-1" busy={false} onChanged={()=>{}}/>);
  const card=await screen.findByRole('article',{name:'护盾规则'});
  fireEvent.change(screen.getByLabelText('检索研发资料'),{target:{value:'护盾'}});
  fireEvent.click(screen.getByRole('button',{name:'本地试搜'}));
  await screen.findByRole('article',{name:'检索结果：护盾规则 · 护盾耗尽'});
  fireEvent.click(within(card).getByRole('button',{name:'取消确认'}));
  await within(card).findByText('待确认');
  expect(screen.queryByRole('article',{name:'检索结果：护盾规则 · 护盾耗尽'})).toBeNull();
});

it('loads the separate knowledge tab on demand and invalidates prepared scope after confirmation',async()=>{
  const knowledgeFetcher=mock([document]);
  const task={task_id:'task-1',request:'核对护盾处理',project:'D:/my-game',project_name:'my-game',short_version:'base',tree_hash:'tree',changed_files:[],files:[],patch:'',checks:[],validation:'尚未验证',workflow_state:'candidate',model_state:'not_started',busy:false,candidate_state:'',adoption:null,model_summary:'',tool_events:[],runs:[]};
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);
    if(url.includes('/knowledge'))return knowledgeFetcher(input,init);
    if(url.endsWith('/status'))return new Response(JSON.stringify({default_project:'D:/my-game',key_configured:true,runtime_available:true,checks:[]}));
    if(url.endsWith('/tasks')&&!init?.method)return new Response(JSON.stringify({tasks:[]}));
    if(url.endsWith('/prepare'))return new Response(JSON.stringify({run_id:'run-1',scope_sha256:'scope',file_count:4,knowledge_document_count:2,grant:{max_calls:18,cost_cap_usd:'0.95'}}));
    return new Response(JSON.stringify(task));
  });vi.stubGlobal('fetch',fetcher);
  render(<DevelopmentPage/>);
  await screen.findByDisplayValue('D:/my-game');
  fireEvent.change(screen.getByLabelText('这次想解决什么问题？'),{target:{value:'核对护盾处理'}});
  fireEvent.click(screen.getByRole('button',{name:'创建隔离候选'}));
  await screen.findByRole('button',{name:'让 AI 处理这个需求'});
  expect(knowledgeFetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'让 AI 处理这个需求'}));
  await screen.findByText(/2 份当前基线已确认的研发资料/);
  fireEvent.click(screen.getByRole('button',{name:'研发资料'}));
  const card=await screen.findByRole('article',{name:'护盾规则'});
  fireEvent.click(within(card).getByRole('checkbox',{name:/我已核对所选章节适用于当前基线版本/}));
  fireEvent.click(within(card).getByRole('button',{name:'确认资料'}));
  await within(card).findByText('已确认');
  expect(screen.queryByRole('region',{name:'真实模型授权'})).toBeNull();
  expect(fetcher.mock.calls.some(([url])=>/\/(run|resume)$/.test(String(url)))).toBe(false);
});

it('shows retrieved source metadata in the actual tool activity without invoking tools',async()=>{
  const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);
    if(url.endsWith('/status'))return new Response(JSON.stringify({default_project:'D:/my-game',key_configured:true,runtime_available:true,checks:[]}));
    if(url.endsWith('/tasks')&&!init?.method)return new Response(JSON.stringify({tasks:[]}));
    return new Response(JSON.stringify({task_id:'task-1',request:'核对护盾',project:'D:/my-game',project_name:'my-game',short_version:'base',tree_hash:'tree',changed_files:[],files:[],patch:'',checks:[],validation:'尚未验证',workflow_state:'candidate',model_state:'completed',busy:false,candidate_state:'',adoption:null,model_summary:'',runs:[],
      tool_events:[{tool:'search_knowledge',success:true,sources:[{id:'retrieved-chunk',path:'docs/rules.md',heading:'护盾耗尽',version:'baseline-current',start_line:3}]}]}));
  });vi.stubGlobal('fetch',fetcher);render(<DevelopmentPage/>);
  await screen.findByDisplayValue('D:/my-game');
  fireEvent.change(screen.getByLabelText('这次想解决什么问题？'),{target:{value:'核对护盾'}});
  fireEvent.click(screen.getByRole('button',{name:'创建隔离候选'}));
  fireEvent.click(await screen.findByRole('button',{name:'处理过程'}));
  expect(screen.getByText('检索已确认的研发资料')).toBeTruthy();
  expect(screen.getByText(/已读取来源/)).toBeTruthy();
  expect(screen.getByText(/docs\/rules.md:3 · 护盾耗尽 · 版本 baseline-current/)).toBeTruthy();
  expect(fetcher.mock.calls.some(([url])=>String(url).includes('/knowledge'))).toBe(false);
});
