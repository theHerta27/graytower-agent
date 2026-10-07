"""Freeze read-only, bounded review packets; never reads model runs or results.

Run with combat-foundation/.venv/Scripts/python.exe -B prepare_tasks.py.
Existing frozen files may only be reproduced byte-for-byte. Candidate mutations
exist exclusively under oracle/private, never in any source checkout.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
COMBAT = Path('D:/Desktop/combat-foundation')
HERTA = Path('D:/Desktop/herta-agent-coding')
V = 'mihoyo-agent-project/src/agent_workbench/verification/'
G = 'combat-foundation/game-core/combat_core/v2/'
U = 'combat-foundation/game-unity/Assets/Runtime/'
H = 'herta-agent-coding/backend/herta_agent/service/'


def raw(path):
    repo, rel = path.split('/', 1)
    return {'combat-foundation': COMBAT, 'herta-agent-coding': HERTA,
            'mihoyo-agent-project': PROJECT}[repo].joinpath(rel).read_bytes()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def frozen_write(path, value):
    data = value if isinstance(value, bytes) else value.encode('utf-8')
    if path.exists() and path.read_bytes() != data:
        raise RuntimeError(f'Frozen output differs; no overwrite permitted: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def issue(i, severity, path, needle, root, trigger, evidence, fix, aliases=()):
    return dict(issue_id=i, severity=severity, path=path, needle=needle,
                root_cause=root, trigger=trigger, required_evidence=evidence,
                fix=fix, aliases=list(aliases), verification_ids=[i])


TASKS = [
dict(id='dev01', split='development', title='护盾与战斗快照跨层评审',
request='我们想减少战斗Trace的快照分配，并简化Unity护盾展示和回合末维护。请审查冻结候选，判断是否仍满足护盾持续期、事件历史不可变和回放显示要求。只报候选新增的可行动问题，不把建议重构当缺陷。',
rules=['Python是唯一结算权威；每个事件的state_after必须保存发出时的完整独立状态，后续伤害和状态到期不能改写历史事件。',
       '护盾由不同来源叠加，显示值是当前全部有效护盾的value之和；空护盾显示0。',
       'remaining按持有者普通回合结束结算；当护盾在持有者当前普通回合中创建时，该回合结束不消耗持续期。终结技本身不额外推进普通回合。',
       '此题不要求设计战前支援新功能；只判断现有护盾/快照链路。Unity仅从权威快照加载和显示。'],
sources={G+'effects.py':[(110,127),(222,247)], G+'state.py':[(1,82)],
         G+'trace.py':[(1,60),(108,123)], G+'simulation.py':[(21,69)],
         U+'CombatUnitView.cs':[(1,20),(41,65)], U+'CombatStateV2.cs':[(9,41)]},
mutations={G+'effects.py':[('        if sh.fresh_turn==state.normal_turn_count:continue\n','')],
           G+'trace.py':[('state_after=state.model_copy(deep=True)', 'state_after=state.model_copy(deep=False)')],
           U+'CombatUnitView.cs':[('V2State.shields.Sum(x=>x.value)', 'V2State.shields.Select(x=>x.value).DefaultIfEmpty(0).Max()')]},
issues=[
 issue('D01-HISTORY','P1',G+'trace.py','state_after=state.model_copy(deep=False)',
       '浅复制BattleState共享units及其中UnitState，后续结算会改写已记录事件。',
       '发出battle_started或任一伤害前事件后，再修改同一单位hp/shields。',
       ['EventRecorder.emit使用deep=False仅复制外层模型。','BattleState.units及UnitState的可变对象仍共享，后续修改污染旧state_after；不是只有显示缓存问题。'],
       '恢复深复制，或使用等价的完整不可变快照。', ['事件污染','历史快照别名']),
 issue('D01-DURATION','P2',G+'effects.py','    for sh in list(u.shields):',
       '移除fresh_turn跳过规则，使当前回合新授予自己的护盾提前消耗一次持续期。',
       '持有者回合中施放护盾，fresh_turn等于normal_turn_count；同回合end_statuses。',
       ['apply_skill_effects会记录fresh_turn。','同回合end_statuses不再跳过，remaining=1立即消失或remaining=3降为2。'],
       '在护盾到期循环恢复fresh_turn判断。', ['自施护盾少一回合']),
 issue('D01-DISPLAY','P2',U+'CombatUnitView.cs','public int Shield',
       '显示由所有护盾求和改为最大单层，叠加护盾被低估。',
       '同一单位有两个有效来源护盾，例如120和80。',
       ['UnitSnapshotV2.shields是多层护盾列表。','Max显示120，规则总值应200；空列表已DefaultIfEmpty处理，不能误报空列表异常。'],
       '保留Sum，或明确用全部有效护盾求和。', ['叠盾显示错误'])],
non_issues=['DefaultIfEmpty(0)已处理空护盾列表；不能报告Max空集合异常。','不要求Unity自行扣护盾或推进回合。']),

dict(id='dev02', split='development', title='实验恢复与账本对账调查',
request='一次进程中断后，实验恢复偶发接受了旧批准或不完整结果。请结合冻结候选及诊断记录，审查领域账本的批准、worker准入、收据提交三段边界。checkpoint只用于路由，不能当作已经完成实验的事实。不要推断未展示的网络或数据库故障。',
rules=['批准必须与同一request_id的不可变plan_hash完全匹配。API调用者可能拿着旧版本/另一个计划的hash，不能仅凭ID批准。',
       'worker被准入后即保守计入完整冻结场次数。进程死于execute中时，running表示外部结果未知，没有可对账领域收据时必须拒绝自动重试。',
       '完整收据必须绑定plan_hash、game_fingerprint，且每个(policy,seed)恰有一个baseline/candidate结果；complete提交前必须验证。',
       '领域completed后checkpoint未同步可安全恢复；既有completed账本应避免再次执行或再次扣账。日志中的时钟、checkpoint节点名均不构成批准。'],
sources={V+'store.py':[(38,150)],V+'workflow.py':[(37,55),(67,110)],V+'report.py':[(9,23)], V+'contracts.py':[(20,65)]},
mutations={V+'store.py':[
 ('if row is None or row[0] != plan_hash:', 'if row is None:'),
 ('if row["job_status"] != "new":', 'if row["job_status"] not in ("new", "running"):'),
 ('        build_report(plan, result)  # Check manifest before acknowledging a completed experiment.',
  '        # The worker has already produced a result; defer reporting to show().')]},
issues=[
 issue('D02-APPROVAL','P1',V+'store.py','            if row is None:',
       'decide不再比较传入plan_hash，旧hash也能批准当前计划。',
       '对有效request_id传入其他计划的hash并approve=True。',
       ['查询返回plan_hash却只判断row是否存在。','后续UPDATE使用request_id写approved，claim检查当前账本hash无法恢复调用者实际批准的hash。'],
       '恢复plan_hash相等检查后才记录批准。'),
 issue('D02-RETRY','P1',V+'store.py','            if row["job_status"] not in',
       'claim允许running再次准入；外部结果未知时会再次调用execute。',
       '第一次claim提交后worker可能执行，进程在complete之前退出；新进程resume。',
       ['workflow.experiment对未completed状态调用claim后execute。','running被允许导致第二次执行，而charged_battles仍覆盖为plan.battles而非反映两次执行。'],
       '仅允许new进入执行；running必须对账领域收据或人工处置。', ['未知结果重复执行','恢复重跑']),
 issue('D02-RECEIPT','P1',V+'store.py','        # The worker has already produced a result',
       'complete在写completed前不验证收据manifest，错误计划或不完整结果进入持久化事实。',
       'running计划收到plan_hash不匹配、game_fingerprint错误或缺少pair的worker结果。',
       ['complete移除build_report校验而仍写result_json/result_hash及completed。','自身fingerprint(result)只能防后续篡改，不能证明结果绑定计划；show晚校验不能撤销已完成状态。'],
       '提交前恢复完整收据校验，失败保持未确认状态。', ['错计划收据','complete缺验证'])],
non_issues=['普通resume不是批准这一检查仍存在。','driver_lock仍是进程锁，不是本次候选新问题。'], logs=True),

dict(id='confirm01', split='confirmation', title='行动窗口和Boss蓄力轮转评审',
request='候选清理了行动入口和蓄力取消逻辑。请针对玩家动作准入以及Boss被击破后的技能轮转审查。调用方既可能是内置bot，也可能是未来的受控玩家输入；不能用bot当前不发送某类请求代替入口校验。',
rules=['每个普通回合可先释放至多一个满能终结技，再普通行动；普通行动已用后不能补放终结技。',
       'Boss蓄力技能启动时不推进skill_index；正常释放或被击破取消后都消费当前技能槽，下一次从后续槽继续。',
       '进入新阶段的重置由apply_phase_transition处理；本题只审查同一阶段内的准入和蓄力取消。',
       '只报告冻结diff新增的问题；不要求更改bot策略、技能池或新增手动客户端。'],
sources={G+'effects.py':[(127,214)],G+'state.py':[(30,110)],G+'boss.py':[(1,100)],G+'bots.py':[(1,55)],G+'simulation.py':[(35,67)]},
mutations={G+'effects.py':[('if state.ultimate_used or state.normal_used or u.energy!=u.energy_max:', 'if state.ultimate_used or u.energy!=u.energy_max:')],
           G+'state.py':[('    unit.skill_index+=1\n','')]},
issues=[
 issue('C01-WINDOW','P1',G+'effects.py','if state.ultimate_used or u.energy!=u.energy_max:',
       'validate_action移除normal_used检查，允许普通行动后的终结技。',
       '当前活跃玩家满能，normal_used=True且ultimate_used=False，直接提交其拥有的终结技。',
       ['入口缺少normal_used限制。','bot.choose_ultimate仍限制但外部ActionRequest绕过bot，resolve_action依赖validate_action准入。'],
       '在终结技入口恢复normal_used校验。', ['普通攻击后终结技']),
 issue('C01-CHARGE','P2',G+'state.py','    unit.charging=None',
       'cancel_charge清空charging却不推进skill_index，使下一次仍选择被取消的蓄力槽。',
       'Boss本阶段位于一个interruptible技能槽；启动时advance=False，被击破后cancel_charge，下次choose_enemy_action。',
       ['resolve_enemy_action启动蓄力不增加skill_index。','choose_enemy_action用pool[skill_index%len(pool)]，取消后未推进会重复该槽而非下一槽。'],
       '成功取消蓄力时推进skill_index一次；未蓄力时不推进。', ['取消蓄力不推进轮转'])],
non_issues=['apply_phase_transition新阶段重置charging/skill_index仍符合题设。']),

dict(id='confirm02', split='confirmation', title='配对报告和源码冻结评审',
request='为精简结果报告和源码扫描，候选调整了配对集合校验、AV指标和游戏指纹文件选择。请判断是否仍能拒绝重复结果、保持指标方向，以及把本次运行实际导入的规则源码全部纳入冻结。无需评价统计显著性或提出更多样本。',
rules=['一个(policy,seed)恰好代表一场baseline与一场candidate，结果行不能重复，即使重复行完全相同。',
       'paired_av_ratio_median定义为共同获胜样本的candidate.elapsed_av / baseline.elapsed_av的中位数；小于1表示候选更快。',
       'game-core/combat_core及services/verification-agent/verification_agent中的所有Python源文件均属于冻结输入，包含包入口__init__.py；导入包时入口也可能执行代码。',
       '报告仍仅为DESCRIPTIVE_ONLY，不应据此宣称总体非劣；此项并非本候选需要修复的缺陷。'],
sources={V+'report.py':[(1,70)],V+'combat_worker.py':[(1,140)],V+'contracts.py':[(1,75)],V+'store.py':[(104,145)]},
mutations={V+'report.py':[
 ('if len(actual) != len(expected) or set(actual) != expected:', 'if set(actual) != expected:'),
 ('ratios.append(cav / bav)', 'ratios.append(bav / cav)')],
 V+'combat_worker.py':[('paths = [p for folder in roots for p in folder.rglob("*.py")]',
                       'paths = [p for folder in roots for p in folder.rglob("*.py") if p.name != "__init__.py"]')]},
issues=[
 issue('C02-DUPLICATE','P1',V+'report.py','    if set(actual) != expected:',
       '集合去重后比较丢失行数约束，重复同一pair可被接受并污染指标权重。',
       '结果包含所有预期pair，同时额外复制某一个(policy,seed)行。',
       ['set(actual)仍等于expected但len(actual)多于expected。','后续data按原rows统计pairs/胜率/中位数，重复不会再被过滤。'],
       '同时校验行数和集合，拒绝重复pair。'),
 issue('C02-RATIO','P2',V+'report.py','ratios.append(bav / cav)',
       'AV比率被取倒数，颠倒候选快慢方向。',
       '共同获胜baseline AV=100，candidate AV=80。',
       ['规范定义candidate/baseline应为0.8。','实际bav/cav得到1.25，方向与指标含义相反。'],
       '恢复cav/bav，保持共同获胜筛选。', ['AV倒数','基线候选比值颠倒']),
 issue('C02-FINGERPRINT','P1',V+'combat_worker.py','if p.name != "__init__.py"',
       '源指纹排除可执行包入口，入口修改不会使计划失效。',
       '冻结后只修改combat_core/__init__.py或verification_agent/__init__.py再执行。',
       ['新列表排除所有__init__.py。','work后续导入这些包，检查前后指纹都无法检测入口变化。'],
       '纳入包入口及其路径和字节。', ['入口指纹缺失'])],
non_issues=['本题不要求从小样本升级为严格非劣推断。']),

dict(id='confirm03', split='confirmation', title='SSE背压及取消清理评审',
request='候选简化了SSE内存队列和持久化清理等待。请审查消费者变慢、断线以及取消到达提交阶段时，是否仍保持有界背压与清理任务所有权。仅讨论给定单进程服务实现，不假设多worker部署。',
rules=['EventQueue在项数或字节数达到上限时等待空间，消费者取出事件后必须唤醒等待的生产者；队列清空不代表Run已终止。',
       '调用者取消可以停止业务推理，但已经由服务持有的持久化收尾任务不能被调用者取消；_wait_owned必须等待它结束并取回结果。',
       'RunHandle.emit发生背压超时会标记cancel_requested并抛CancelledError；不能用超时退出把丢失唤醒当作正常行为。',
       '只需审查冻结候选这两段修改引发的行为；不要求新增SSE断线续传、持久事件日志或改变POST拥有Run的设计。'],
sources={H+'events.py':[(1,125)],H+'runs.py':[(30,116),(205,299)],H+'sse.py':[(1,110)]},
mutations={H+'events.py':[('        self._space.set()\n','')],H+'runs.py':[('            await asyncio.shield(task)', '            await task')]},
issues=[
 issue('C03-WAKEUP','P1',H+'events.py','        self._bytes -= self._sizes.popleft()',
       'get_nowait释放队列空间但不再set _space，已等待生产者不会继续。',
       '队列满后put等待，消费者get_nowait取走一个事件，随后无人取消。',
       ['put在QueueFull后clear并await _space.wait。','get_nowait不再set导致即使有空间仍阻塞，RunHandle.emit到时取消run。'],
       '成功取出并更新字节数后恢复_space.set。', ['队列丢失唤醒']),
 issue('C03-OWNERSHIP','P1',H+'runs.py','            await task',
       '_wait_owned直接await将外层取消传播到所有权任务，捕获外层CancelledError不能恢复已取消任务。',
       'finish_run或response cleanup尚未完成，正在_wait_owned的调用者收到cancel。',
       ['asyncio.shield被删除，取消传播给task。','task变为cancelled/done，循环结束后task.result再次抛CancelledError，持久化收尾未完成。'],
       '用asyncio.shield保护拥有的任务，并保留循环处理重复外部取消。', ['取消传播至提交任务'])],
non_issues=['RunResponse设计上断线取消Run，题目没有要求继续后台推理。']),

dict(id='confirm04', split='confirmation', title='配对清单不可变集合整理',
request='候选把报告中的预期pair集合明确为不可变集合，以便代码表达“冻结清单”。请只审查这次改动是否改变当前授权、结果校验或报告计算。可以没有发现；不要把原有代码的拓展建议算成本次回归。',
rules=['expected仅用于len和与set(actual)比较；每个(policy,seed)恰好一行。',
       'frozenset和set对相同元素按集合内容判等；冻结计划中的policies/seeds都是可哈希字符串/整数。',
       '未变更代码按当前契约使用；本次不涉及严格统计、跨revision预算或代码沙箱。'],
sources={V+'report.py':[(1,70)],V+'contracts.py':[(1,75)],V+'combat_worker.py':[(52,108)],V+'store.py':[(61,140)]},
mutations={V+'report.py':[('expected = {(policy, seed) for policy in plan.policies for seed in plan.seeds}',
                         'expected = frozenset((policy, seed) for policy in plan.policies for seed in plan.seeds)')]},
issues=[], non_issues=['frozenset与set按内容比较相等，不会让所有合法收据失败。','未新增缺陷；本题候选仅改变集合是否可变。'])
]


def recovery_log():
    lines = ['# 受控诊断fixture；按相同代码分支构造，非线上自然故障证据。',
             '# 时间为逻辑时钟，hash缩写只用于日志展示，数据库中保存完整hash。']
    for i in range(1, 7):
        rid = f'probe_{i:02d}'
        lines.extend([f'{i:03d}.010 {rid} prepare plan_hash=p{i:02d} seeds=[11,12] policies=[balanced] battles=4',
                      f'{i:03d}.020 {rid} graph node=validate passed=true source_fingerprint=stable',
                      f'{i:03d}.030 {rid} graph interrupt=authorize checkpoint_saved=true',
                      f'{i:03d}.040 {rid} operator decide request_id={rid} plan_hash=p{i:02d} approve=true',
                      f'{i:03d}.050 {rid} domain status=running charged_battles=4',
                      f'{i:03d}.060 {rid} worker_pair policy=balanced seed=11 baseline=win candidate=win',
                      f'{i:03d}.070 {rid} worker_pair policy=balanced seed=12 baseline=win candidate=win',
                      f'{i:03d}.080 {rid} domain status=completed receipt_hash=r{i:02d}',
                      f'{i:03d}.090 {rid} graph checkpoint_saved=true report=DESCRIPTIVE_ONLY'])
    lines.extend(['017.010 interrupted prepare plan_hash=p17 battles=4',
                  '017.020 interrupted operator decide plan_hash=p17 approve=true',
                  '017.030 interrupted domain status=running charged_battles=4 result_json=null',
                  '017.040 interrupted worker spawned pid=fixture-17',
                  '017.050 interrupted process_exit=74 checkpoint_next=experiment worker_outcome=unavailable',
                  '018.010 interrupted new_process resume request_id=interrupted',
                  '018.020 interrupted checkpoint next=experiment interrupt_count=0',
                  '018.030 interrupted domain status=running charged_battles=4 result_json=null',
                  '018.040 interrupted graph enters experiment',
                  '018.050 interrupted diagnostic_boundary=before_claim',
                  '# 本次日志在恢复准入前停止；请由候选源码推导后续是否安全。'])
    return '\n'.join(lines)+'\n'


def prepare():
    manifest = dict(schema_version=1, version='coding-collaboration-tasks-v1',
                    scope='bounded frozen candidate review; no patch generation; no live model or Unity',
                    mutation_notice='Benchmark injections, not claims of existing repository defects.',
                    freeze_policy='confirmation packets/oracles fixed before any model outputs; hash changes require new dataset version',
                    hash_definition='SHA256 of exact UTF-8 file bytes; source hashes use original file bytes', tasks=[])
    for task in TASKS:
        tid = task['id']; public = ROOT/'tasks/public'/tid; private = ROOT/'oracle/private'/tid
        sources = {p: raw(p).decode('utf-8-sig').replace('\r\n','\n') for p in task['sources']}
        candidates = dict(sources)
        diffs = []
        for path, mutations in task['mutations'].items():
            for before, after in mutations:
                if candidates[path].count(before) != 1:
                    raise ValueError(f'Expected unique mutation at {tid}: {path}: {before}')
                candidates[path] = candidates[path].replace(before, after)
            diffs.extend(difflib.unified_diff(sources[path].splitlines(True), candidates[path].splitlines(True),
                                            fromfile='a/'+path, tofile='b/'+path, n=3))
        parts = [f'# {tid} — {task["title"]}\n', task['request'],
                 '\n这是评测专用候选：从真实只读源码构造，可能含benchmark注入修改，也可能无缺陷。它不是对原仓库已有缺陷的断言。各条件获得完全相同的有限资料包。请仅用此包完成评审，不查找隐藏真值或包外文件。',
                 '\n## 业务规则与范围\n', '\n'.join(f'{i}. {r}' for i,r in enumerate(task['rules'],1)),
                 '\n## 输出\n只返回JSON对象：{"findings":[{"path":"仓库名/相对路径","line":候选行号,"title":"简短标题","why":"根因与业务后果","evidence":"源码链路及具体触发例子","fix":"最小修正建议"}]}。没有问题时findings为空数组。按独立根因合并重复现象，引用下文候选文件行号。证据要能从包内核对；不要填自信度、issue_id或猜测评分规则。',
                 '\n## 冻结候选diff\n```diff\n'+''.join(diffs)+'```\n',
                 '\n## 相关源码\n以下均为应用上述diff后的候选版本；没有出现在diff的文件/行与真实基线相同。行号对应候选完整文件，不是片段内编号。']
        for path, ranges in task['sources'].items():
            code = candidates[path].splitlines()
            for start,end in ranges:
                end = min(end,len(code))
                if start>end: continue
                numbered = '\n'.join(f'{i:04d} | {code[i-1]}' for i in range(start,end+1))
                parts.append(f'\n### {path}:{start}-{end}\n```{ "csharp" if path.endswith(".cs") else "python"}\n{numbered}\n```')
            filename = path.replace('/','__')
            frozen_write(private/'baseline'/filename,sources[path])
            frozen_write(private/'candidate'/filename,candidates[path])
        if task.get('logs'):
            parts.append('\n## 诊断记录\n```text\n'+recovery_log()+'```')
        packet = '\n'.join(parts)+'\n'
        issues = []
        for spec in task['issues']:
            spec = dict(spec); path=spec.pop('path'); needle=spec.pop('needle')
            hits=[i for i,line in enumerate(candidates[path].splitlines(),1) if needle in line]
            if len(hits)!=1: raise ValueError((tid,spec['issue_id'],needle,hits))
            spec['allowed_locations']=[dict(path=path,start_line=max(1,hits[0]-2),end_line=hits[0]+3)]
            issues.append(spec)
        oracle = dict(schema_version=1,task_id=tid,split=task['split'],
                      ground_truth_kind='benchmark_injected' if issues else 'clean_control',
                      exhaustive_within_scope=True,scope=task['request'],issues=issues,
                      non_issues=task['non_issues'], packet_sha256=digest(packet),
                      source_hashes={p:digest(raw(p)) for p in sources},
                      candidate_hashes={p:digest(candidates[p]) for p in candidates},
                      verification='oracle/private/verify_oracles.py; actual Python functions + source-verifiable C# projection; no Unity claim')
        metadata = dict(schema_version=1,task_id=tid,split=task['split'],title=task['title'],
                        packet_path=f'tasks/public/{tid}/packet.md',packet_sha256=digest(packet),
                        packet_characters=len(packet),source_paths=list(sources),
                        output_schema={'findings':[dict(path='string',line='integer',title='string',why='string',evidence='string',fix='string')]})
        frozen_write(public/'packet.md',packet)
        frozen_write(public/'task.json',dump(metadata))
        frozen_write(private/'oracle.json',dump(oracle))
        manifest['tasks'].append(dict(**metadata, oracle_path=f'oracle/private/{tid}/oracle.json',oracle_sha256=digest(dump(oracle))))
    frozen_write(ROOT/'oracle/private/manifest.json',dump(manifest))
    # Public manifest deliberately excludes oracle paths, source hashes and issue counts.
    frozen_write(ROOT/'tasks/public/manifest.json',dump(dict(schema_version=1,version=manifest['version'],tasks=[{k:v for k,v in t.items() if not k.startswith('oracle_')} for t in manifest['tasks']])))
    print(dump({'tasks':[{k:t[k] for k in ('task_id','split','packet_characters','packet_sha256')} for t in manifest['tasks']],
                'manifest_sha256':digest(dump(manifest))}))


if __name__ == '__main__':
    prepare()
