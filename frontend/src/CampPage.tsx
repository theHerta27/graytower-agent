import { useEffect, useState } from 'react';
import './camp.css';

type Turn = { request: { request_id: string; text: string }; status: string; reply?: { text: string }; offer?: { offer_hash: string; choices: { choice: string; name: string }[] } };
type Memory = { event_id: string; kind: string; payload: Record<string, unknown>; is_world_fact: boolean };
type Camp = { offline: boolean; expedition: string; turns: Partial<Record<'lan' | 'li', Turn>>; memories: Record<'lan' | 'li', Memory[]>; support_ready: boolean; report_shared: boolean; player_open: boolean; battle?: { revision: number; observation: { phase: string; state: { skill_points: number; units: Record<string, { side: string; hp: number; max_hp: number; shields: { value: number }[] }> }; result?: { outcome: string } } } };

export default function CampPage() {
  const [camp, setCamp] = useState<Camp>();
  const [npc, setNpc] = useState<'lan' | 'li'>('lan');
  const [text, setText] = useState('开场有点吃力，能帮我们准备一些支援吗？');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState<{ action: string; body?: unknown }>();
  async function call(action: string, body?: unknown) {
    setBusy(true); setError(''); setRetry({ action, body });
    try {
      const response = await fetch(`/camp/api/${action}`, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || '操作没有完成');
      setCamp(value); setRetry(undefined);
    } catch (failure) { setError(failure instanceof Error ? failure.message : '连接中断'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void call('state'); }, []);
  const turn = camp?.turns[npc], lan = camp?.turns.lan;
  const pending = turn?.status === 'awaiting_choice';
  const battle = camp?.battle, finished = battle?.observation.phase === 'finished';
  const names: Record<string, string> = { striker_01: '强攻手', support_01: '支援手', breaker_01: '击破手' };
  return <main className="camp-shell">
    <header className="camp-top"><a href="http://127.0.0.1:8767/" target="_blank" rel="noreferrer">灰塔 / 研发工作台 ↗</a><span>本机保存 · 无付费调用</span></header>
    <section className="camp-heading"><span className="camp-kicker">GRAYTOWER · CAMP</span><h1>出发之前，先歇一会儿。</h1><p>和同伴商量支援，亲自打一场，再把见闻带回来。</p><div className="camp-mode">离线剧情演示：台词为预编写内容，LangGraph、记忆、支援与战斗实际运行。</div></section>
    {error && <div className="camp-error" role="alert">{error} <button disabled={busy} onClick={() => retry && void call(retry.action, retry.body)}>重试这次操作</button><button disabled={busy} onClick={() => void call('state')}>刷新已保存状态</button></div>}
    <div className="camp-grid"><section className="camp-card">
      <div className="camp-tabs"><button className={npc === 'lan' ? 'active' : ''} onClick={() => setNpc('lan')}>岚 · 战前整备</button><button className={npc === 'li' ? 'active' : ''} onClick={() => setNpc('li')}>砾 · 观察哨</button></div>
      <div className="camp-speaker"><div className={`camp-portrait ${npc}`}>{npc === 'lan' ? '岚' : '砾'}</div><div><h2>{npc === 'lan' ? '先照顾好自己，再去闯关。' : '你回来，我就放心了。'}</h2><p>{npc === 'lan' ? '我能准备一份补给或护盾，你来选。' : '没有听你说过的事，我不会假装知道。'}</p></div></div>
      {turn && <div className="camp-dialog"><p className="camp-player">你：{turn.request.text}</p><p>{turn.reply?.text || (pending ? '有两种准备方式。看看哪一种更适合这次出发？' : '正在核对已保存的结果，请刷新查看。')}</p></div>}
      {npc === 'lan' && pending && <div className="camp-choices">{turn?.offer?.choices.map(choice => <button disabled={busy} key={choice.choice} onClick={() => void call('choose', { request_id: turn.request.request_id, choice: choice.choice, offer_hash: turn.offer?.offer_hash })}><strong>{choice.name}</strong><span>{choice.choice === 'shield_start' ? '每人120点护盾；到各自第3个普通回合末到期，耗尽提前消失。' : '开局增加1点战技点，最多5点。'}</span></button>)}</div>}
      <label className="camp-label" htmlFor="camp-message">想和{npc === 'lan' ? '岚' : '砾'}说些什么？</label><textarea id="camp-message" value={text} maxLength={1600} onChange={e => setText(e.target.value)} disabled={busy || pending} />
      <button className="camp-primary" disabled={busy || pending || !text.trim() || !camp} onClick={() => void call('talk', { npc, request_id: 'msg_' + crypto.randomUUID().replaceAll('-', ''), text })}>{busy ? '处理中…' : '交谈'}</button>
      <details className="camp-memory"><summary>看看{npc === 'lan' ? '岚' : '砾'}记得什么（调试）</summary>{(camp?.memories[npc] || []).map(m => <p key={m.event_id}><b>{m.kind === 'player_told' ? '你亲口告诉的事' : m.kind === 'battle_report_shared' ? '你带回的真实战报' : m.kind === 'expedition_prepared' ? '开始新的出发' : '亲自见证的整备'}</b><br />{m.kind === 'player_told' ? String(m.payload.text) : m.kind === 'battle_report_shared' ? '战斗结果已核对，来源保留。' : m.kind === 'expedition_prepared' ? '上次行动已结束，可以重新商量支援。' : '为这次出发准备了支援。'}</p>)}{!camp?.memories[npc]?.length && <p>还没有这位角色知道的新经历。</p>}</details>
    </section><aside className="camp-card camp-journey"><span className="camp-kicker">本次出发</span><h2>{finished ? '战斗结束了' : battle ? '战斗进度已保存' : camp?.support_ready ? '准备好了，出发吧' : '先选一份支援'}</h2>
      <ol><li className={camp?.support_ready ? 'done' : ''}>和岚交谈，选择支援</li><li className={battle ? 'done' : ''}>进入 Unity，选择行动</li><li className={camp?.report_shared ? 'done' : ''}>回来分享战报</li></ol>
      {lan?.reply && camp?.support_ready && <p>{lan.reply.text}</p>}
      {battle && <div className="camp-battle"><strong>战技点 {battle.observation.state.skill_points} / 5</strong>{Object.entries(battle.observation.state.units).filter(([,u]) => u.side === 'player').map(([id,u]) => <p key={id}>{names[id] || id}：生命 {u.hp}/{u.max_hp} · 护盾 {u.shields.reduce((n,s) => n+s.value,0)}</p>)}{finished && <b>结果：{({win:'胜利',loss:'失败',timeout:'达到行动上限'} as Record<string,string>)[battle.observation.result?.outcome || ''] || '已结束'}</b>}</div>}
      <button className="camp-primary" disabled={busy || !camp?.support_ready || camp.player_open || finished} onClick={() => void call('start', {})}>{camp?.player_open ? '游戏窗口已打开' : battle ? '继续 Unity 战斗' : '进入 Unity 战斗'}</button>
      <p className="camp-small">游戏内：↑↓ 选择，Enter 确认。先选技能，再按 Enter 执行；关闭窗口后可继续。</p>
      <button disabled={busy || !camp} onClick={() => void call('state')}>刷新战斗进度</button>
      {battle && !finished && <><button disabled={busy || camp?.player_open} onClick={() => void call('finish_demo', {})}>快速演示剩余战斗</button><p className="camp-small">先关闭 Unity 窗口，再让固定策略通过同一规则打完。此功能不是 Agent，也不是自动按键测试。</p></>}
      {finished && <button className="camp-primary" disabled={busy || camp?.report_shared} onClick={() => { setNpc('lan'); void call('share', {}); }}>把真实战报告诉岚</button>}
      {camp?.report_shared && <button disabled={busy || camp.player_open} onClick={() => void call('next', {})}>休整后再出发</button>}
    </aside></div><footer className="camp-footer">当前演示保留同一份本机存档。角色只知道自己听到、见到或被明确分享的事。</footer>
  </main>;
}
