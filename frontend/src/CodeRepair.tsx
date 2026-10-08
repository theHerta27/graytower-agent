import {useEffect,useState} from 'react';
type Test={name:string;status:string};
type Demo={available:boolean;request:string;candidate_id:string;patch:string;summary:string;review:string;
  baseline_tests:Test[];candidate_tests:Test[];calls:number;cost_usd:string;autonomous_children:number};
export default function CodeRepair(){
  const [demo,setDemo]=useState<Demo|null>(null);const [error,setError]=useState('');
  useEffect(()=>{let active=true;void fetch('/api/code-demo').then(async r=>{
    if(!r.ok)throw new Error('无法核对代码修复记录，请检查本地服务的证据目录。');
    const value:Demo=await r.json();if(active)setDemo(value);
  }).catch(e=>{if(active)setError(String(e.message));});return()=>{active=false;};},[]);
  return <main className="code-repair-page"><a className="button secondary" href="/tasks">← 返回任务中心</a>
    <section className="candidate-panel"><span className="eyebrow">真实代码修复 / D-01</span><h1>让护盾先抵消伤害</h1>
      <p>受控故障案例：护盾已吸收伤害，角色生命却仍减少。Coding Agent 阅读规则、修改 Python，再由独立容器运行固定测试。</p>
      {error?<p role="alert">{error}</p>:!demo?<p>正在核对原记录…</p>:!demo.available?<p>此服务未配置代码演示记录。没有启动新的模型或测试。</p>:<>
        <p className="notice">这是已完成的真实运行记录；本次浏览零新调用，候选尚未应用到游戏。</p>
        <ol className="process-track"><li>提出故障</li><li>Runtime 定位与编辑</li><li>原生 Review</li><li>冻结补丁</li><li>容器测试</li></ol>
        <h2>1. 需求与实际补丁</h2><p>{demo.request}</p><pre>{demo.patch}</pre>
        <h2>2. 测试结果</h2><p>原始故障版有 {demo.baseline_tests.filter(t=>t.status==='FAIL').length} 项失败；候选版 {demo.candidate_tests.filter(t=>t.status==='PASS').length} 项通过。以下结论只覆盖本批固定护盾与伤害事件检查。</p>
        <table><thead><tr><th>检查</th><th>原始故障版</th><th>候选版</th></tr></thead><tbody>
          {demo.baseline_tests.map((t,i)=><tr key={t.name}><td>{['完全吸收：生命不变','部分吸收：只扣剩余伤害','无护盾：原行为不变','致死溢出与事件字段'][i]||t.name}</td><td>{t.status==='PASS'?'通过':t.status==='FAIL'?'失败':t.status}</td><td>{demo.candidate_tests[i]?.status==='PASS'?'通过':demo.candidate_tests[i]?.status||'缺失'}</td></tr>)}
        </tbody></table>
        <p className="notice">尚未接入统一代码 QA Agent 与采纳回退入口。这些是实际容器测试结果，不能当作全游戏回归通过。</p>
        <h2>3. Coding Agent 的说明</h2><div className="coding-prose">{demo.summary}</div>
        <details><summary>原生 Review 意见（不替代测试）</summary><div className="coding-prose">{demo.review}</div></details>
        <h2>4. 调用与协作</h2><p>{demo.calls} 次调用，峰价估算 {demo.cost_usd} 美元；本批剩余额度已关闭。</p>
        <p>{demo.autonomous_children?`实际自主委派 ${demo.autonomous_children} 个子任务。`:'本次允许 auto 协作，但没有自主委派子任务；原生 Review 已运行。'} 单次修复不能证明多 Agent 的质量或速度收益。</p>
        <details><summary>冻结候选编号</summary><p className="mono">{demo.candidate_id}</p></details>
      </>}
    </section></main>;
}
