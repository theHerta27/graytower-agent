import {useCallback,useEffect,useRef,useState} from 'react';
import './development.css';

type Check={job_id:string;check_set:string;status:string;matches_current_candidate:boolean;matches_current_definition:boolean;note:string;error?:string;
  result:null|{verdict:string;tests:{name:string;status:string}[];log:string}};
type Task={task_id:string;request:string;project:string;project_name:string;short_version:string;tree_hash:string;changed_files:string[];patch:string;
  files:{path:string;editable:boolean}[];checks:Check[];validation:string;workflow_state:string;model_state:string;busy:boolean;
  candidate_state:string;model_error?:string;adoption:null|{operation_id:string;state:string;note:string;matches_current_candidate:boolean};model_summary:string;tool_events:{tool:string;success:boolean}[];
  runs:{run_id:string;state:string;error_message?:string;budget:null|{reserved:number;known_cost_usd:string}}[];
  resumable_run?:{run_id:string;scope_sha256:string;status:'waiting_user'|'waiting_checks'|'interrupted';question?:string;note?:string}|null};
type Scope={run_id:string;scope_sha256:string;file_count:number;grant:{max_calls:number;cost_cap_usd:string}};
type FileView={path:string;sha256:string;text:string;before:string;editable:boolean};
type Settings={default_project:string;key_configured:boolean;runtime_available:boolean;engine?:string;framework?:string;checks:{value:string;label:string}[]};
type Memory={id:string;content:string;source:string;version:string;kind:string;status:string};
type Memories={memories:Memory[];version:string};
const memoryKinds=[['constraint','项目约定'],['decision','设计决定'],['lesson','经验记录']];
const root='/api/development';
async function api<T>(path:string,body?:unknown):Promise<T>{
  const response=await fetch(root+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await response.json();if(!response.ok)throw new Error(typeof value.error==='string'?value.error:'操作没有完成，请刷新查看原因。');return value;
}
const modelLabel=(state:string)=>({not_started:'尚未调用真实模型',prepared:'材料已准备，尚未调用模型',running:'AI 正在处理',completed:'AI 已结束，请审阅结果',failed:'AI 未完成，请查看原因',unknown:'执行结果待核对',interrupted:'运行中断，未自动重试',waiting_user:'等待你的回复',waiting_checks:'等待真实检查结果',partial:'已保存阶段结果，请审阅'})[state]||state;
const tools:Record<string,string>={project_status:'查看项目与候选',read_file:'阅读源码或规则',search_code:'检索相关代码',write_file:'修改隔离候选',replace_text:'精确替换候选片段',propose_memory:'提出待确认的项目记忆',start_check:'开始真实检查',read_check:'读取检查结果',start_diagnostic:'调查实际行为'};
const memoryStatus=(status:string)=>({pending:'待确认',confirmed:'已确认'})[status]||status;

export default function DevelopmentPage(){
  const [settings,setSettings]=useState<Settings|null>(null),[project,setProject]=useState(''),[request,setRequest]=useState('');
  const [list,setList]=useState<{task_id:string;request:string;project:string}[]>([]),[task,setTask]=useState<Task|null>(null);
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[pending,setPending]=useState(false),[tab,setTab]=useState('changes');
  const [file,setFile]=useState<FileView|null>(null),[draft,setDraft]=useState(''),[editing,setEditing]=useState(false),[checkSet,setCheckSet]=useState('effects');
  const [scope,setScope]=useState<Scope|null>(null),[acceptData,setAcceptData]=useState(false),[acceptCost,setAcceptCost]=useState(false),[adopting,setAdopting]=useState(false);
  const [answer,setAnswer]=useState(''),[memoryData,setMemoryData]=useState<Memories|null>(null),[memoryLoading,setMemoryLoading]=useState(false);
  const [memoryContent,setMemoryContent]=useState(''),[memoryKind,setMemoryKind]=useState('constraint'),[crossVersion,setCrossVersion]=useState(false);
  const [memoryEdit,setMemoryEdit]=useState<Memory|null>(null);
  const selected=useRef(''),saveRequest=useRef<null|{operation_id:string;path:string;expected_sha256:string;content:string}>(null);
  const refreshList=useCallback(async()=>setList((await api<{tasks:typeof list}>('/tasks')).tasks),[]);
  const load=useCallback(async(id:string)=>{const value=await api<Task>('/tasks/'+id);if(selected.current===id)setTask(value);return value;},[]);
  useEffect(()=>{Promise.all([api<Settings>('/status'),refreshList()]).then(([s])=>{setSettings(s);setProject(s.default_project);setCheckSet(s.checks[0]?.value||'effects');}).catch(e=>setError(String(e.message)));},[refreshList]);
  useEffect(()=>{
    if(!task||(!task.busy&&!task.checks.some(c=>c.status==='running')))return;
    const id=task.task_id;const timer=setInterval(()=>load(id).catch(e=>setError(e.message)),2000);return()=>clearInterval(timer);
  },[task,load]);
  const taskId=task?.task_id;
  useEffect(()=>{setAnswer('');},[taskId,task?.resumable_run?.run_id]);
  useEffect(()=>{
    setMemoryContent('');setMemoryKind('constraint');setCrossVersion(false);setMemoryEdit(null);
  },[taskId]);
  useEffect(()=>{
    if(tab!=='memories'||!taskId)return;
    let active=true;setMemoryData(null);setMemoryLoading(true);
    api<Memories>('/tasks/'+taskId+'/memories').then(value=>{if(active)setMemoryData(value);})
      .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setMemoryLoading(false);});
    return()=>{active=false;};
  },[tab,taskId]);
  async function perform(action:()=>Promise<void>){setPending(true);setError('');setNotice('');try{await action();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setPending(false);}}
  const blocked=pending||!!task?.busy||task?.workflow_state==='discarded';
  async function open(id:string){selected.current=id;setFile(null);setScope(null);setEditing(false);saveRequest.current=null;await load(id);}
  async function action(name:string,value:unknown){if(!task)return;const result=await api<Task>('/tasks/'+task.task_id+'/'+name,value);setTask(result);}
  async function readFile(name:string){if(!task||!name){setFile(null);return;}const result=await api<FileView>('/tasks/'+task.task_id+'/file?path='+encodeURIComponent(name));setFile(result);setDraft(result.text);setEditing(false);saveRequest.current=null;}
  async function updateMemory(body:unknown){
    if(!task)return;
    await api('/tasks/'+task.task_id+'/memories',body);
    setMemoryData(await api<Memories>('/tasks/'+task.task_id+'/memories'));
    setScope(null);
  }
  const canAdopt=!!task&&task.changed_files.length>0&&task.checks.some(c=>c.matches_current_candidate&&c.matches_current_definition&&c.result?.verdict==='PASS')
    &&!task.checks.some(c=>c.matches_current_candidate&&c.matches_current_definition&&c.result?.verdict==='FAIL');

  return <div className="dev-workbench">
    <header className="dev-header"><div><span className="dev-mark" aria-hidden="true">灰</span><strong>灰塔 · 研发助手</strong><span className="dev-caption">把一次修改，交付清楚。</span></div><span className="dev-local">本机工作台 · 默认不调用模型</span></header>
    <div className="dev-layout"><aside className="dev-sidebar">
      <h1>开始一次修改</h1><p className="dev-muted">选好游戏项目，说清遇到的问题。系统先建立独立候选。</p>
      <form onSubmit={e=>{e.preventDefault();perform(async()=>{const value=await api<Task>('/tasks',{project,request});selected.current=value.task_id;setTask(value);setFile(null);setScope(null);await refreshList();});}}>
        <label>游戏项目目录<input value={project} onChange={e=>setProject(e.target.value)} required placeholder="例如 D:\Desktop\graytower-game"/></label>
        <label>这次想解决什么问题？<textarea value={request} onChange={e=>setRequest(e.target.value)} required maxLength={8000} rows={6} placeholder="描述你观察到的行为，以及希望它怎样变化。可以先用普通中文说明。"/></label>
        <button className="dev-primary" disabled={pending||!request.trim()||!project.trim()}>创建隔离候选</button>
      </form>
      <div className="dev-project-note">从已提交的版本开始。开发项目有未提交改动时，会先提示你处理。</div>
      <h2>最近的需求</h2>{!list.length?<p className="dev-muted">还没有需求。创建后会保存在这里。</p>:<div className="dev-task-list">{list.map(item=><button key={item.task_id} disabled={pending} className={task?.task_id===item.task_id?'selected':''} onClick={()=>perform(()=>open(item.task_id))}>{item.request}<small>{item.project.split(/[\\/]/).pop()}</small></button>)}</div>}
    </aside><main className="dev-main">
      {error&&<div className="dev-error" role="alert">{error}</div>}{notice&&<div className="dev-notice" role="status">{notice}</div>}
      {!task?<section className="dev-empty"><p className="dev-eyebrow">你的项目，你来决定采用什么。</p><h2>先把需求交给一个独立候选。</h2><p>AI可以阅读代码、提出修改并运行检查。你能看到真实差异和执行结果，再决定是否写回开发项目。</p><div className="dev-flow"><span>提出需求</span><b>→</b><span>审阅修改</span><b>→</b><span>检查结果</span><b>→</b><span>采用或放弃</span></div><p className="dev-muted">这里没有自动播放的历史演示。首次打开为空；浏览和创建候选不会产生模型费用。</p></section>:<>
        <section className="dev-task-heading"><div className="dev-version"><b>{task.project_name}</b><span>基于版本 {task.short_version}</span><button className="dev-link" disabled={pending} onClick={()=>perform(async()=>{await load(task.task_id);})}>刷新状态</button></div><h1>{task.request}</h1>
          <p className="dev-protection">{task.candidate_state||task.adoption?.note||'原项目尚未改动'}{task.workflow_state==='discarded'?' · 这份候选已放弃':''}</p>
          <div className="dev-toolbar"><button className="dev-primary" disabled={blocked||!!task.resumable_run||!settings?.key_configured||!settings?.runtime_available} onClick={()=>perform(async()=>{const value=await api<Scope>('/tasks/'+task.task_id+'/prepare',{});setScope(value);setAcceptCost(false);setAcceptData(false);})}>让 AI 处理这个需求</button><span className="dev-muted">{modelLabel(task.model_state)}</span></div>
          {(task.model_error||task.runs.at(-1)?.error_message)&&<p className="dev-error" role="status">{task.model_error||task.runs.at(-1)?.error_message}</p>}
          {settings&&(!settings.key_configured||!settings.runtime_available)&&<p className="dev-muted">{!settings.key_configured?'请先在本机配置 DeepSeek Key，再重新启动。 ':''}{!settings.runtime_available?'尚未安装任务运行所需的框架依赖，请按启动说明安装。':''}</p>}
        </section>
        {task.resumable_run&&<section className="dev-resume" aria-label="继续保存的任务"><h2>{modelLabel(task.resumable_run.status)}</h2>
          {task.resumable_run.note&&<p>{task.resumable_run.note}</p>}
          {task.resumable_run.question&&<p className="dev-question">{task.resumable_run.question}</p>}
          <p className="dev-muted">继续会沿用这次任务和原批次的剩余额度，可能再次调用模型；不会增加次数或费用上限。若要开始另一项工作，可以创建新的隔离候选。</p>
          <form onSubmit={e=>{e.preventDefault();const saved=task.resumable_run!;perform(async()=>{await action('resume',{run_id:saved.run_id,scope_sha256:saved.scope_sha256,...(saved.status==='waiting_user'?{answer:answer.trim()}:{})});setAnswer('');});}}>
            {task.resumable_run.status==='waiting_user'&&<label>回复这个问题<textarea value={answer} onChange={e=>setAnswer(e.target.value)} required maxLength={8000} rows={3}/></label>}
            <button className="dev-primary" disabled={blocked||!settings?.runtime_available||!settings?.key_configured||(task.resumable_run.status==='waiting_user'&&!answer.trim())}>{task.resumable_run.status==='waiting_user'?'回复并继续':'继续这次任务'}</button>
          </form>
        </section>}
        {scope&&!task.resumable_run&&<section className="dev-consent" aria-label="真实模型授权"><h2>开始前，确认发送范围与费用</h2><p>把需求、候选中允许的 {scope.file_count} 份游戏文本、命中的已确认项目记忆、相关工具结果和修改发送至 DeepSeek 官方接口。密钥和无关文件不会进入材料。</p><p>模型：deepseek-flash；本批最多 {scope.grant.max_calls} 次请求，费用上限 <strong>${scope.grant.cost_cap_usd}</strong>。这不是已经发生的费用；失败和未知请求同样占额度，不会自动续费。</p><a href={root+'/tasks/'+task.task_id+'/scope?run_id='+scope.run_id} target="_blank" rel="noreferrer">查看完整发送材料（含命中记忆）</a><label className="dev-checkbox"><input type="checkbox" checked={acceptData} onChange={e=>setAcceptData(e.target.checked)}/>我同意发送上述项目材料至 DeepSeek</label><label className="dev-checkbox"><input type="checkbox" checked={acceptCost} onChange={e=>setAcceptCost(e.target.checked)}/>我同意本批费用上限，并主动开始</label><div className="dev-toolbar"><button className="dev-primary" disabled={pending||!acceptData||!acceptCost} onClick={()=>perform(async()=>{await action('run',{run_id:scope.run_id,scope_sha256:scope.scope_sha256,accept_data:true,accept_cost:true});setScope(null);})}>同意并开始真实模型任务</button><button onClick={()=>setScope(null)}>暂不调用</button></div></section>}
        <nav className="dev-tabs" aria-label="任务内容">{[['changes','修改内容'],['checks','检查与交付'],['activity','处理过程'],['memories','项目记忆']].map(([value,label])=><button key={value} aria-pressed={tab===value} onClick={()=>setTab(value)}>{label}</button>)}</nav>
        {tab==='changes'&&<section className="dev-panel"><h2>查看修改前后</h2><p className="dev-muted">{task.changed_files.length?`这份候选修改了 ${task.changed_files.length} 个文件。`:'候选刚建立，还没有文件变化。可先让 AI 处理，也可手动调整候选。'}</p>
          <label>查看候选文件<select aria-label="查看候选文件" value={file?.path||''} onChange={e=>perform(()=>readFile(e.target.value))}><option value="">选择一个源码或配置文件</option>{task.files.filter(f=>f.editable).map(f=><option key={f.path} value={f.path}>{task.changed_files.includes(f.path)?'已修改 · ':''}{f.path}</option>)}</select></label>
          {file&&<><div className="dev-compare"><div><h3>原版本</h3><pre>{file.before||'原版本没有此文件。'}</pre></div><div><h3>当前候选</h3>{editing?<textarea aria-label="候选源码" className="dev-code-edit" value={draft} disabled={!!saveRequest.current} onChange={e=>setDraft(e.target.value)} rows={22}/>:<pre>{file.text||'文件为空。'}</pre>}</div></div><div className="dev-toolbar">{!editing?<button disabled={blocked} onClick={()=>setEditing(true)}>手动调整这份候选</button>:<button disabled={blocked} onClick={()=>perform(async()=>{if(!saveRequest.current)saveRequest.current={operation_id:crypto.randomUUID().replaceAll('-',''),path:file.path,expected_sha256:file.sha256,content:draft};await action('edit',saveRequest.current);saveRequest.current=null;await readFile(file.path);setNotice('候选已保存；原项目没有变化，需要重新检查。');})}>{saveRequest.current?'查询刚才的保存结果':'保存到候选'}</button>}</div></>}
          <details className="dev-diff" open={task.changed_files.length>0}><summary>完整源码 Diff</summary><pre>{task.patch||'尚无修改。'}</pre></details>
          {task.model_summary&&<div className="dev-explanation"><h3>AI 的修改说明</h3><p>{task.model_summary}</p><small>说明供审阅，检查结果以真实执行为准。</small></div>}
        </section>}
        {tab==='checks'&&<section className="dev-panel"><h2>用执行结果判断修改</h2><p>{task.validation}</p><div className="dev-toolbar"><select aria-label="检查范围" value={checkSet} onChange={e=>setCheckSet(e.target.value)}>{settings?.checks.map(c=><option key={c.value} value={c.value}>{c.label}</option>)}</select><button disabled={blocked} onClick={()=>perform(()=>action('check',{check_set:checkSet}))}>运行这项检查</button></div><p className="dev-muted">只运行本地检查，不调用模型。局部检查通过，只能说明这个范围；修改文件后旧结果会过时。</p>
          <div className="dev-checks">{!task.checks.length?<p className="dev-muted">还没有执行检查。</p>:task.checks.map(c=><details key={c.job_id}><summary><b>{settings?.checks.find(s=>s.value===c.check_set)?.label||c.check_set}</b><span>{!c.matches_current_candidate||!c.matches_current_definition?'旧版本结果':c.result?.verdict||({running:'检查中',unknown:'待核对',not_started:'尚未启动'} as Record<string,string>)[c.status]||c.status}</span></summary><p>{c.note}{c.error}</p>{c.result&&<><p>{c.result.tests?.filter(t=>t.status==='PASS').length||0} 项通过，共 {c.result.tests?.length||0} 项。</p><pre>{c.result.log}</pre></>}</details>)}</div>
          <div className="dev-delivery"><h2>决定怎样处理这份候选</h2><p>采用会写入 <strong>{task.project}</strong> 中对应文件，并保留恢复记录；不会自动提交 Git 或更新 Unity。</p><div className="dev-toolbar"><button className="dev-primary" disabled={blocked||!canAdopt||task.adoption?.state==='applied'} onClick={()=>setAdopting(true)}>采用到开发项目</button><button disabled={blocked||!task.adoption||task.adoption.state==='restored'} onClick={()=>perform(()=>action('restore',{operation_id:task.adoption!.operation_id}))}>恢复采用前的文件</button><button disabled={blocked||task.adoption?.state==='applied'} onClick={()=>perform(()=>action('discard',{tree_hash:task.tree_hash}))}>放弃这份候选</button><button disabled={pending} onClick={()=>perform(async()=>{await api('/tasks/'+task.task_id+'/export',{});setNotice('补丁与候选摘要已导出到任务目录的 exports 文件夹。');})}>导出补丁</button></div>{!canAdopt&&<p className="dev-muted">采用前需要当前候选至少有一项可信检查通过，且没有当前检查失败；没有修改时也无需采用。</p>}
          {adopting&&<div className="dev-confirm"><p>将以下 {task.changed_files.length} 个文件写入开发项目：</p><ul>{task.changed_files.map(f=><li key={f}>{f}</li>)}</ul><p>检查不能代替你对需求的判断。请确认已审阅 Diff。</p><button className="dev-primary" disabled={pending} onClick={()=>perform(async()=>{await action('apply',{tree_hash:task.tree_hash});setAdopting(false);})}>确认采用这份修改</button><button onClick={()=>setAdopting(false)}>返回审阅</button></div>}
          </div></section>}
        {tab==='activity'&&<section className="dev-panel"><h2>这次实际发生了什么</h2><p className="dev-muted">只显示本次实际收到的工具操作。没有模型调用时，不会播放虚构的思考过程。</p>{!task.tool_events.length?<p>还没有模型工具操作。</p>:<ol className="dev-events">{task.tool_events.map((event,index)=><li key={index}><span>{tools[event.tool]||event.tool}</span><b>{event.success?'已完成':'未成功，请查看结果'}</b></li>)}</ol>}{task.runs.map(r=><p key={r.run_id}>{modelLabel(r.state)}{r.budget?` · ${r.budget.reserved} 次请求，记录费用 $${r.budget.known_cost_usd}`:''}{r.error_message?' · '+r.error_message:''}</p>)}</section>}
        {tab==='memories'&&<section className="dev-panel"><h2>管理这个项目的记忆</h2>
          <p className="dev-muted">这里保存可供后续任务参考的项目约定和事实。每条都保留来源、适用版本与确认状态；AI 提出的内容先待确认，只有已确认且与当前版本、需求相关的记忆才会进入发送材料。任务进度另行保存，记忆不授予操作或费用权限。</p>
          <p className="dev-muted">查看、新增和修改记忆只操作本机记录，不调用模型。修改后，已准备的发送材料需要重新确认。</p>
          {memoryLoading?<p role="status">正在读取项目记忆…</p>:memoryData&&<>
            <form className="dev-memory-form" onSubmit={e=>{e.preventDefault();perform(async()=>{await updateMemory({action:'add',content:memoryContent.trim(),kind:memoryKind,version:crossVersion?'*':memoryData.version});setMemoryContent('');setNotice('记忆已由你确认并保存。');});}}>
              <h3>添加一条项目记忆</h3><label>新增记忆内容<textarea value={memoryContent} onChange={e=>setMemoryContent(e.target.value)} rows={3} required maxLength={2000}/></label>
              <label>记忆类型<select value={memoryKind} onChange={e=>setMemoryKind(e.target.value)}>{memoryKinds.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
              <label className="dev-checkbox"><input type="checkbox" checked={crossVersion} onChange={e=>setCrossVersion(e.target.checked)}/>跨版本约定</label>
              <p className="dev-memory-meta">适用版本：{crossVersion?'跨版本（*）':memoryData.version}</p>
              <button disabled={pending||!memoryContent.trim()} className="dev-primary">确认并添加记忆</button>
            </form>
            <div className="dev-toolbar"><button disabled={pending} onClick={()=>perform(async()=>{setMemoryData(await api<Memories>('/tasks/'+task.task_id+'/memories'));})}>刷新项目记忆</button><span className="dev-muted">共 {memoryData.memories.length} 条</span></div>
            {!memoryData.memories.length?<p>还没有项目记忆。</p>:<div className="dev-memories">{memoryData.memories.map(memory=><article key={memory.id} className="dev-memory">
              <div className="dev-memory-heading"><b>{memoryStatus(memory.status)}</b><span>{memoryKinds.find(([value])=>value===memory.kind)?.[1]||memory.kind}</span></div>
              <p className="dev-memory-meta">来源：{memory.source} · 适用版本：{memory.version==='*'?'跨版本（*）':memory.version}</p>
              {memoryEdit?.id===memory.id?<form onSubmit={e=>{e.preventDefault();perform(async()=>{await updateMemory({action:'update',id:memory.id,content:memoryEdit.content.trim(),kind:memoryEdit.kind,version:memoryEdit.version});setMemoryEdit(null);setNotice('记忆修改已保存。');});}}>
                <label>修改记忆内容<textarea value={memoryEdit.content} onChange={e=>setMemoryEdit({...memoryEdit,content:e.target.value})} required maxLength={2000} rows={3}/></label>
                <label>修改记忆类型<select value={memoryEdit.kind} onChange={e=>setMemoryEdit({...memoryEdit,kind:e.target.value})}>{!memoryKinds.some(([value])=>value===memoryEdit.kind)&&<option value={memoryEdit.kind}>{memoryEdit.kind}</option>}{memoryKinds.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
                <label className="dev-checkbox"><input type="checkbox" checked={memoryEdit.version==='*'} onChange={e=>setMemoryEdit({...memoryEdit,version:e.target.checked?'*':memoryData.version})}/>修改为跨版本约定</label>
                <p className="dev-memory-meta">修改后适用版本：{memoryEdit.version==='*'?'跨版本（*）':memoryEdit.version}</p>
                <div className="dev-toolbar"><button className="dev-primary" disabled={pending||!memoryEdit.content.trim()}>保存记忆修改</button><button type="button" disabled={pending} onClick={()=>setMemoryEdit(null)}>取消修改</button></div>
              </form>:<><p className="dev-memory-content">{memory.content}</p><div className="dev-toolbar">
                {memory.status!=='confirmed'&&<button disabled={pending} onClick={()=>perform(async()=>{await updateMemory({action:'update',id:memory.id,status:'confirmed'});setNotice('这条项目记忆已确认。');})}>确认这条记忆</button>}
                <button disabled={pending} onClick={()=>setMemoryEdit({...memory})}>修改记忆</button><button disabled={pending} onClick={()=>perform(async()=>{await updateMemory({action:'delete',id:memory.id});setNotice('项目记忆已删除。');})}>删除记忆</button>
              </div></>}
            </article>)}</div>}
          </>}
        </section>}
        <details className="dev-technical"><summary>项目和运行详情</summary><p>开发项目：{task.project}</p><p>候选版本：{task.tree_hash}</p><p>任务框架：{settings?.framework||'LangGraph + LangChain'}。单个研发助手按实际结果调查、修改和检查；暂停后从保存位置继续。</p><p>工作范围：灰塔 Python 游戏规则与配置。NPC、多 Agent 和 A2A 不在当前默认流程中。</p></details>
      </>}
    </main></div>
  </div>;
}
