import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, errorMessage } from './api';
import ReportView, { verdictLabel } from './ReportView';
import CodingPage from './CodingPage';
import TaskCenter from './TaskCenter';
import type { Candidate, Operation, RequestDetail, RequestSummary, Status } from './types';

const fieldName = (path: string) => ({ 'skills.breaker_skill.multiplier': '击破手 · 战技倍率' })[path] || '配置字段变更';
const showValue = (value: unknown) => typeof value === 'object' ? JSON.stringify(value) : String(value);
const stateLabel = (value: string) => ({ new: '已受理', running: '验证进行中', completed: '报告已交付', failed: '执行失败', interrupted: '等待恢复' })[value] || value;
const OP_KEY = 'graytower.pending-operation';
type Pending = { id: string; kind: 'draft' | 'verify'; payload?: { request?: string; request_id?: string; manifest_hash?: string; goal?: string; max_battles?: number }; resume_request_id?: string };
function loadPending(): Pending | null {
  try { return JSON.parse(sessionStorage.getItem(OP_KEY) || 'null'); } catch { return null; }
}
function id(prefix: string) { return `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`; }

function CandidateView({ candidate, busy, onConfirm, onVerify }: { candidate: Candidate | undefined; busy: boolean; onConfirm: () => void; onVerify: () => void }) {
  const [checked, setChecked] = useState(false);
  useEffect(() => setChecked(false), [candidate?.manifest_hash]);
  if (!candidate) return <section className="empty-state candidate-empty"><span className="empty-mark">→</span><h2>候选变更将在这里展开</h2><p>选择已有候选，或填写需求生成提案。<br />确认前可逐项核对原值、候选值与检查结果。</p></section>;
  return <section className="candidate-panel" aria-label="候选变更">
    <div className="section-heading"><div><span className="eyebrow">候选提案 / 尚未应用</span><h2>先看清变更，再做决定</h2></div><span className={`tag ${candidate.confirmed ? 'success-tag' : ''}`}>{candidate.confirmed ? '已确认' : '待确认'}</span></div>
    <p className="candidate-request">{candidate.request}</p>
    <div className="diff-track-labels"><span>变更对象</span><span>原配置</span><span>候选配置</span></div>
    {candidate.diff.map((change, index) => <div className="diff-track" key={`${change.path}:${index}`}><div className="diff-subject"><span className="track-tick" /><strong>{fieldName(change.path)}</strong>{fieldName(change.path) === '配置字段变更' && <small className="mono">{change.path}</small>}</div><div className="diff-value before"><small>原配置</small><strong>{showValue(change.before)}</strong></div><div className="diff-value after"><span className="diff-arrow" aria-hidden="true">→</span><small>候选配置</small><strong>{showValue(change.after)}</strong></div></div>)}
    <div className="precheck"><span className={`status-dot ${candidate.validation.passed ? 'ready' : ''}`} /><strong>{candidate.validation.passed ? '确定性预检通过' : '预检未通过'}</strong><span>这里只检查配置是否合法，实际效果交给独立验证。</span></div>
    <details><summary>查看字段路径与检查依据</summary><dl><dt>候选标识</dt><dd className="mono">{candidate.manifest_hash}</dd></dl><pre>{JSON.stringify({ diff: candidate.diff, validation: candidate.validation }, null, 2)}</pre></details>
    <div className="confirmation-box">{candidate.confirmed ? <><div><strong>已批准进入测试，可以交给独立验证。</strong><p>验证会读取这一份冻结候选，返回独立证据报告。</p></div><button className="button primary" onClick={onVerify}>准备委托 QA <span aria-hidden="true">→</span></button></> : <><label className="check-label"><input type="checkbox" checked={checked} onChange={event => setChecked(event.target.checked)} disabled={busy || !candidate.validation.passed} />我已核对以上变更，批准进入测试</label><p className="subtle">本次批准仅允许测试；不会应用配置或启动战斗。</p><button className="button primary" disabled={!checked || busy || !candidate.validation.passed} onClick={onConfirm}>{busy ? '确认中…' : '批准进入测试'}</button></>}</div>
  </section>;
}

