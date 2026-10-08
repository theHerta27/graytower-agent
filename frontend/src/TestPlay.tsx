import {useEffect,useState} from 'react';
type Command={kind:string;actor_id?:string;skill_id?:string;target_ids?:string[]};
type Unit={hp:number;max_hp:number;dead:boolean;shields:{value:number}[]};
type View={session_id:string;revision:number;play_configuration:{breaker_multiplier:number};
  observation:{actor_id:string;phase:string;result?:{outcome:string};state:{skill_points:number;units:Record<string,Unit>};legal_commands:Command[]}};
const person=(id?:string)=>({striker_01:'强攻手',support_01:'支援手',breaker_01:'击破手',boss_guardian_01:'试验型守卫'})[id||'']||id||'—';
const skill=(id?:string)=>({striker_basic:'普通攻击',striker_skill:'战技 · 强攻',striker_ultimate:'终结技 · 强攻',support_basic:'普通攻击',support_skill:'战技 · 群体治疗',support_ultimate:'终结技 · 全队护盾',breaker_basic:'普通攻击',breaker_skill:'战技 · 破盾攻击',breaker_ultimate:'终结技 · 击破'})[id||'']||id||'—';
const key='graytower.planner-test-session';
const pendingKey='graytower.planner-test-pending';
async function call(path:string,body?:unknown){
  const r=await fetch('/api/local-test/'+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await r.json();if(!r.ok)throw new Error(value.error?.message||'未收到可靠结果，请保留当前操作并重试。');return value as View;
}
export default function TestPlay(){
  const [view,setView]=useState<View|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [pending,setPending]=useState<{session_id:string;command:unknown}|null>(()=>{
    try{return JSON.parse(localStorage.getItem(pendingKey)||'null');}catch{return null;}
  });
  useEffect(()=>{const saved=localStorage.getItem(key);if(saved)void call(saved).then(setView).catch(e=>setError(e.message));},[]);
  async function start(){setBusy(true);setError('');try{
    const id='play_'+crypto.randomUUID().replaceAll('-','');
    localStorage.setItem(key,id);const next=await call('start',{session_id:id});
    localStorage.setItem(key,id);setView(next);setPending(null);
  }catch(e){setError(e instanceof Error?e.message:'无法开启战斗');}finally{setBusy(false);}}
  async function execute(body:{session_id:string;command:unknown}){setBusy(true);setError('');setPending(body);
    localStorage.setItem(pendingKey,JSON.stringify(body));
    try{const next=await call('command',body);setView(next);setPending(null);localStorage.removeItem(pendingKey);}catch(e){setError(e instanceof Error?e.message:'操作结果未知');}finally{setBusy(false);}}
  return <main className="rule-play"><a className="button secondary" href="/tasks">← 返回任务中心</a>
    <section className="candidate-panel"><span className="eyebrow">研发侧规则试玩 · 不调用模型</span><h1>亲手试试配置改动</h1>
      <p>采纳的配置用于新开的测试战斗。原来的战斗继续使用原配置；关闭页面不会删除进度。</p>
      <button className="button primary" disabled={busy||!!pending} onClick={()=>void start()}>新开测试战斗</button>
      {error&&<p className="notice error" role="alert">{error}</p>}
      {pending&&<button className="button secondary" disabled={busy} onClick={()=>void execute(pending)}>查询／重试刚才的同一个行动</button>}
      {view&&<>
        <p className="notice">本场击破手战技倍率：<strong>{view.play_configuration.breaker_multiplier}</strong>。技能点：<strong>{view.observation.state.skill_points} / 5</strong>。已完成 <strong>{view.revision}</strong> 次操作。</p>
        <div className="unit-cards">{Object.entries(view.observation.state.units).filter(([id])=>['striker_01','support_01','breaker_01','boss_guardian_01'].includes(id)).map(([id,u])=><div className="unit-card" key={id}>
          <h3>{person(id)}</h3><p>生命 {u.hp} / {u.max_hp}<br/>护盾 {u.shields.reduce((n,s)=>n+s.value,0)}{u.dead?' · 已退场':''}</p>
        </div>)}</div>
        <h2>{view.observation.result?({win:'战斗胜利',loss:'战斗失败',timeout:'本场达到行动上限'})[view.observation.result.outcome]||'战斗结束':`轮到${person(view.observation.actor_id)}行动`}</h2>
        <div className="button-row">{view.observation.legal_commands.map((c,i)=><button className="button secondary" key={i} disabled={busy||!!pending} onClick={()=>void execute({session_id:view.session_id,
          command:{command_id:'cmd_'+crypto.randomUUID().replaceAll('-',''),expected_revision:view.revision,command:c}})}>{c.kind==='skip_ultimate'?'暂不使用终结技':`${skill(c.skill_id)} → ${(c.target_ids||[]).map(person).join('、')}`}</button>)}</div>
        <details><summary>给开发者的状态与版本详情</summary><pre>{JSON.stringify(view,null,2)}</pre></details>
      </>}
      <p className="field-hint">这里直接使用 Python 游戏权威规则。玩家版 Unity 与营地演示有独立入口，不会随本地配置测试自动更新。</p>
    </section></main>;
}
