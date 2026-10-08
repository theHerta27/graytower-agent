import { useState } from 'react';
import { api, errorMessage } from './api';
import type { RequestDetail, Trace } from './types';
import CodeReport from './CodeReport';

export const policyName = (name: string) => ({ balanced: '均衡策略', survival: '生存策略', basic_only: '仅普通攻击' })[name] || name;
const outcomeName = (name: string) => ({ win: '胜利', loss: '失败', timeout: '超时' })[name] || name;
const eventName = (name: string) => ({ decision: '行动决策', direct_damage: '直接伤害', break_damage: '击破伤害', dot_damage: '持续伤害', battle_finished: '战斗结束', unit_died: '单位退场', phase_changed: '阶段切换' })[name] || name;
export const verdictLabel = (value?: string | null) => ({ INCONCLUSIVE: '尚不足以判断总体效果', FAIL: '发现失败证据', PASS: '验证通过' })[value || ''] || '等待报告';
const roundedAV=(value:string)=>{
  const [n,d]=value.split('/').map(Number);const number=d===undefined?n:n/d;
  return Number.isFinite(number)?number.toLocaleString('zh-CN',{maximumFractionDigits:2}):value;
};

function TraceView({ trace }: { trace: Trace }) {
  let events: Record<string, unknown>[] = [];
  try { events = JSON.parse(trace.excerpt).events || []; } catch { /* Original excerpt remains available below. */ }
  return <section className="trace-view" aria-label="战斗记录摘录">
    <div className="section-heading"><div><span className="eyebrow">证据 / 只读</span><h3>战斗记录摘录</h3></div><span className="tag">{trace.reference?.variant === 'baseline' ? '原配置' : '候选配置'} · 样本 {trace.reference?.seed ?? '—'}</span></div>
    <p className="notice warning">{trace.selection?.limit || '这是战斗记录的部分摘录，不能单独证明总体效果或因果关系。'}</p>
    <p className="subtle">已显示 {trace.selection?.selected_events ?? events.length} / {trace.selection?.total_events ?? '未知'} 条事件</p>
    {events.length > 0 && <div className="table-scroll"><table><thead><tr><th>事件</th><th>行动值</th><th>执行者</th><th>目标 / 结果</th></tr></thead><tbody>{events.map((event, index) => <tr key={String(event.event_id || index)}><td><strong>{eventName(String(event.kind))}</strong><small className="mono">{String(event.event_id || '')}</small></td><td className="mono">{String(event.av ?? '—')}</td><td className="mono">{String(event.actor_id || '—')}</td><td className="mono">{String(event.target_id || (event.payload as Record<string, unknown> | undefined)?.outcome || '—')}</td></tr>)}</tbody></table></div>}
    <details><summary>原始记录与选择范围</summary><pre>{JSON.stringify(trace, null, 2)}</pre></details>
  </section>;
}

