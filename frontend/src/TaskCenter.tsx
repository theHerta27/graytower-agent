import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage } from './api';
import ReportView from './ReportView';
import type { Candidate, RequestDetail, Status } from './types';

interface Task {
  task_id: string; kind: string; request: string; status: string; origin: string;
  candidate_id: string | null; candidate: Candidate | null; applied: boolean;
  report: RequestDetail | null; author_result?: { message?: string; proposal_message?: string } | null;
  events: { kind: string; time: string; detail: Record<string, unknown> }[];
  historical_runs?: { request_id: string; verdict: string }[];
  coding_operation_id?:string|null;
}
const label = (s: string) => ({ needs_generation: '需求已保存', running: '处理中', failed: '执行失败',
  interrupted: '等待人工恢复', needs_input: '需要补充需求', rejected: '超出当前范围',
  awaiting_test_approval: '待批准测试', ready_for_verification: '可以发起验证',
  verification_completed: '验证已结束', historical_candidate: '历史候选，只读查看', history_view: '历史报告回看', completed: '已完成' })[s] || s;
const eventLabel = (s: string) => ({ task_created: '收到研发需求', existing_candidate_linked: '关联已有候选',
  author_operation: '作者操作状态', verification_operation: '验证操作状态', test_approved: '批准进入测试',
  job_receipt: '实际检查已完成', verification_report: '收到独立检查报告', author_node: '生成改动的过程', candidate_frozen: '改动已保存，等待核对', historical_report_linked: '打开过去的报告（未重新执行）',local_version_adopted:'已采纳到本地测试版本',frozen_replay_requested:'按原方案重新检查' })[s] || s;
const freshId = () => 'task_' + crypto.randomUUID().replaceAll('-', '');
const shortRequest=(text:string)=>{const first=text.split('。')[0];return first.length>70?first.slice(0,70)+'…':first;};

