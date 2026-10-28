import {useEffect,useState} from 'react';

export type Delivery={preparation_id:string;kind:string;state:string;target_branch:string;target_commit:string;
  candidate_commit:string;merge_commit?:string;worktree_path:string;patch?:string;changed_files?:string[];
  can_approve:boolean;approval_hash:string|null;approved_hash?:string;note:string;stale_reason:string|null;conflicts?:string[];
  cleanup_hash?:string|null;cleanup_error?:string;adopted_preparation?:string|null;other_preparations?:{preparation_id:string;state:string;cleanup_hash:string|null;cleanup_error?:string}[];
  checks:{job_id:string;status:string;note?:string;result:null|{verdict:string;tests:{name:string;status:string}[]}}[]};

type Props={delivery:Delivery|null;blocked:boolean;archived:boolean;onAction:(name:string,args:Record<string,unknown>)=>void};

export default function GitDeliveryPanel({delivery:d,blocked,archived,onAction}:Props){
  const [confirmation,setConfirmation]=useState<{preparation_id:string;approval_hash:string}|null>(null);
  const [discard,setDiscard]=useState<{preparation_id:string;cleanup_hash:string}|null>(null);
  useEffect(()=>setConfirmation(null),[d?.preparation_id,d?.approval_hash,d?.state]);
  const disabled=blocked||archived;
  return <section className="dev-delivery" aria-label="Git 合并与撤销">
    <h2>检查合并结果，再决定是否合入</h2>
    <p>每个任务使用独立 Git 工作树。采用会合入 Git 提交；撤销会新增提交，保留原来的历史。</p>
    {archived&&<p>任务已归档，可以查看差异和检查记录。</p>}
    {(!d||!['applied','applying'].includes(d.state))&&<button disabled={disabled} onClick={()=>onAction('delivery-prepare',{kind:'merge'})}>准备合并结果</button>}
    {d&&<>
      <p>{d.note}</p><p>目标分支：<strong>{d.target_branch}</strong> · {d.kind==='revert'?'撤销前的版本':'合并前的版本'}：<code>{d.target_commit.slice(0,12)}</code></p>
      {d.stale_reason&&<p role="alert">{d.stale_reason}</p>}
      {d.state==='conflict'&&<div><p>请在下面的交付目录处理冲突，执行 git add 标记已解决；不要自行提交或切换分支。随后点击“检查冲突处理结果”。</p>
        <code>{d.worktree_path}</code><ul>{d.conflicts?.map(name=><li key={name}>{name}</li>)}</ul>
        <button disabled={disabled} onClick={()=>onAction('delivery-resolve',{preparation_id:d.preparation_id})}>检查冲突处理结果</button></div>}
      {d.merge_commit&&<p>准备合入的提交：<code>{d.merge_commit}</code></p>}
      {d.patch&&<details open><summary>准备合入的实际差异</summary><pre>{d.patch}</pre></details>}
      {d.checks.map(check=><p key={check.job_id}>合并结果检查：{check.result?.verdict||check.status}{check.result?` · ${check.result.tests.length} 项`:''}{check.note?` · ${check.note}`:''}</p>)}
      {d.state==='prepared'&&<div className="dev-toolbar">
        <button disabled={disabled||!!d.stale_reason} onClick={()=>onAction('delivery-check',{preparation_id:d.preparation_id})}>检查这份合并结果</button>
        <button disabled={disabled||!d.can_approve||!d.approval_hash} onClick={()=>setConfirmation({preparation_id:d.preparation_id,approval_hash:d.approval_hash!})}>{d.kind==='revert'?'审阅并撤销':'审阅并合入'}</button>
      </div>}
      {d.state==='applied'&&<button disabled={disabled} onClick={()=>onAction('delivery-prepare',{kind:'revert',operation_id:d.preparation_id})}>准备撤销提交</button>}
      {d.state!=='applied'&&d.adopted_preparation&&<button disabled={disabled} onClick={()=>onAction('delivery-prepare',{kind:'revert',operation_id:d.adopted_preparation})}>准备撤销已采用提交</button>}
      {d.state==='applying'&&<button disabled={disabled} onClick={()=>onAction('delivery-approve',{preparation_id:d.preparation_id,approval_hash:d.approved_hash})}>核对并继续原合并</button>}
      {[d,...(d.other_preparations||[])].filter(p=>p.cleanup_hash).map(p=><p key={p.preparation_id}>准备记录 {p.preparation_id.slice(0,8)}：<button disabled={disabled} onClick={()=>setDiscard({preparation_id:p.preparation_id,cleanup_hash:p.cleanup_hash!})}>废弃这次准备</button></p>)}
      {d.cleanup_error&&<p>{d.cleanup_error}</p>}
      {discard&&<div className="dev-confirm"><p>把这份交付工作树中的允许文件和暂存区记录保存到 abandoned.json，再删除交付工作树。原项目和 Agent 候选不变；额外文件或现场变化会阻止清理。</p><button disabled={disabled} onClick={()=>{onAction('delivery-discard',discard);setDiscard(null);}}>保存现场并废弃</button><button onClick={()=>setDiscard(null)}>取消废弃</button></div>}
      {confirmation&&<div className="dev-confirm"><p>已审阅上面的差异和检查结果。确认后会{d.kind==='revert'?'新增撤销提交':'合入这个 Git 提交'}；原项目或候选变化时，程序会停止操作。</p>
        <button disabled={disabled} onClick={()=>onAction('delivery-approve',confirmation)}>{d.kind==='revert'?'确认新增撤销提交':'确认合入这个 Git 提交'}</button>
        <button onClick={()=>setConfirmation(null)}>返回审阅</button></div>}
    </>}
  </section>;
}