export default function ReportView({ detail }: { detail: RequestDetail }) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [traceError, setTraceError] = useState('');
  const [loadingTrace, setLoadingTrace] = useState('');
  const { request, facts } = detail;
  const report = request.report;
  if (!report) return <section className="empty-state"><span className="empty-mark">…</span><h3>验证尚未交付</h3><p>已计入 {request.charged_battles} / {request.max_battles} 场预算。报告完成后会显示在这里。</p><p className="subtle">中断任务会保留原请求与已用预算，可在下方尝试恢复。</p></section>;
  if (report.kind==='code') return <CodeReport report={report}/>;
  const rows = Array.from(new Map((report.jobs || []).flatMap(job => job.result.rows || []).map(row => [`${row.policy}:${row.seed}`, row])).values());
  async function openTrace(hash: string) {
    setTraceError(''); setLoadingTrace(hash); setTrace(null);
    try { setTrace(await api.trace(request.request_id, hash)); } catch (error) { setTraceError(errorMessage(error)); }
    finally { setLoadingTrace(''); }
  }
  return <div className="report-content">
    <section className={`verdict-banner ${report.verdict === 'FAIL' ? 'failed' : ''}`}>
      <div><span className="eyebrow">这次检查的结论</span><h2>{verdictLabel(report.verdict)}</h2><p>{report.summary || '请结合程序事实与证据范围阅读本次结论。'}</p></div>
      <div className="structure-result"><span className={`status-dot ${report.structural_verdict === 'PASS' ? 'ready' : ''}`} />{report.structural_verdict === 'PASS' ? '配置格式与字段合法' : report.structural_verdict === 'FAIL' ? '配置检查失败' : '配置检查未完成'}</div>
    </section>
    {report.stop_reason === 'model_budget_exhausted' && <p className="notice warning">模型调用额度已用尽，调查已停止；已有证据和运行错误保留。</p>}
    <section className="report-section">
      <div className="section-heading"><div><span className="eyebrow">程序计算 / 可核对事实</span><h3>这批战斗发生了什么</h3></div><span className="tag">{facts?.distinct_pairs ?? rows.length} 对固定样本 · {request.charged_battles} 场已计入</span></div>
      {!facts ? <p className="notice warning">暂时没有可读取的程序事实，请查看原始报告。</p> : <>
        <div className="outcome-grid">{Object.entries(facts.transitions).map(([key, count]) => { const [policy, transition] = key.split(':'); const [before, after] = transition.split('->'); return <div className={`outcome-item ${before === 'win' && after !== 'win' ? 'regression' : ''}`} key={key}><span>{policyName(policy)}</span><strong>{outcomeName(before)} → {outcomeName(after)}</strong><b>{count}<small> 对</small></b></div>; })}</div>
        <p className="subtle">{facts.meaning}</p>
        {facts.comparisons.length > 0 ? <div className="table-scroll"><table className="comparison-table"><thead><tr><th>两版都胜利的样本</th><th>改动前行动值</th><th>改动后行动值</th><th>变化（改动后 − 改动前）</th></tr></thead><tbody>{facts.comparisons.map(pair => <tr key={`${pair.policy}:${pair.seed}`}><td><strong>样本 {pair.seed}</strong><small>{policyName(pair.policy)}</small></td><td className="mono">{roundedAV(pair.baseline_av)}</td><td className="mono">{roundedAV(pair.candidate_av)}</td><td><strong className="mono">{roundedAV(pair.delta_av)}</strong><small>{pair.direction}</small></td></tr>)}</tbody></table></div> : <p>没有双方都获胜的配对，无法比较共同胜利样本的行动值。</p>}
        <p className="field-hint">页面数值保留两位小数方便阅读；精确分数与原始判定保留在下方技术详情。</p>
        <p className="footnote">{facts.basis}</p><p className="notice">{facts.limit}</p>
      </>}
    </section>
    <section className="report-section">
      <div className="section-heading"><div><span className="eyebrow">运行过程 / 保留原记录</span><h3>失败与调查记录</h3></div><span className="tag warning-tag">{report.errors?.length || 0} 条运行错误</span></div>
      {report.errors?.length ? <ul className="error-list">{report.errors.map((error, index) => <li key={index}><span>运行错误 {index + 1}</span><code>{error}</code></li>)}</ul> : <p className="subtle">本报告没有记录运行错误。</p>}
      {!!report.observations?.length && <details><summary>查看 {report.observations.length} 条工具调查记录</summary><ol className="observation-list">{report.observations.map((observation, index) => <li key={index}><strong>{({ inspect_candidate: '检查候选', simulate: '运行战斗模拟', read_trace: '读取战斗记录' })[observation.tool || ''] || observation.tool || '工具结果'}</strong><pre>{JSON.stringify(observation, null, 2)}</pre></li>)}</ol></details>}
    </section>
    <section className="report-section">
      <div className="section-heading"><div><span className="eyebrow">证据 / 战斗记录</span><h3>沿着样本核对结果</h3></div></div>
      {rows.length ? <div className="evidence-list">{rows.map(row => <div className="evidence-row" key={`${row.policy}:${row.seed}`}><div><strong>样本 {row.seed}</strong><small>{policyName(row.policy)} · {outcomeName(row.baseline.outcome)} → {outcomeName(row.candidate.outcome)}</small></div><div className="button-row">{(['baseline', 'candidate'] as const).map(variant => row[variant].trace_sha256 && <button key={variant} className="button ghost compact" disabled={!!loadingTrace} aria-label={`查看${variant === 'baseline' ? '原配置' : '候选'}记录 · 样本${row.seed}`} onClick={() => openTrace(row[variant].trace_sha256!)}>{loadingTrace === row[variant].trace_sha256 ? '读取中…' : variant === 'baseline' ? '原配置记录 ↗' : '候选记录 ↗'}</button>)}</div></div>)}</div> : <p className="notice warning">没有已完成的战斗收据，不能展示战斗证据。</p>}
      {traceError && <p className="notice error" role="alert">{traceError}</p>}{trace && <TraceView trace={trace} />}
    </section>
    <section className="model-note"><span className="eyebrow">与程序事实分开阅读</span><h3>模型意见 · 未核验</h3><p className="subtle">{facts?.model_text_status || '模型意见不能覆盖计算事实或最终判定。'}</p><details><summary>阅读模型原文</summary><p className="preserve-lines">{report.agent_decision_note || '本次报告没有模型意见。'}</p></details></section>
    {!!report.limitations?.length && <section className="report-section"><h3>还缺什么</h3><ul className="limitations">{report.limitations.map(item => <li key={item}>{item}</li>)}</ul><p className="subtle">候选尚未应用到游戏基线。确认候选、委托验证和最终采纳分别进行。</p></section>}
    <details className="technical-details"><summary>请求标识、原始报告与参数</summary><dl><dt>请求</dt><dd className="mono">{request.request_id}</dd><dt>候选标识</dt><dd className="mono">{request.manifest_hash}</dd></dl>{detail.report_text && <pre>{detail.report_text}</pre>}<pre>{JSON.stringify(request.report, null, 2)}</pre></details>
  </div>;
}
