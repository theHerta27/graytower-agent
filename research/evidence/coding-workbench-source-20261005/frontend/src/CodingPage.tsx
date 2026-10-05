import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, errorMessage } from './api';
import type { CodingRun, Status } from './types';

const KEY = 'graytower.coding-pending';
type Pending = { id: string; request: string; mode: 'single' | 'auto'; resume?: boolean };
const stateName = (state: string) => ({ running: '文件任务进行中', completed: '候选已交付', interrupted: '需要核对收据', failed: '执行未完成' })[state] || state;
function saved(): Pending | null {
  try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch { return null; }
}

export default function CodingPage({ status, revision, onCandidate }: {
  status: Status['coding']; revision: number; onCandidate: (hash: string) => void;
}) {
  const [runs, setRuns] = useState<CodingRun[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<CodingRun | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState('');
  const [mode, setMode] = useState<'single' | 'auto'>('single');
  const [authorizedId, setAuthorizedId] = useState('');
  const [pending, setPending] = useState<Pending | null>(saved);
  const [missing, setMissing] = useState(false);
  const [readRevision, setReadRevision] = useState(0);
  const tasks = status?.tasks || [];
  const authorized = tasks.find(task => task.operation_id === authorizedId);
  const enabled = !!status?.enabled && status.remaining_calls > 0 && tasks.length > 0;
  const running = runs.some(run => run.status === 'running');
  useEffect(() => {
    if (!tasks.length) { setAuthorizedId(''); return; }
    const chosen = tasks.find(task => task.operation_id === authorizedId) || tasks[0];
    setAuthorizedId(chosen.operation_id); setText(chosen.request); setMode(chosen.mode);
  }, [status?.tasks, authorizedId]);

  const reload = useCallback(async () => {
    const result = await api.codingRuns();
    setRuns(result.runs);
    setSelected(old => result.runs.some(run => run.operation_id === old) ? old : result.runs[0]?.operation_id || '');
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    reload().catch(issue => { if (active) setError(errorMessage(issue)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload, revision, readRevision]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    let active = true; let timer: ReturnType<typeof setTimeout>;
    setDetail(null);
    async function read() {
      try {
        const result = await api.codingRun(selected);
        if (!active) return;
        setDetail(result.run);
        setRuns(previous => previous.map(run => run.operation_id === result.run.operation_id ? result.run : run));
        if (result.run.status === 'running') timer = setTimeout(read, 1500);
      } catch (issue) { if (active) setError(errorMessage(issue)); }
    }
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, [selected, revision, readRevision]);

  function remember(next: Pending | null) {
    setPending(next); setMissing(false);
    try { if (next) sessionStorage.setItem(KEY, JSON.stringify(next)); else sessionStorage.removeItem(KEY); } catch { /* Durable server records still identify the task. */ }
  }
  useEffect(() => {
    if (!pending) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const operation = await api.operation(pending!.id);
        if (!active) return;
        setMissing(false);
        if (operation.status === 'running') { timer = setTimeout(poll, 1000); return; }
        remember(null);
        if (operation.error) setError(operation.error);
        setSelected(pending!.id); setReadRevision(value => value + 1);
      } catch (issue) {
        if (!active) return;
        if (issue instanceof ApiError && issue.status === 404) setMissing(true);
        else setError(errorMessage(issue));
        timer = setTimeout(poll, 2000);
      }
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [pending?.id]);

  async function submit(value?: Pending) {
    if (busy) return;
    const retry = !!value;
    if (!retry && (!enabled || pending || running || !authorized)) return;
    const next = value || { id: authorized!.operation_id, request: authorized!.request, mode: authorized!.mode };
    setBusy(true); setError(''); remember(next);
    try {
      const operation = next.resume ? await api.codingResume(next.id) : await api.codingStart(next.id, next.request, next.mode);
      if (operation.status !== 'running') remember(null);
      if (operation.error) setError(operation.error);
      setSelected(next.id); setReadRevision(v => v + 1);
    } catch (issue) {
      setError(errorMessage(issue));
      if (issue instanceof ApiError && issue.status >= 400 && issue.status < 500) remember(null);
    } finally { setBusy(false); }
  }

  return <>
    <section className={`model-status ${enabled ? 'available' : ''}`} aria-label="Coding 模型状态">
      <span className="status-symbol" aria-hidden="true">{enabled ? '●' : 'Ⅱ'}</span><div><strong>{enabled ? '文件任务已开放' : '文件任务当前只读'}</strong>
        <p>{status?.reason || '未配置 Coding 调用授权；可查看已保存的任务。'}</p>
        {enabled && <small>父任务、子任务与 Review 共用剩余 {status?.remaining_calls} 次额度。</small>}
      </div>
    </section>
    {error && <div className="notice error" role="alert"><span>{error}</span><button className="button text-button" onClick={() => setReadRevision(v => v + 1)}>重新读取文件任务</button></div>}
    {pending && <div className="notice progress-notice" role="status"><div><strong>正在核对文件任务状态</strong><p>刷新或重新打开页面不会另建任务。</p>
      {missing && <><p>服务尚未找到提交，可沿用原内容和同一标识重试。</p><button className="button secondary" disabled={busy} onClick={() => void submit(pending)}>按原内容重试文件任务</button></>}
    </div></div>}
    <ol className="process-track" aria-label="文件任务流程"><li className="active"><span>1</span>提出文件需求</li><li className={detail ? 'active' : ''}><span>2</span>修改与 Review</li><li><span>3</span>核对候选</li><li><span>4</span>独立验证</li></ol>
    <div className="coding-layout">
      <aside className="input-panel"><span className="eyebrow">文件任务 / CODING</span><h2>从实际文件开始</h2>
        {tasks.length > 0 && <><label htmlFor="coding-authorized-task">本次已授权任务</label><select id="coding-authorized-task" value={authorizedId} onChange={event => setAuthorizedId(event.target.value)} disabled={!!pending}>{tasks.map(task => <option key={task.operation_id} value={task.operation_id}>{task.mode === 'single' ? '单 Agent' : '自动协作'} · {task.request}</option>)}</select><p className="field-hint">沿用已授权的原需求和运行方式，不会扩大外发范围。</p></>}
        <label htmlFor="coding-request">希望修改什么</label><textarea id="coding-request" value={text} maxLength={4000} rows={5} onChange={event => setText(event.target.value)} disabled={!!pending} readOnly={tasks.length > 0} placeholder="例如：把击破手战技倍率改为 1.58，保留战技点消耗与削韧。" />
        <label htmlFor="coding-mode">运行方式</label><select id="coding-mode" value={mode} onChange={event => setMode(event.target.value as 'single' | 'auto')} disabled={!!pending || tasks.length > 0}><option value="single">单 Agent · 主任务直接完成</option><option value="auto">自动协作 · 按需要分配子任务</option></select>
        <p className="field-hint">自动协作允许主任务自行决定是否委派，并不保证每次都创建子任务。当前支持受限数值配置文件。</p>
        <button className="button primary full-width" disabled={!enabled || !authorized || busy || !!pending || running} onClick={() => void submit()}>开始文件任务</button>
        <div className="input-divider" /><span className="eyebrow">已保存的文件任务</span>
        <div className="request-list">{runs.map(run => <button className={`request-item ${selected === run.operation_id ? 'selected' : ''}`} key={run.operation_id} onClick={() => setSelected(run.operation_id)}><strong>{run.request}</strong><span>{run.mode === 'auto' ? '自动协作' : '单 Agent'}<b>{stateName(run.status)}</b></span></button>)}</div>
        {!runs.length && <p className="field-hint">{loading ? '正在读取…' : '还没有保存的任务。启用授权后，任务记录会保留在这里。'}</p>}
      </aside>
      <section className="candidate-panel coding-detail" aria-label="Coding 任务详情">
        {detail ? <><div className="section-heading"><div><span className="eyebrow">{detail.mode === 'auto' ? '自动协作 / AUTO' : '单 Agent / SINGLE'}</span><h2>{stateName(detail.status)}</h2></div><span className="tag">{detail.manifest_hash ? '候选尚未应用' : '保留执行记录'}</span></div>
          <p className="candidate-request">{detail.request}</p>
          <div className="coding-execution"><strong>自主委派 {detail.spawned_thread_ids.length} 个子任务</strong><span>{detail.seconds === null ? '执行时间待记录' : `本次文件任务 ${detail.seconds.toFixed(2)} 秒`}</span><p>{detail.spawned_thread_ids.length ? '子任务由 Runtime 调度；创建数量不代表任务质量提升。' : '修改任务没有自主委派；原生 Review 另行记录。这条记录不能用于宣称多 Agent 收益。'}</p></div>
          {detail.error && <p className="notice error">{detail.error}</p>}
          <h3>修改说明 · Agent 原文</h3><div className="coding-prose">{detail.summary || '尚未形成完整修改说明。'}</div>
          <section className="coding-review"><h3>原生 Review 意见 · 不等于 QA 通过</h3><div className="coding-prose">{detail.review_text || '尚无完整 Review 收据。'}</div></section>
          {detail.manifest_hash && <div className="confirmation-box"><div><strong>下一步：核对冻结候选</strong><p>查看实际差异和预检结果，确认后再交给独立 QA。</p></div><button className="button primary" onClick={() => onCandidate(detail.manifest_hash!)}>核对这一候选</button></div>}
          {(detail.status === 'interrupted' || detail.status === 'failed') && <div className="resume-bar"><p>仅使用已完成的收据尝试收尾；没有完整收据时会停止，不重新调用模型。</p><button className="button secondary" disabled={busy || !!pending || running} onClick={() => void submit({ id: detail.operation_id, request: detail.request, mode: detail.mode, resume: true })}>核对收据并收尾</button></div>}
          <details><summary>查看技术记录与费用口径</summary><dl><dt>任务标识</dt><dd className="mono">{detail.operation_id}</dd><dt>候选标识</dt><dd className="mono">{detail.manifest_hash || '尚未冻结'}</dd><dt>执行阶段</dt><dd>{detail.stage}</dd><dt>委派尝试</dt><dd>{detail.spawn_attempts}</dd></dl>
            {detail.spawned_thread_ids.length > 0 && <pre>{detail.spawned_thread_ids.join('\n')}</pre>}
            {detail.budget && <><p>费用按记录中的预算范围统计；批次共用账本时包含同批其他任务，不能当作本条任务费用。</p><pre>{JSON.stringify(detail.budget, null, 2)}</pre></>}
          </details>
        </> : <div className="empty-state"><span className="empty-mark">⌘</span><h2>{selected ? '正在读取文件任务…' : '选择任务查看执行过程'}</h2><p>这里保存文件修改、原生 Review 与候选的对应关系。</p></div>}
      </section>
    </div>
  </>;
}
