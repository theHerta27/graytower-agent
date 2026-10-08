import type {Report} from './types';
type Check={name:string;status:string};
type CodeJob={args:{variant:string};result:{tests:Check[];game_events?:unknown[]}};
const state=(s?:string)=>s==='PASS'?'通过':s==='FAIL'?'发现问题':s==='ERROR'?'检查出错':'未完成';
export default function CodeReport({report}:{report:Report}){
  const jobs=(report.jobs||[]) as unknown as CodeJob[];
  const old=jobs.find(j=>j.args.variant==='baseline')?.result.tests||[];
  const current=jobs.find(j=>j.args.variant==='candidate')?.result.tests||[];
  const labels=(report.test_labels||[]) as string[];
  return <div className="report-content">
    <section className={`verdict-banner ${report.verdict==='FAIL'?'failed':''}`}>
      <div><span className="eyebrow">独立检查结果</span><h2>{report.verdict==='PASS'?'这次修复通过检查':report.verdict==='FAIL'?'还有问题需要修复':'暂时不能判断是否修好'}</h2><p>{report.summary}</p></div>
    </section>
    <h3>具体检查了什么</h3><p className="subtle">在隔离环境分别运行原始故障版和修复版。这里的“通过”只针对下列检查。</p>
    <div className="table-scroll"><table><thead><tr><th>检查项目</th><th>原始故障版</th><th>修复后的版本</th></tr></thead><tbody>
      {labels.map((label,i)=><tr key={label}><td>{label}</td><td>{state(old[i]?.status)}</td><td>{state(current[i]?.status)}</td></tr>)}
    </tbody></table></div>
    <p className="notice">下一步：{report.verdict==='PASS'?'先看清变更，再决定是否采纳到本地测试版本。':report.verdict==='FAIL'?'将这些失败证据带给代码开发，创建新的修复任务。':'保留现场，补齐缺失的检查结果。'}</p>
    <details><summary>检查说明与事件证据</summary><p>{report.agent_decision_note}</p><pre>{JSON.stringify(report.observations,null,2)}</pre></details>
    {!!report.errors?.length&&<p className="notice error">检查过程中有 {report.errors.length} 项错误，详细记录已保留。</p>}
    <p className="subtle">{report.limitations?.join(' ')}</p>
    <details><summary>给开发者的技术详情</summary><pre>{JSON.stringify(report,null,2)}</pre></details>
  </div>;
}
