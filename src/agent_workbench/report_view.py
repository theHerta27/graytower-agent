"""Program-derived player-facing facts; model prose never owns arithmetic."""
from collections import Counter
from fractions import Fraction


def facts_for_report(report):
    rows = {}
    for job in report.get('jobs', []):
        for row in job['result'].get('rows', []):
            key = (row['policy'], row['seed'])
            if key in rows and rows[key] != row:
                raise ValueError('same sample has conflicting evidence')
            rows[key] = row
    comparisons, transitions = [], Counter()
    for (policy, seed), row in sorted(rows.items()):
        baseline, candidate = row['baseline'], row['candidate']
        transitions[policy + ':' + baseline['outcome'] + '->' + candidate['outcome']] += 1
        if baseline['outcome'] != 'win' or candidate['outcome'] != 'win':
            continue
        before, after = Fraction(str(baseline['elapsed_av'])), Fraction(str(candidate['elapsed_av']))
        if before <= 0 or after <= 0:
            raise ValueError('winning battle AV must be positive')
        delta = after - before
        comparisons.append({'policy': policy, 'seed': seed, 'baseline_av': str(before),
                            'candidate_av': str(after), 'delta_av': str(delta),
                            'direction': '行动值减少' if delta < 0 else '行动值增加' if delta > 0 else '行动值不变'})
    return {'verdict': report['verdict'], 'distinct_pairs': len(rows), 'comparisons': comparisons,
            'transitions': dict(transitions), 'original_error_count': len(report.get('errors', [])),
            'basis': '由原始配对结果使用精确分数计算；重复读取不增加样本数。',
            'meaning': '行动值 AV 是战斗行动时间轴；数值较少表示同条件下更早结束，不是程序运行耗时。',
            'limit': '这些固定样本不能证明总体胜率、总体通关速度或玩家体验改善。',
            'model_text_status': '模型自然语言说明为未核验草稿，不能覆盖这里的计算事实或原判定。'}


def render_report(report):
    facts = facts_for_report(report)
    label = '尚不足以判断总体效果' if facts['verdict'] == 'INCONCLUSIVE' else '发现失败证据'
    lines = [f'验证结果：{label}（{facts["verdict"]}）',
             f'本批共 {facts["distinct_pairs"]} 对固定样本。', facts['meaning']]
    if report.get('stop_reason') == 'model_budget_exhausted':
        lines.append('模型调用额度已用尽，已停止继续调查并保留已有证据。')
    outcomes = {'win': '胜利', 'loss': '失败', 'timeout': '超时'}
    for transition, count in sorted(facts['transitions'].items()):
        policy, change = transition.split(':', 1)
        before, after = change.split('->', 1)
        lines.append(f'{policy} / {outcomes.get(before, before)} → {outcomes.get(after, after)}：{count} 对。')
    if not facts['comparisons']:
        lines.append('本批没有双方都获胜的配对，无法比较共同胜利样本的行动值。')
    for pair in facts['comparisons']:
        lines.append(f'样本 {pair["seed"]} / {pair["policy"]}：两个版本都获胜；基线 AV {pair["baseline_av"]}，候选 AV {pair["candidate_av"]}，{pair["direction"]}（差值 {pair["delta_av"]}）。')
    if facts['original_error_count']:
        lines.append(f'原运行记录了 {facts["original_error_count"]} 次运行错误；错误详情保留在原始报告中。')
    if not report.get('jobs'):
        lines.append('没有已完成的战斗收据。')
    lines.extend([facts['limit'], '候选尚未应用到游戏基线。'])
    return '\n'.join(lines)
