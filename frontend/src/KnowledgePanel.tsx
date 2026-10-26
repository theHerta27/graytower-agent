import {useEffect,useRef,useState} from 'react';

type Document={id:string;path:string;title:string;version:string;status:'pending'|'confirmed';headings:string[]|null;chunks?:unknown[];chunk_count?:number};
type Knowledge={documents:Document[];version:string;mode:'off'|'lexical'};
type Preview={path:string;title:string;version:string;sha256:string;sections:{heading:string;start_line:number;end_line:number;text:string}[]};
type Result={id:string;document_id:string;path:string;title:string;heading:string;text:string;version:string;start_line:number;end_line:number;score:number;reason:string};
async function api<T>(taskId:string,path:string,body?:unknown):Promise<T>{
  const response=await fetch('/api/development/tasks/'+encodeURIComponent(taskId)+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.error==='string'?value.error:'研发资料操作没有完成，请刷新后重试。');
  return value;
}

export default function KnowledgePanel({taskId,busy,onChanged}:{taskId:string;busy:boolean;onChanged:()=>void}){
  const [data,setData]=useState<Knowledge|null>(null),[sources,setSources]=useState<{path:string}[]>([]);
  const [source,setSource]=useState(''),[preview,setPreview]=useState<Preview|null>(null),[headings,setHeadings]=useState<string[]>([]);
  const [accepted,setAccepted]=useState<Record<string,boolean>>({}),[query,setQuery]=useState(''),[results,setResults]=useState<Result[]|null>(null);
  const [loading,setLoading]=useState(true),[previewLoading,setPreviewLoading]=useState(false),[pending,setPending]=useState(false),[searching,setSearching]=useState(false);
  const [error,setError]=useState(''),[notice,setNotice]=useState('');
  const generation=useRef(0),sourceGeneration=useRef(0),searchGeneration=useRef(0);
  useEffect(()=>{
    const current=++generation.current;sourceGeneration.current++;searchGeneration.current++;
    setData(null);setSources([]);setSource('');setPreview(null);setHeadings([]);setAccepted({});setQuery('');setResults(null);setError('');setNotice('');setLoading(true);setPending(false);setSearching(false);setPreviewLoading(false);
    Promise.all([api<Knowledge>(taskId,'/knowledge'),api<{sources:{path:string}[]}>(taskId,'/knowledge-sources')])
      .then(([knowledge,available])=>{if(current===generation.current){setData(knowledge);setSources(available.sources);}})
      .catch(e=>{if(current===generation.current)setError(e.message);})
      .finally(()=>{if(current===generation.current)setLoading(false);});
    return()=>{generation.current++;sourceGeneration.current++;searchGeneration.current++;};
  },[taskId]);
  async function selectSource(path:string){
    const current=generation.current,selection=++sourceGeneration.current;
    setSource(path);setPreview(null);setHeadings([]);setError('');setPreviewLoading(!!path);
    if(!path)return;
    try{const value=await api<Preview>(taskId,'/knowledge-source?path='+encodeURIComponent(path));if(current===generation.current&&selection===sourceGeneration.current)setPreview(value);}
    catch(e){if(current===generation.current&&selection===sourceGeneration.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(current===generation.current&&selection===sourceGeneration.current)setPreviewLoading(false);}
  }
  async function mutate(body:unknown,message:string,onSuccess?:()=>void){
    if(busy||pending)return;
    const current=generation.current;setPending(true);setError('');setNotice('');
    try{
      await api(taskId,'/knowledge',body);
      if(current!==generation.current)return;
      searchGeneration.current++;setResults(null);setSearching(false);setAccepted({});onChanged();
      const value=await api<Knowledge>(taskId,'/knowledge');
      if(current===generation.current){setData(value);setNotice(message);onSuccess?.();}
    }catch(e){if(current===generation.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(current===generation.current)setPending(false);}
  }
  async function search(){
    if(!query.trim()||searching||pending)return;
    const current=generation.current,request=++searchGeneration.current;setSearching(true);setError('');setResults(null);
    try{const value=await api<{results:Result[]}>(taskId,'/knowledge-search',{query:query.trim()});if(current===generation.current&&request===searchGeneration.current)setResults(value.results);}
    catch(e){if(current===generation.current&&request===searchGeneration.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(current===generation.current&&request===searchGeneration.current)setSearching(false);}
  }
  function importDocument(selectedHeadings:string[]|null){
    if(!preview||(selectedHeadings!==null&&!selectedHeadings.length))return;
    void mutate({action:'import',path:preview.path,headings:selectedHeadings},selectedHeadings===null?'整份文档已导入，核对适用版本后再确认。':'所选章节已导入，核对适用版本后再确认。',()=>{setSource('');setPreview(null);setHeadings([]);});
  }
  const disabled=busy||pending,confirmed=data?.documents.filter(item=>item.status==='confirmed'&&item.version===data.version).length||0;
  return <section className="dev-panel dev-knowledge" aria-label="研发资料管理">
    <h2>为这次研发选择有出处的资料</h2>
    <p className="dev-muted">从当前游戏 Git 基线的 README 与 docs Markdown 中选择章节，先导入，再由你核对适用性。只有当前基线中已确认的资料参与检索。项目记忆另行管理。</p>
    <p className="dev-muted">预览、导入和试搜只在本机进行，不调用模型，也不产生模型费用。更改已确认资料后，已准备的发送材料需要重新准备；运行中的任务沿用已冻结的资料副本。</p>
    {error&&<p className="dev-error" role="alert">{error}</p>}{notice&&<p className="dev-notice" role="status">{notice}</p>}
    {loading?<p role="status">正在读取研发资料…</p>:data&&<>
      <div className="dev-knowledge-baseline"><span>当前基线版本：<b>{data.version}</b></span><span>{confirmed} 份资料可检索</span></div>
      {data.mode==='off'&&<p className="dev-muted">这次任务已关闭 AI 资料检索。你仍可管理资料和本地试搜；已保存任务的检索模式保持原样。</p>}
      <div className="dev-memory-form dev-knowledge-import"><h3>从基线导入章节</h3>
        <label>选择基线资料<select value={source} disabled={disabled} onChange={e=>{void selectSource(e.target.value);}}><option value="">选择一份 README 或 docs 文档</option>{sources.map(item=><option key={item.path} value={item.path}>{item.path}</option>)}</select></label>
        {!sources.length&&<p className="dev-muted">当前基线没有可导入的 README 或 docs Markdown。</p>}
        {previewLoading&&<p role="status">正在预览基线章节…</p>}
        {preview&&<><p className="dev-memory-meta">{preview.title} · {preview.path} · 版本：{preview.version}</p>
          <p className="dev-muted">勾选父标题会一并包含它的全部子章节。也可直接导入整份文档，导入后都需人工确认。</p>
          {preview.sections.some(section=>!section.heading.trim())&&<p className="dev-muted">无标题内容仅在“导入整份文档”时包含；单独勾选标题不会包含文档前言。</p>}
          <div className="dev-knowledge-sections">{preview.sections.map((section,index)=><div key={index} className="dev-knowledge-section">
            {section.heading.trim()?<label className="dev-checkbox"><input type="checkbox" aria-label={'选择章节：'+section.heading} checked={headings.includes(section.heading)} disabled={disabled} onChange={e=>setHeadings(current=>e.target.checked?[...current,section.heading]:current.filter(heading=>heading!==section.heading))}/><span>{section.heading}<small>第 {section.start_line}–{section.end_line} 行</small></span></label>:<p className="dev-memory-meta">无标题内容（仅整份导入） · 第 {section.start_line}–{section.end_line} 行</p>}
            <details><summary>{section.heading.trim()?'预览章节：'+section.heading:'预览无标题内容'}</summary><pre>{section.text}</pre></details>
          </div>)}</div>
          <div className="dev-toolbar">{preview.sections.some(section=>section.heading.trim())&&<><button className="dev-primary" disabled={disabled||!headings.length} onClick={()=>importDocument(headings)}>导入所选章节（待确认）</button><span className="dev-muted">已选 {headings.length} 个章节</span></>}<button disabled={disabled} onClick={()=>importDocument(null)}>导入整份文档（待确认）</button></div>
        </>}
      </div>
      <h3>已导入资料</h3>
      {!data.documents.length?<p>还没有导入研发资料。</p>:<div className="dev-memories">{data.documents.map(item=>{
        const current=item.version===data.version;
        return <article key={item.id} className="dev-memory" aria-label={item.title}>
          <div className="dev-memory-heading"><h3>{item.title}</h3><b>{item.status==='confirmed'?'已确认':'待确认'}</b>{!current&&<span className="dev-knowledge-old">旧版本 · 不参与检索</span>}</div>
          <p className="dev-memory-meta">来源：{item.path} · 适用版本：{item.version}</p>
          <p className="dev-knowledge-headings">{item.headings===null?'整份文档':item.headings.join(' / ')}</p><p className="dev-memory-meta">共 {item.chunk_count??item.chunks?.length??0} 个片段</p>
          {current&&item.status==='pending'&&<label className="dev-checkbox"><input type="checkbox" checked={!!accepted[item.id]} disabled={disabled} onChange={e=>setAccepted({...accepted,[item.id]:e.target.checked})}/>{item.headings===null?'我已核对整份文档适用于当前基线版本':'我已核对所选章节适用于当前基线版本'}</label>}
          <div className="dev-toolbar">
            {current&&item.status==='pending'&&<button disabled={disabled||!accepted[item.id]} onClick={()=>{void mutate({action:'status',id:item.id,status:'confirmed'},'资料已确认；新的发送材料会封存当前版本的全部已确认资料。');}}>确认资料</button>}
            {item.status==='confirmed'&&<button disabled={disabled} onClick={()=>{void mutate({action:'status',id:item.id,status:'pending'},'资料已改为待确认，不再参与新的资料检索。');}}>取消确认</button>}
            <button disabled={disabled} onClick={()=>{void mutate({action:'delete',id:item.id},'资料已删除；已冻结的运行副本不受影响。');}}>删除资料</button>
          </div>
        </article>;
      })}</div>}
      <form className="dev-knowledge-search" onSubmit={e=>{e.preventDefault();void search();}}>
        <h3>看看能找到哪些资料</h3><p className="dev-muted">只检索当前基线已确认的资料，结果保留原始来源和行号。</p>
        <label>检索研发资料<input value={query} onChange={e=>setQuery(e.target.value)} maxLength={500} required placeholder="例如：护盾耗尽后需要清除什么？"/></label>
        <button disabled={pending||searching||!query.trim()}>本地试搜</button>
      </form>
      {searching&&<p role="status">正在本地检索…</p>}
      {results&&<div className="dev-knowledge-results" aria-live="polite">{!results.length?<p>没有找到相关的已确认资料。可以换个说法，或先核对资料与适用版本。</p>:results.map(result=><article className="dev-memory" key={result.id} aria-label={'检索结果：'+result.title+' · '+result.heading}>
        <h3>{result.title} · {result.heading}</h3><p className="dev-knowledge-snippet">{result.text}</p>
        <div className="dev-memory-meta"><span>{result.path}:{result.start_line}–{result.end_line}</span><span>版本：{result.version}</span></div>
        <details><summary>引用与匹配详情</summary><p className="dev-memory-meta">片段 ID：{result.id}<br/>文档 ID：{result.document_id}<br/>匹配分数：{result.score}<br/>{result.reason}</p></details>
      </article>)}</div>}
    </>}
  </section>;
}