export default function App() {
  const [page, setPage] = useState<'config' | 'qa' | 'coding' | 'tasks'>(location.pathname === '/tasks' ? 'tasks' : 'config');
  const [status, setStatus] = useState<Status | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedHash, setSelectedHash] = useState('');
  const [requests, setRequests] = useState<RequestSummary[]>([]);
  const [selectedRequest, setSelectedRequest] = useState('');
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [requestText, setRequestText] = useState('');
  const [importHash, setImportHash] = useState('');
  const [goal, setGoal] = useState('比较修改前后的胜负和行动值，调查退步样本，不把小样本当总体保证。');
  const [budget, setBudget] = useState(4);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [pending, setPending] = useState(loadPending);
  const [missingOperation, setMissingOperation] = useState(false);
  const [readRevision, setReadRevision] = useState(0);
  const candidate = candidates.find(item => item.manifest_hash === selectedHash);
  const reportCandidate = candidates.find(item => item.manifest_hash === detail?.request.manifest_hash);
  const modelAvailable = !!status?.model.enabled && status.model.remaining_calls > 0;
  const canDraft = modelAvailable && (!status?.model.actions || status.model.actions.includes('draft'));
  const canVerify = modelAvailable && (!status?.model.actions || status.model.actions.includes('verify'));
  const inProgress = !!pending || operation?.status === 'running';

  const refresh = useCallback(async () => {
    const [nextStatus, nextCandidates, nextRequests] = await Promise.all([api.status(), api.candidates(), api.requests()]);
    setStatus(nextStatus); setCandidates(nextCandidates.candidates); setRequests(nextRequests.requests);
    setSelectedHash(previous => nextCandidates.candidates.some(item => item.manifest_hash === previous) ? previous : nextCandidates.candidates[0]?.manifest_hash || '');
    setSelectedRequest(previous => nextRequests.requests.some(item => item.request_id === previous) ? previous : nextRequests.requests[0]?.request_id || '');
  }, []);
  async function reload() { setLoading(true); setError(''); try { await refresh(); setReadRevision(value => value + 1); } catch (issue) { setStatus(null); setError(errorMessage(issue)); } finally { setLoading(false); } }
  useEffect(() => { let active = true; refresh().catch(issue => { if (active) setError(errorMessage(issue)); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [refresh]);

  useEffect(() => {
    if (!selectedRequest) { setDetail(null); return; }
    let active = true; let timer: ReturnType<typeof setTimeout>;
    setDetail(null); setDetailError(''); setDetailLoading(true);
    async function read() {
      try { const next = await api.detail(selectedRequest); if (active) { setDetail(next); setDetailError(''); if (next.request.status !== 'completed') timer = setTimeout(read, 1500); } }
      catch (issue) { if (active) setDetailError(errorMessage(issue)); }
      finally { if (active) setDetailLoading(false); }
    }
    void read(); return () => { active = false; clearTimeout(timer); };
  }, [selectedRequest, operation?.status, readRevision]);

  function remember(next: Pending | null) {
    setMissingOperation(false);
    setPending(next); try { if (next) sessionStorage.setItem(OP_KEY, JSON.stringify(next)); else sessionStorage.removeItem(OP_KEY); } catch { /* Server remains the source of truth. */ }
  }
  const pendingId = pending?.id;
  useEffect(() => {
    if (!pendingId) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.operation(pendingId!); if (!active) return;
        setOperation(next); setMissingOperation(false);
        if (next.status === 'running') { timer = setTimeout(poll, 750); return; }
        remember(null);
        if (next.error) setError(next.error);
        if (next.kind === 'draft' && next.result) {
          setNotice(next.result.proposal_message || next.result.message || '提案处理完成。');
          if (next.result.candidate) setSelectedHash(next.result.candidate.manifest_hash);
        }
        if (next.kind === 'verify') setSelectedRequest(next.operation_id.replace(/^verify_/, ''));
        await refresh();
      } catch (issue) { if (active) { if (issue instanceof ApiError && issue.status === 404) setMissingOperation(true); else setError(errorMessage(issue)); timer = setTimeout(poll, 2000); } }
    }
    timer = setTimeout(poll, 750); return () => { active = false; clearTimeout(timer); };
  }, [pendingId, refresh]);

  function updateCandidate(next: Candidate) { setCandidates(items => [next, ...items.filter(item => item.manifest_hash !== next.manifest_hash)]); setSelectedHash(next.manifest_hash); }
  async function inspectCandidate() {
    setBusy('inspect'); setError(''); setNotice('');
    try { updateCandidate(await api.inspect(importHash.trim())); setNotice('已读取冻结候选，请核对变更。'); }
    catch (issue) { setError(errorMessage(issue)); } finally { setBusy(''); }
  }
  async function confirmCandidate() {
    if (!candidate) return; setBusy('confirm'); setError('');
    try { updateCandidate(await api.confirm(candidate.manifest_hash)); } catch (issue) { setError(errorMessage(issue)); } finally { setBusy(''); }
  }
  async function submit(kind: 'draft' | 'verify') {
    if (inProgress || busy || (kind === 'draft' ? !canDraft || !requestText.trim() : !canVerify || !candidate?.confirmed || !goal.trim())) return;
    const requestId = id(kind); const operationId = kind === 'verify' ? `verify_${requestId}` : requestId;
    setBusy(kind); setError(''); setNotice('');
    remember({ id: operationId, kind, payload: kind === 'draft' ? { request: requestText.trim() } : { request_id: requestId, manifest_hash: candidate!.manifest_hash, goal: goal.trim(), max_battles: budget } });
    try {
      const next = kind === 'draft' ? await api.draft(operationId, requestText.trim()) : await api.verify(requestId, candidate!.manifest_hash, goal.trim(), budget);
      setOperation(next); if (kind === 'verify') setSelectedRequest(requestId);
    } catch (issue) {
      setError(errorMessage(issue));
      // Explicit server rejections have no pending operation. Network failures remain queryable by the same ID.
      if (issue instanceof ApiError && issue.status >= 400 && issue.status < 500) remember(null);
    } finally { setBusy(''); }
  }
  async function resume() {
    if (!detail || inProgress) return;
    setBusy('resume'); setError('');
    const operationId = `verify_${detail.request.request_id}`; remember({ id: operationId, kind: 'verify', resume_request_id: detail.request.request_id });
    try { setOperation(await api.resume(detail.request.request_id)); }
    catch (issue) { setError(errorMessage(issue)); if (issue instanceof ApiError && issue.status >= 400 && issue.status < 500) remember(null); }
    finally { setBusy(''); }
  }
  async function retryPending() {
    if (!pending || busy) return;
    setBusy('retry'); setError('');
    try {
      let next: Operation;
      if (pending.resume_request_id) next = await api.resume(pending.resume_request_id);
      else if (pending.kind === 'draft' && pending.payload?.request) next = await api.draft(pending.id, pending.payload.request);
      else if (pending.kind === 'verify' && pending.payload?.request_id && pending.payload.manifest_hash && pending.payload.goal && pending.payload.max_battles) {
        next = await api.verify(pending.payload.request_id, pending.payload.manifest_hash, pending.payload.goal, pending.payload.max_battles);
      } else throw new Error('页面未保留原始内容，请按操作标识检查本地记录。');
      setOperation(next); setMissingOperation(false);
    } catch (issue) { setError(errorMessage(issue)); }
    finally { setBusy(''); }
  }
  async function openCodingCandidate(hash: string) {
    setError('');
    try { updateCandidate(await api.inspect(hash)); setPage('config'); } catch (issue) { setError(errorMessage(issue)); }
  }
  const pageCopy = { tasks: ['任务中心', '从研发需求，走到可审阅的结果。', '候选、批准测试与独立报告共享同一个任务，无需搬运文件或复制编号。', 'TASKS'], config: ['配置提案', '每一次调整，都有据可查。', '写下调整需求，核对候选差异，再决定是否交给 QA。', 'CONFIG'], qa: ['独立验证', '从候选出发，向证据求证。', '选择已确认的候选，设定目标与预算，阅读独立验证报告。', 'VERIFICATION'], coding: ['文件开发', '从文件修改，走到独立验证。', '查看实际变更、原生 Review 与任务分工，核对候选后再做验证。', 'CODING'] }[page];
  function openQA() { setPage('qa'); const linked = requests.find(item => item.manifest_hash === selectedHash); if (linked) setSelectedRequest(linked.request_id); setError(''); setNotice(''); }
  const selector = <><label htmlFor="candidate-select">已冻结的候选</label><select id="candidate-select" value={selectedHash} onChange={event => { setSelectedHash(event.target.value); setNotice(''); }} disabled={loading || !candidates.length}><option value="" disabled>{candidates.length ? '选择候选' : '还没有候选'}</option>{candidates.map((item, index) => <option value={item.manifest_hash} key={item.manifest_hash}>{index + 1}. {item.request.length > 52 ? `${item.request.slice(0, 52)}…` : item.request} · {item.confirmed ? '已确认' : '待确认'}</option>)}</select></>;

  return <div className="app-shell">
    <a href="#main-content" className="skip-link">跳到主要内容</a>
    <aside className="sidebar"><div className="brand"><span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span><div><strong>灰塔前哨</strong><small>研发工作台</small></div></div><div className="nav-caption">工作区</div><nav aria-label="主要导航"><button className={page === 'tasks' ? 'nav-item selected' : 'nav-item'} aria-current={page === 'tasks' ? 'page' : undefined} onClick={() => setPage('tasks')}>任务中心<span className="nav-arrow">→</span></button><button className={page === 'coding' ? 'nav-item selected' : 'nav-item'} aria-current={page === 'coding' ? 'page' : undefined} onClick={() => setPage('coding')}><span aria-hidden="true">⌘</span>文件开发<span className="nav-arrow" aria-hidden="true">→</span></button><button className={page === 'config' ? 'nav-item selected' : 'nav-item'} aria-current={page === 'config' ? 'page' : undefined} onClick={() => setPage('config')}><span aria-hidden="true">≋</span>配置提案<span className="nav-arrow" aria-hidden="true">→</span></button><button className={page === 'qa' ? 'nav-item selected' : 'nav-item'} aria-current={page === 'qa' ? 'page' : undefined} onClick={() => setPage('qa')}><span aria-hidden="true">⊡</span>独立验证<span className="nav-arrow" aria-hidden="true">→</span></button></nav><div className="sidebar-footer"><span className="status-dot ready" /><span>本地工作台</span><p>确认变更<br />让证据说明结果</p><span className="mono">V1 / LOCAL</span></div></aside>
    <main id="main-content" className="main-content">
      <header className="topbar"><span>灰塔前哨 <b>/</b> {pageCopy[0]}</span><div className="button-row"><span className={`connection ${status ? '' : 'offline'}`}><span className="status-dot" />{status ? '本地服务已连接' : loading ? '连接中' : '服务未连接'}</span><button className="button text-button" disabled={loading} onClick={() => void reload()}>刷新数据</button></div></header>
      <div className="page-body"><div className="page-intro"><div><span className="eyebrow">{pageCopy[0]} / {pageCopy[3]}</span><h1>{pageCopy[1]}</h1><p>{pageCopy[2]}</p></div><span className="workspace-stamp">{page === 'qa' ? 'VERIFIER' : 'AUTHOR'}<small>{page === 'qa' ? '候选的验证者' : '候选的提出者'}</small></span></div>
      {page !== 'coding' && page !== 'tasks' && <section className={`model-status ${modelAvailable ? 'available' : ''}`} aria-label="模型状态"><span className="status-symbol" aria-hidden="true">{modelAvailable ? '●' : 'Ⅱ'}</span><div><strong>{modelAvailable ? '模型调用已开放' : '模型调用已关闭'}</strong><p>{status?.model.reason || (loading ? '正在读取模型授权与额度…' : '服务未连接，暂时无法确认模型状态。')}</p>{modelAvailable && <small>剩余 {status?.model.remaining_calls} 次调用；可用操作：{canDraft ? '生成提案' : ''}{canDraft && canVerify ? '、' : ''}{canVerify ? '独立验证' : ''}</small>}</div><span className="model-status-tail">已有候选与证据仍可查阅</span></section>}
      {error && <div className="notice error global-notice" role="alert"><strong>操作未完成</strong><span>{error}</span><button className="button text-button" onClick={() => setError('')} aria-label="关闭错误提示">关闭</button></div>}
      {notice && <p className="notice success-notice" role="status">{notice}</p>}
      {inProgress && <div className="notice progress-notice" role="status"><span className="loading-dot" /><div><strong>{operation?.status === 'running' ? operation.kind === 'draft' ? '正在生成并预检候选' : '独立验证正在运行' : '正在核对操作状态'}</strong><p>页面会读取最新进度；刷新页面后仍可继续核对同一操作。</p><details><summary>操作标识</summary><code>{pending?.id || operation?.operation_id}</code></details></div></div>}
      {missingOperation && pending && <div className="notice warning" role="status"><p>服务尚未找到这次操作，可能没有收到提交。重试沿用原始内容和同一个标识，不会创建另一个任务。</p><button className="button secondary" disabled={!!busy} onClick={() => void retryPending()}>按原内容重试提交</button></div>}
      {loading && <p className="loading-line" role="status">正在读取候选与验证记录…</p>}
      {page === 'tasks' ? <TaskCenter status={status} /> : page === 'coding' ? <CodingPage status={status?.coding} revision={readRevision} onCandidate={hash => void openCodingCandidate(hash)} /> : page === 'config' ? <><ol className="process-track" aria-label="配置工作流程"><li className="active"><span>1</span>提出需求</li><li className={candidate ? 'active' : ''}><span>2</span>核对差异</li><li className={candidate?.confirmed ? 'active' : ''}><span>3</span>批准测试</li><li><span>4</span>委托独立验证</li></ol><div className="author-layout"><aside className="input-panel"><span className="eyebrow">需求输入</span><h2>准备一次调整</h2><label htmlFor="request-text">想调整什么</label><textarea id="request-text" rows={6} maxLength={4000} value={requestText} disabled={inProgress} onChange={event => setRequestText(event.target.value)} placeholder="例如：将击破手的战技倍率改为 1.6，其他配置保持不变。" /><p className="field-hint">说明变更对象和目标值，候选生成后仍需你确认。</p><button className="button primary full-width" disabled={!canDraft || !requestText.trim() || !!busy || inProgress} onClick={() => void submit('draft')}>生成候选提案</button>{!canDraft && <p className="disabled-reason">当前未开放生成提案，可先查看已有候选。</p>}<div className="input-divider" />{selector}<details className="import-candidate"><summary>读取现有候选</summary><p className="field-hint">输入本地已有冻结候选的完整标识。</p><label htmlFor="import-hash">候选标识</label><input id="import-hash" className="mono" value={importHash} onChange={event => setImportHash(event.target.value)} placeholder="64 位候选标识" autoComplete="off" spellCheck={false} /><button className="button secondary full-width" disabled={!/^[a-f0-9]{64}$/.test(importHash.trim()) || !!busy} onClick={() => void inspectCandidate()}>{busy === 'inspect' ? '读取中…' : '读取候选'}</button></details></aside><CandidateView candidate={candidate} busy={busy === 'confirm'} onConfirm={() => void confirmCandidate()} onVerify={openQA} /></div>{candidate && requests.some(item => item.manifest_hash === selectedHash) && <button className="linked-report" onClick={openQA}><div><span className="eyebrow">已有验证记录</span><strong>查看这一候选的独立证据</strong></div><span>前往报告 →</span></button>}</> : <div className="qa-layout"><aside className="input-panel qa-input"><span className="eyebrow">新验证委托</span><h2>划定检查范围</h2>{selector}{candidate && <div className="selected-candidate-note"><span className={`tag ${candidate.confirmed ? 'success-tag' : 'warning-tag'}`}>{candidate.confirmed ? '候选已确认' : '尚未确认'}</span><p>{candidate.diff.map(change => `${fieldName(change.path)} ${showValue(change.before)} → ${showValue(change.after)}`).join('；')}</p></div>}{candidate && !candidate.confirmed && <button className="button text-button" onClick={() => setPage('config')}>返回配置提案确认 →</button>}<label htmlFor="verification-goal">这次要验证什么</label><textarea id="verification-goal" rows={5} maxLength={3000} value={goal} disabled={inProgress} onChange={event => setGoal(event.target.value)} /><label htmlFor="battle-budget">最多使用的战斗场数</label><select id="battle-budget" value={budget} onChange={event => setBudget(Number(event.target.value))} disabled={inProgress}><option value={2}>2 场 · 最多 1 对样本</option><option value={4}>4 场 · 最多 2 对样本</option></select><p className="field-hint">一对样本各运行一次原配置与候选。重复读取报告不增加样本。</p><button className="button primary full-width" disabled={!canVerify || !candidate?.confirmed || !goal.trim() || !!busy || inProgress} onClick={() => void submit('verify')}>开始独立验证</button>{!canVerify && <p className="disabled-reason">当前未开放新验证，可阅读已有报告。</p>}<div className="input-divider" /><span className="eyebrow">已保存的验证</span><div className="request-list">{requests.length ? requests.map(item => <button className={`request-item ${selectedRequest === item.request_id ? 'selected' : ''}`} onClick={() => setSelectedRequest(item.request_id)} key={item.request_id}><strong>{item.goal}</strong><span>{stateLabel(item.status)}<b>{item.charged_battles}/{item.max_battles} 场</b></span><small>{verdictLabel(item.verdict)}</small></button>) : <p className="field-hint">还没有验证记录。候选确认后，可在授权额度内创建验证。</p>}</div></aside><section className="report-panel" aria-label="独立验证报告">{detailLoading ? <div className="empty-state" role="status">正在读取验证报告…</div> : detailError ? <div className="notice error" role="alert">{detailError}<button className="button text-button" onClick={() => void reload()}>刷新数据</button></div> : detail ? <><div className="report-header"><span className="eyebrow">{stateLabel(detail.request.status)}</span><p>{detail.request.goal}</p><strong>报告绑定候选：{reportCandidate ? reportCandidate.diff.map(change => `${fieldName(change.path)} ${showValue(change.before)} → ${showValue(change.after)}`).join('；') : detail.request.manifest_hash.slice(0, 12)}</strong></div><ReportView key={detail.request.request_id} detail={detail} />{detail.request.status !== 'completed' && <div className="resume-bar"><p>恢复会沿用原请求、候选与预算；模型关闭时不新增推理。缺少作业收据时会停止并提示人工对账。</p><button className="button secondary" disabled={!!busy || inProgress} onClick={() => void resume()}>恢复此验证</button></div>}</> : <div className="empty-state"><span className="empty-mark">⊡</span><h2>等待第一份独立报告</h2><p>从左侧选择已有记录，或确认候选后委托一次验证。</p></div>}</section></div>}
      <footer className="page-footer"><span>灰塔前哨 · 本地研发工作台</span><span>文件 / 配置候选 → 人工确认 → 独立验证</span></footer></div>
    </main>
  </div>;
}