export default function TaskCenter({ status }: { status: Status | null }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selected, setSelected] = useState('');
  const [request, setRequest] = useState('');
  const [kind, setKind] = useState('config');
  const [source, setSource] = useState('');
  const [goal, setGoal] = useState('比较原配置与候选的战斗表现，说明样本范围和限制。');
  const [budget, setBudget] = useState(4);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [pendingId, setPendingId] = useState(freshId);
  const [codingId,setCodingId]=useState('');
  const [acceptSample,setAcceptSample]=useState(false);
  const [releaseState,setReleaseState]=useState<Record<string,{active_release:string;version?:{candidate_id:string}|null}>>({});
  const task = tasks.find(t => t.task_id === selected);
  useEffect(()=>{setGoal(task?.candidate?.verification_goal||'比较原配置与候选的战斗表现，说明样本范围和限制。');setAcceptSample(false);},[task?.task_id,task?.candidate?.manifest_hash]);
  useEffect(()=>{if(task?.applied)localStorage.removeItem('graytower.pending-adoption.'+task.task_id);},[task?.task_id,task?.applied]);
  const refresh = useCallback(async () => {
    try {
      const [list, items,versions] = await Promise.all([api.taskList(), api.candidates(),api.releases()]);
      setTasks(list.tasks); setCandidates(items.candidates);
      setReleaseState(versions);
    } catch (e) { setError(errorMessage(e)); }
  }, []);
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 2500); return () => clearInterval(timer); }, [refresh]);
  async function perform(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); await refresh(); } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function create() {
    await perform(async () => {
      const created = await api.taskCreate({ task_id: pendingId, kind, request, candidate_id: source || null,
                                           coding_operation_id:kind==='coding'&&!source?codingId||null:null });
      setSelected(created.task_id); setPendingId(freshId());
    });
  }
  async function adoptCurrent(t:Task){
    const storageKey='graytower.pending-adoption.'+t.task_id;
    const operation=localStorage.getItem(storageKey)||'adopt_'+crypto.randomUUID().replaceAll('-','');
    localStorage.setItem(storageKey,operation);
    await api.taskAdopt(t.task_id,operation,t.candidate?.kind==='code'?false:acceptSample);
    localStorage.removeItem(storageKey);
  }
  async function replayCurrent(t:Task){
    const key='graytower.pending-replay.'+t.task_id;
    const id=localStorage.getItem(key)||freshId();localStorage.setItem(key,id);
    const next=await api.taskReplay(t.task_id,id);
    localStorage.removeItem(key);setSelected(next.task_id);
  }
  async function rollbackCurrent(k:string){
    const key='graytower.pending-rollback.'+k;
    const id=localStorage.getItem(key)||'rollback_'+crypto.randomUUID().replaceAll('-','');localStorage.setItem(key,id);
    await api.releaseRollback(k,id);localStorage.removeItem(key);
  }
  const generateAllowed = task?.kind === 'config' ? status?.model.enabled && status.model.actions?.includes('draft') :
    task?.kind==='coding'&&!!task.coding_operation_id&&status?.coding?.enabled;
  const verifyAllowed = status?.model.enabled && status.model.actions?.includes('verify');
  const running = task?.status === 'running';
  const isCode = task?.candidate?.kind === 'code';
  const configDemo=tasks.find(t=>t.kind==='config'&&t.candidate&&t.candidate.diff.length>0);
  const shieldDemo=tasks.find(t=>t.candidate?.profile==='shield-damage-python-v1'&&t.report?.request.report?.verdict==='PASS');
  return <div className="task-center">
    <div className="planner-guide"><strong>第一次使用，从这两条流程开始</strong><p>先看改了什么，再看检查结果，最后决定采纳或回退。打开已有记录不会产生模型费用。</p>
      <div className="button-row"><button className="button primary" disabled={!configDemo} onClick={()=>configDemo&&setSelected(configDemo.task_id)}>① 体验数值调整</button><button className="button secondary" disabled={!shieldDemo} onClick={()=>shieldDemo&&setSelected(shieldDemo.task_id)}>② 看护盾代码修复</button></div>
      <p className="field-hint">第二个战技点案例保留了首次失败，供你查看“检查发现问题后怎样处理”。</p></div>
    {error && <div className="notice error" role="alert">{error}</div>}
    <div className="workspace-grid">
      <aside className="input-panel">
        <span className="eyebrow">填写需求</span><h2>你想解决什么问题？</h2>
        <label htmlFor="task-request">研发需求</label>
        <textarea id="task-request" value={request} onChange={e => { setRequest(e.target.value); setPendingId(freshId()); }}
          placeholder="例如：将击破手战技倍率从 1.4 调到 1.6，其余保持不变。" />
        <label htmlFor="task-kind">任务类型</label>
        <select id="task-kind" value={kind} onChange={e => { setKind(e.target.value); setPendingId(freshId()); }}>
          <option value="config">调整数值配置</option><option value="coding">修复游戏代码</option><option value="verification">检查已有改动</option>
        </select>
        {kind==='coding'&&!!status?.coding?.tasks?.length&&<><label htmlFor="coding-choice">已授权的代码尝试</label><select id="coding-choice" value={codingId} onChange={e=>{
          setCodingId(e.target.value);const choice=status.coding?.tasks?.find(t=>t.operation_id===e.target.value);if(choice)setRequest(choice.request);setPendingId(freshId());
        }}><option value="">请选择一个已授权需求</option>{status.coding.tasks.map(t=><option key={t.operation_id} value={t.operation_id}>{t.request} · {t.mode==='auto'?'允许按需协作':'单 Agent'}</option>)}</select></>}
        <label htmlFor="task-source">候选来源</label>
        <select id="task-source" value={source} onChange={e => { setSource(e.target.value); setPendingId(freshId()); }}>
          <option value="">从新需求开始</option>
          {candidates.map(c => <option key={c.manifest_hash} value={c.manifest_hash}>{c.request}</option>)}
        </select>
        <p className="field-hint">创建任务只保存需求，不调用模型。选择已有候选时会明确标记来源，不算新的模型尝试。</p>
        <button className="button primary full-width" disabled={busy || !request.trim() || (kind === 'verification' && !source)} onClick={() => void create()}>创建任务</button>
        <div className="input-divider" /><span className="eyebrow">任务历史</span>
        <div className="request-list">{tasks.map(t => <button key={t.task_id} className={`request-item ${selected === t.task_id ? 'selected' : ''}`} onClick={() => setSelected(t.task_id)}>
          <strong>{shortRequest(t.request)}</strong><span>{label(t.status)}</span><small>{t.origin === 'existing_candidate' ? '已有候选关联' : '新研发需求'}</small>
        </button>)}</div>
      </aside>
      <section className="candidate-panel" aria-label="统一任务详情">
        {!task ? <div className="empty-state"><h2>需求、候选和证据，放在同一个任务里</h2><p>从左侧创建任务，或选择已有记录。不会自动应用到游戏。</p></div> : <>
          <div className="section-heading"><h2>{shortRequest(task.request)}</h2><span className="tag">{label(task.status)}</span></div>
          {shortRequest(task.request)!==task.request&&<details><summary>查看完整需求</summary><p>{task.request}</p></details>}
          <p className="field-hint">{task.origin === 'existing_candidate' ? '使用已保存的改动，本次没有重新生成。' : '新需求。'} {task.applied?'已采纳到本地测试版本；玩家游戏不自动更新。':'尚未应用到游戏。'}</p>
          {!task.candidate && <>
            <button className="button primary" disabled={busy || running || !generateAllowed} onClick={() => void perform(() => api.taskGenerate(task.task_id))}>生成候选</button>
            {!generateAllowed && <p className="disabled-reason">当前未开放新的模型额度。可以先保存需求，或选择已完成的改动进行检查；重新生成需要单独授权。</p>}
            {task.author_result && <p>{task.author_result.message || task.author_result.proposal_message}</p>}
          </>}
          {task.candidate && <>
            <h3>这次改了什么</h3>
            {isCode && <><p>修改游戏规则代码；下方独立检查会对照修复前后的实际结果。</p><details><summary>查看代码修改（供开发者核对）</summary><pre>{task.candidate.patch}</pre></details></>}
            {task.candidate.diff.map((d, i) => <div className="diff-track" key={i}><strong>{d.path === 'skills.breaker_skill.multiplier' ? '击破手 · 战技倍率' : d.path}</strong><span>{String(d.before)}</span><strong>{String(d.after)}</strong></div>)}
            <div className="button-row">{!isCode&&<><a className="button secondary" href={`/api/tasks/${task.task_id}/export/json`}>下载 JSON</a><a className="button secondary" href={`/api/tasks/${task.task_id}/export/xlsx`}>下载 Excel</a></>}
              {isCode&&<a className="button secondary" href={`/api/tasks/${task.task_id}/export/patch`}>下载代码补丁</a>}
              <button className="button primary" disabled={busy || task.candidate.confirmed || task.candidate.execution_compatible === false} onClick={() => void perform(() => api.taskApprove(task.task_id))}>{task.candidate.confirmed ? '已批准测试' : '批准进入测试'}</button></div>
            {task.candidate.compatibility_note && <p className="notice">{task.candidate.compatibility_note}</p>}
            <p className="field-hint">批准检查不会改变正在玩的游戏。{!isCode&&'Excel 与 JSON 展示同一份配置。'}</p>
            <label htmlFor="task-goal">验证目标</label><textarea id="task-goal" value={goal} onChange={e => setGoal(e.target.value)} />
            {!isCode&&<><label htmlFor="task-budget">检查规模</label><select id="task-budget" value={budget} onChange={e => setBudget(Number(e.target.value))}><option value={2}>小范围：改动前后各 1 场</option><option value={4}>标准演示：改动前后各 2 场</option></select></>}
            {isCode&&<p className="field-hint">修复前后各运行4项规则检查；{verifyAllowed?'本次已授权模型参与独立 QA 分析，会使用所示调用额度。':'当前按预设方案检查，不调用模型，不产生模型费用。'}</p>}
            <button className="button secondary" disabled={busy || running || ['interrupted', 'failed'].includes(task.status) || task.candidate.execution_compatible === false || !task.candidate.confirmed || (!verifyAllowed&&!isCode) || !!task.report?.request.report || !goal.trim()} onClick={() => void perform(() => api.taskVerify(task.task_id, goal, isCode?2:budget))}>{running?'正在检查…':'发起独立验证'}</button>
            {!verifyAllowed&&!isCode && <p className="disabled-reason">当前模型额度未开放，可以查看已有报告。</p>}
            {!task.report && task.historical_runs?.map(r => <button className="button secondary" disabled={busy} key={r.request_id} onClick={() => void perform(() => api.taskHistory(task.task_id, r.request_id))}>查看已有验证报告 · {r.request_id}</button>)}
          </>}
          {['interrupted', 'failed'].includes(task.status) && task.report && !task.report.request.report && <>
            <button className="button secondary" disabled={busy} onClick={() => void perform(() => api.taskResume(task.task_id))}>恢复已准入验证</button>
            <p className="field-hint">沿用原任务、预算和作业收据。未开放模型时可零推理恢复；未知作业不会自动重跑。</p>
          </>}
          {task.status === 'history_view' && <p className="notice">正在读取过去保存的报告；本次没有新模型调用、没有重新运行战斗。</p>}
          {task.report?.request.report && <ReportView detail={task.report} />}
          {task.report?.request.report&&<section className="next-actions"><h3>下一步怎么做</h3>
            <p>想核对结果，可重新测试；想体验配置改动，可采纳到本地测试版本后试玩。</p>
            <button className="button secondary" disabled={busy||running} onClick={()=>void perform(()=>replayCurrent(task))}>重新测试这份改动（不调用模型）</button>
            <p className="field-hint">会实际重新执行原测试方案，保留旧报告。重新测试不是重新请 Agent 求解，也不增加独立统计样本数。</p>
            {task.report.request.report.verdict!=='FAIL'&&<>
              {!isCode&&<label className="check-label"><input type="checkbox" checked={acceptSample} onChange={e=>setAcceptSample(e.target.checked)}/>我知道这里只观察了少量战斗，不能保证总体平衡；仅用于本地试玩。</label>}
              <button className="button primary" disabled={busy||task.applied||(!isCode&&!acceptSample)||(isCode&&task.report.request.report.verdict!=='PASS')} onClick={()=>void perform(()=>adoptCurrent(task))}>{task.applied?'已采纳到本地测试版本':'采纳到本地测试版本'}</button>
            </>}
            {task.report.request.report.verdict==='FAIL'&&<button className="button secondary" onClick={()=>{setKind(isCode?'coding':'config');setSource('');setRequest(task.request+'；请结合失败报告重新修订。');setSelected('');setPendingId(freshId());}}>创建新的修订需求</button>}
            <a className="button secondary" href="/test-play">打开配置规则试玩 →</a>
            {['config','code'].map(k=>(localStorage.getItem('graytower.pending-rollback.'+k)||(releaseState[k]?.active_release&&releaseState[k].active_release!=='baseline'))&&<button key={k} className="button ghost" disabled={busy} onClick={()=>void perform(()=>rollbackCurrent(k))}>{localStorage.getItem('graytower.pending-rollback.'+k)?'查询刚才的':'切回上一'}{ k==='config'?'配置':'代码'}{localStorage.getItem('graytower.pending-rollback.'+k)?'回退结果':'测试版本'}</button>)}
            <p className="field-hint">采纳和回退保留所有报告与存档。配置影响新开的测试战斗；代码只建立经过检查的独立测试版本，不热更新 Unity。</p>
          </section>}
          <div className="input-divider" /><h3>这项任务走到了哪一步</h3>
          <ol className="task-timeline">{task.events.map((e, i) => <li key={i}><strong>{eventLabel(e.kind)}</strong><time>{new Date(e.time).toLocaleString('zh-CN')}</time><details><summary>查看执行详情</summary><pre>{JSON.stringify(e.detail, null, 2)}</pre></details></li>)}</ol>
          <details><summary>给开发者的任务编号与版本信息</summary><p>{task.task_id}</p><p>{task.candidate_id}</p></details>
        </>}
      </section>
    </div>
  </div>;
}
