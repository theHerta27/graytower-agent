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
}
const label = (s: string) => ({ needs_generation: '需求已保存', running: '处理中', failed: '执行失败',
  interrupted: '等待人工恢复', needs_input: '需要补充需求', rejected: '超出当前范围',
  awaiting_test_approval: '待批准测试', ready_for_verification: '可以发起验证',
  verification_completed: '验证已结束', historical_candidate: '历史候选，只读查看', history_view: '历史报告回看', completed: '已完成' })[s] || s;
const eventLabel = (s: string) => ({ task_created: '收到研发需求', existing_candidate_linked: '关联已有候选',
  author_operation: '作者操作状态', verification_operation: '验证操作状态', test_approved: '批准进入测试',
  job_receipt: '实际作业收据', verification_report: '独立验证报告', author_node: '作者图节点记录', candidate_frozen: '候选已冻结', historical_report_linked: '关联历史报告（未重新执行）' })[s] || s;
const freshId = () => 'task_' + crypto.randomUUID().replaceAll('-', '');

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
  const task = tasks.find(t => t.task_id === selected);
  const refresh = useCallback(async () => {
    try {
      const [list, items] = await Promise.all([api.taskList(), api.candidates()]);
      setTasks(list.tasks); setCandidates(items.candidates);
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
      const created = await api.taskCreate({ task_id: pendingId, kind, request, candidate_id: source || null });
      setSelected(created.task_id); setPendingId(freshId());
    });
  }
  const generateAllowed = task?.kind === 'config' && status?.model.enabled && status.model.actions?.includes('draft');
  const verifyAllowed = status?.model.enabled && status.model.actions?.includes('verify');
  const running = task?.status === 'running';
  return <div className="task-center">
    <p><a className="button secondary" href="/code-repair">查看真实护盾代码修复 →</a></p>
    {error && <div className="notice error" role="alert">{error}</div>}
    <div className="workspace-grid">
      <aside className="input-panel">
        <span className="eyebrow">研发需求 / TASK</span><h2>从一个任务开始</h2>
        <label htmlFor="task-request">研发需求</label>
        <textarea id="task-request" value={request} onChange={e => { setRequest(e.target.value); setPendingId(freshId()); }}
          placeholder="例如：将击破手战技倍率从 1.4 调到 1.6，其余保持不变。" />
        <label htmlFor="task-kind">任务类型</label>
        <select id="task-kind" value={kind} onChange={e => { setKind(e.target.value); setPendingId(freshId()); }}>
          <option value="config">策划配置</option><option value="coding">代码开发（代码修复链路待交付）</option><option value="verification">独立验证已有候选</option>
        </select>
        <label htmlFor="task-source">候选来源</label>
        <select id="task-source" value={source} onChange={e => { setSource(e.target.value); setPendingId(freshId()); }}>
          <option value="">新需求，生成新候选</option>
          {candidates.map(c => <option key={c.manifest_hash} value={c.manifest_hash}>{c.request}</option>)}
        </select>
        <p className="field-hint">创建任务只保存需求，不调用模型。选择已有候选时会明确标记来源，不算新的模型尝试。</p>
        <button className="button primary full-width" disabled={busy || !request.trim() || (kind === 'verification' && !source)} onClick={() => void create()}>创建任务</button>
        <div className="input-divider" /><span className="eyebrow">任务历史</span>
        <div className="request-list">{tasks.map(t => <button key={t.task_id} className={`request-item ${selected === t.task_id ? 'selected' : ''}`} onClick={() => setSelected(t.task_id)}>
          <strong>{t.request}</strong><span>{label(t.status)}</span><small>{t.origin === 'existing_candidate' ? '已有候选关联' : '新研发需求'}</small>
        </button>)}</div>
      </aside>
      <section className="candidate-panel" aria-label="统一任务详情">
        {!task ? <div className="empty-state"><h2>需求、候选和证据，放在同一个任务里</h2><p>从左侧创建任务，或选择已有记录。不会自动应用到游戏。</p></div> : <>
          <div className="section-heading"><h2>{task.request}</h2><span className="tag">{label(task.status)}</span></div>
          <p className="field-hint">任务：{task.task_id} · {task.origin === 'existing_candidate' ? '关联已有候选，未重新调用作者 Agent' : '新需求'} · 尚未应用到游戏</p>
          {!task.candidate && <>
            <button className="button primary" disabled={busy || running || !generateAllowed} onClick={() => void perform(() => api.taskGenerate(task.task_id))}>生成候选</button>
            {!generateAllowed && <p className="disabled-reason">当前未开放新模型调用；可以创建需求记录或关联已有候选。代码修复的工作树与隔离测试将在后续阶段交付。</p>}
            {task.author_result && <p>{task.author_result.message || task.author_result.proposal_message}</p>}
          </>}
          {task.candidate && <>
            <h3>冻结候选</h3>
            {task.candidate.diff.map((d, i) => <div className="diff-track" key={i}><strong>{d.path === 'skills.breaker_skill.multiplier' ? '击破手 · 战技倍率' : d.path}</strong><span>{String(d.before)}</span><strong>{String(d.after)}</strong></div>)}
            <div className="button-row"><a className="button secondary" href={`/api/tasks/${task.task_id}/export/json`}>下载 JSON</a><a className="button secondary" href={`/api/tasks/${task.task_id}/export/xlsx`}>下载 Excel</a>
              <button className="button primary" disabled={busy || task.candidate.confirmed || task.candidate.execution_compatible === false} onClick={() => void perform(() => api.taskApprove(task.task_id))}>{task.candidate.confirmed ? '已批准测试' : '批准进入测试'}</button></div>
            {task.candidate.compatibility_note && <p className="notice">{task.candidate.compatibility_note}</p>}
            <p className="field-hint">批准测试只允许后续验证此候选，不表示已采纳或发布。Excel 与 JSON 来自同一份冻结数据。</p>
            <label htmlFor="task-goal">验证目标</label><textarea id="task-goal" value={goal} onChange={e => setGoal(e.target.value)} />
            <label htmlFor="task-budget">战斗预算</label><select id="task-budget" value={budget} onChange={e => setBudget(Number(e.target.value))}><option value={2}>2 场 · 1 对样本</option><option value={4}>4 场 · 2 对样本</option></select>
            <button className="button secondary" disabled={busy || running || ['interrupted', 'failed'].includes(task.status) || task.candidate.execution_compatible === false || !task.candidate.confirmed || !verifyAllowed || !!task.report?.request.report || !goal.trim()} onClick={() => void perform(() => api.taskVerify(task.task_id, goal, budget))}>发起独立验证</button>
            {!verifyAllowed && <p className="disabled-reason">模型额度未开放；不会自动发起收费验证。</p>}
            {!task.report && task.historical_runs?.map(r => <button className="button secondary" disabled={busy} key={r.request_id} onClick={() => void perform(() => api.taskHistory(task.task_id, r.request_id))}>查看已有验证报告 · {r.request_id}</button>)}
          </>}
          {['interrupted', 'failed'].includes(task.status) && task.report && !task.report.request.report && <>
            <button className="button secondary" disabled={busy} onClick={() => void perform(() => api.taskResume(task.task_id))}>恢复已准入验证</button>
            <p className="field-hint">沿用原任务、预算和作业收据。未开放模型时可零推理恢复；未知作业不会自动重跑。</p>
          </>}
          {task.status === 'history_view' && <p className="notice">正在读取过去保存的报告；本次没有新模型调用、没有重新运行战斗。</p>}
          {task.report?.request.report && <ReportView detail={task.report} />}
          <div className="input-divider" /><h3>实际活动记录</h3>
          <ol className="task-timeline">{task.events.map((e, i) => <li key={i}><strong>{eventLabel(e.kind)}</strong><time>{new Date(e.time).toLocaleString('zh-CN')}</time><pre>{JSON.stringify(e.detail, null, 2)}</pre></li>)}</ol>
        </>}
      </section>
    </div>
  </div>;
}
