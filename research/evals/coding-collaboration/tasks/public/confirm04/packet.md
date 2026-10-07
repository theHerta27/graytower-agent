# confirm04 — 配对清单不可变集合整理

候选把报告中的预期pair集合明确为不可变集合，以便代码表达“冻结清单”。请只审查这次改动是否改变当前授权、结果校验或报告计算。可以没有发现；不要把原有代码的拓展建议算成本次回归。

这是评测专用候选：从真实只读源码构造，可能含benchmark注入修改，也可能无缺陷。它不是对原仓库已有缺陷的断言。各条件获得完全相同的有限资料包。请仅用此包完成评审，不查找隐藏真值或包外文件。

## 业务规则与范围

1. expected仅用于len和与set(actual)比较；每个(policy,seed)恰好一行。
2. frozenset和set对相同元素按集合内容判等；冻结计划中的policies/seeds都是可哈希字符串/整数。
3. 未变更代码按当前契约使用；本次不涉及严格统计、跨revision预算或代码沙箱。

## 输出
只返回JSON对象：{"findings":[{"path":"仓库名/相对路径","line":候选行号,"title":"简短标题","why":"根因与业务后果","evidence":"源码链路及具体触发例子","fix":"最小修正建议"}]}。没有问题时findings为空数组。按独立根因合并重复现象，引用下文候选文件行号。证据要能从包内核对；不要填自信度、issue_id或猜测评分规则。

## 冻结候选diff
```diff
--- a/mihoyo-agent-project/src/agent_workbench/verification/report.py
+++ b/mihoyo-agent-project/src/agent_workbench/verification/report.py
@@ -11,7 +11,7 @@
         raise ValueError("receipt plan hash mismatch")
     if result.get("game_fingerprint") != plan.game_fingerprint:
         raise ValueError("game fingerprint mismatch")
-    expected = {(policy, seed) for policy in plan.policies for seed in plan.seeds}
+    expected = frozenset((policy, seed) for policy in plan.policies for seed in plan.seeds)
     rows = result.get("rows", [])
     actual = [(r["policy"], r["seed"]) for r in rows]
     if len(actual) != len(expected) or set(actual) != expected:
```


## 相关源码
以下均为应用上述diff后的候选版本；没有出现在diff的文件/行与真实基线相同。行号对应候选完整文件，不是片段内编号。

### mihoyo-agent-project/src/agent_workbench/verification/report.py:1-43
```python
0001 | """Descriptive, paired evidence. This module cannot certify population noninferiority."""
0002 | from collections import Counter
0003 | from fractions import Fraction
0004 | from statistics import median
0005 | 
0006 | from .contracts import ExperimentPlan, fingerprint
0007 | 
0008 | 
0009 | def build_report(plan: ExperimentPlan, result: dict) -> dict:
0010 |     if result.get("plan_hash") != fingerprint(plan):
0011 |         raise ValueError("receipt plan hash mismatch")
0012 |     if result.get("game_fingerprint") != plan.game_fingerprint:
0013 |         raise ValueError("game fingerprint mismatch")
0014 |     expected = frozenset((policy, seed) for policy in plan.policies for seed in plan.seeds)
0015 |     rows = result.get("rows", [])
0016 |     actual = [(r["policy"], r["seed"]) for r in rows]
0017 |     if len(actual) != len(expected) or set(actual) != expected:
0018 |         raise ValueError("missing, duplicate or foreign paired result")
0019 |     groups = {}
0020 |     for policy in plan.policies:
0021 |         data = [r for r in rows if r["policy"] == policy]
0022 |         ratios = []
0023 |         transitions = Counter()
0024 |         for row in data:
0025 |             b, c = row["baseline"], row["candidate"]
0026 |             if b["outcome"] not in ("win", "loss", "timeout") or c["outcome"] not in ("win", "loss", "timeout"):
0027 |                 raise ValueError("invalid battle outcome")
0028 |             bav, cav = Fraction(b["elapsed_av"]), Fraction(c["elapsed_av"])
0029 |             if bav <= 0 or cav <= 0:
0030 |                 raise ValueError("invalid nonpositive battle AV")
0031 |             transitions[f'{b["outcome"]}->{c["outcome"]}'] += 1
0032 |             if b["outcome"] == c["outcome"] == "win":
0033 |                 ratios.append(cav / bav)
0034 |         bw = sum(r["baseline"]["outcome"] == "win" for r in data)
0035 |         cw = sum(r["candidate"]["outcome"] == "win" for r in data)
0036 |         groups[policy] = dict(pairs=len(data), baseline_win_rate=bw / len(data),
0037 |                               candidate_win_rate=cw / len(data), transitions=dict(transitions),
0038 |                               common_wins=len(ratios), paired_av_ratio_median=float(median(ratios)) if ratios else None,
0039 |                               no_observed_win_regressions=not any(r["baseline"]["outcome"] == "win" and
0040 |                                                                r["candidate"]["outcome"] != "win" for r in data))
0041 |     return dict(profile=plan.profile, verdict="DESCRIPTIVE_ONLY", plan_hash=fingerprint(plan),
0042 |                 simulated_battles=plan.battles, policies=groups,
0043 |                 limitation="固定小样本描述；不证明总体胜率、严格非劣或玩家通关时间改善。未经人工采纳不修改游戏。")
```

### mihoyo-agent-project/src/agent_workbench/verification/contracts.py:1-65
```python
0001 | """Frozen business input, independent of graph state and game implementation."""
0002 | import hashlib
0003 | import json
0004 | from typing import Literal, Protocol
0005 | 
0006 | from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator
0007 | 
0008 | 
0009 | def canonical(value) -> str:
0010 |     if isinstance(value, BaseModel):
0011 |         value = value.model_dump(mode="json")
0012 |     return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
0013 | 
0014 | 
0015 | def fingerprint(value) -> str:
0016 |     return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()
0017 | 
0018 | 
0019 | class ClosedModel(BaseModel):
0020 |     model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
0021 | 
0022 | 
0023 | class Bound(ClosedModel):
0024 |     minimum: float
0025 |     maximum: float
0026 | 
0027 | 
0028 | class Change(ClosedModel):
0029 |     path: str = Field(min_length=1, max_length=160)
0030 |     value: StrictInt | StrictFloat
0031 | 
0032 | 
0033 | class ExperimentPlan(ClosedModel):
0034 |     schema_version: Literal["experiment-v1"] = "experiment-v1"
0035 |     request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
0036 |     request: str = Field(min_length=1, max_length=4000)
0037 |     game_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
0038 |     changes: list[Change] = Field(min_length=1, max_length=10)
0039 |     bounds: dict[str, Bound]
0040 |     seeds: list[StrictInt] = Field(min_length=1, max_length=20)
0041 |     policies: list[Literal["balanced", "survival", "basic_only"]] = Field(min_length=1, max_length=3)
0042 |     max_battles: int = Field(ge=1, le=120, strict=True)
0043 |     profile: Literal["descriptive-v1"] = "descriptive-v1"
0044 | 
0045 |     @model_validator(mode="after")
0046 |     def bounded_manifest(self):
0047 |         if len(set(self.seeds)) != len(self.seeds) or any(type(s) is not int or not 0 <= s < 2**63 for s in self.seeds):
0048 |             raise ValueError("seeds must be unique nonnegative integers")
0049 |         if len(set(self.policies)) != len(self.policies):
0050 |             raise ValueError("policies must be unique")
0051 |         if self.battles > self.max_battles:
0052 |             raise ValueError("battle budget is smaller than the frozen paired manifest")
0053 |         if not 1 <= len(self.bounds) <= 10 or any(b.minimum > b.maximum for b in self.bounds.values()):
0054 |             raise ValueError("invalid authorized bounds")
0055 |         return self
0056 | 
0057 |     @property
0058 |     def battles(self) -> int:
0059 |         return 2 * len(self.seeds) * len(self.policies)
0060 | 
0061 | 
0062 | class GamePort(Protocol):
0063 |     """One concrete game adapter today, not a claim of arbitrary-game support."""
0064 |     def validate(self, plan: ExperimentPlan) -> dict: ...
0065 |     def execute(self, plan: ExperimentPlan) -> dict: ...
```

### mihoyo-agent-project/src/agent_workbench/verification/combat_worker.py:52-108
```python
0052 | 
0053 | def work(root: Path, operation: str, plan: ExperimentPlan) -> dict:
0054 |     if source_fingerprint(root) != plan.game_fingerprint:
0055 |         raise ValueError("game source changed since plan freeze")
0056 |     sys.path[:0] = [str(root / "game-core"), str(root / "services/verification-agent")]
0057 |     from combat_core.v2.config import load_bundle, load_scenario, config_hash
0058 |     from combat_core.v2.contracts import CombatBundle, Scenario
0059 |     from combat_core.v2.report import summarize
0060 |     from combat_core.v2.simulation import simulate
0061 |     from verification_agent.v2.models import Authorization, TaskSpec
0062 |     from verification_agent.v2.policy import apply_changes, validate_candidate
0063 | 
0064 |     base = load_bundle(root / "configs/combat/v2/baseline.json")
0065 |     scenario = load_scenario(root / "configs/combat/v2/scenario.json")
0066 |     bounds = {key: value.model_dump() for key, value in plan.bounds.items()}
0067 |     # Legacy policy consumes a Spec. Its criterion here is a DESCRIPTIVE check only;
0068 |     # the new report never promotes it to a population statistical verdict.
0069 |     criterion = dict(metric="win_rate_delta", op="gte", target=0, policy=plan.policies[0])
0070 |     auth = Authorization(actor="local-operator", note=plan.request, scope=bounds,
0071 |                          seeds=plan.seeds, policies=plan.policies, min_samples=1,
0072 |                          max_model_calls=0, max_simulations=plan.max_battles, required_criteria=[criterion])
0073 |     spec = TaskSpec(goal=plan.request, mutable_scope=list(bounds), parameter_constraints=bounds,
0074 |                     acceptance_criteria=[criterion])
0075 |     candidate, diff = apply_changes(base.model_dump(), [c.model_dump() for c in plan.changes], auth, spec)
0076 |     validation = validate_candidate(base.model_dump(), candidate, auth, spec)
0077 |     if not validation["passed"]:
0078 |         raise ValueError(canonical(validation))
0079 |     if operation == "validate":
0080 |         return validation
0081 |     candidate = CombatBundle.model_validate(candidate)
0082 |     rows = []
0083 |     for policy in plan.policies:
0084 |         for seed in plan.seeds:
0085 |             case = Scenario.model_validate({**scenario.model_dump(), "seed": seed, "strategy": policy})
0086 |             pair = dict(seed=seed, policy=policy)
0087 |             for label, bundle in (("baseline", base), ("candidate", candidate)):
0088 |                 trace = simulate(bundle, case)
0089 |                 pair[label] = summarize(trace).model_dump(mode="json")
0090 |                 pair[label]["trace_sha256"] = hashlib.sha256(canonical(trace).encode("utf-8")).hexdigest()
0091 |             rows.append(pair)
0092 |     if source_fingerprint(root) != plan.game_fingerprint:
0093 |         raise ValueError("game source changed during experiment; result not accepted")
0094 |     return dict(rows=rows, diff=diff, validation=validation, game_fingerprint=plan.game_fingerprint,
0095 |                 plan_hash=fingerprint(plan), baseline_hash=config_hash(base), candidate_hash=config_hash(candidate),
0096 |                 scenario_hash=fingerprint(scenario),
0097 |                 worker_python=sys.version, provenance="real-combat-core; no model; no full traces stored")
0098 | 
0099 | 
0100 | def main():
0101 |     parser = argparse.ArgumentParser()
0102 |     parser.add_argument("operation", choices=["validate", "execute"])
0103 |     parser.add_argument("--game-root", type=Path, required=True)
0104 |     args = parser.parse_args()
0105 |     p = ExperimentPlan.model_validate_json(sys.stdin.read())
0106 |     print(canonical(work(args.game_root.resolve(strict=True), args.operation, p)))
0107 | 
0108 | 
```

### mihoyo-agent-project/src/agent_workbench/verification/store.py:61-116
```python
0061 |                          (plan.request_id, canonical(plan), fingerprint(plan)))
0062 |             row = conn.execute("SELECT plan_hash FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
0063 |             if row[0] != fingerprint(plan):
0064 |                 raise ValueError("request ID payload conflict")
0065 | 
0066 |     def get(self, request_id: str) -> dict:
0067 |         with self.connection() as conn:
0068 |             row = conn.execute("SELECT * FROM runs WHERE request_id=?", (request_id,)).fetchone()
0069 |         if row is None:
0070 |             raise ValueError("unknown request ID")
0071 |         result = dict(row)
0072 |         plan = ExperimentPlan.model_validate_json(result["plan_json"])
0073 |         if fingerprint(plan) != result["plan_hash"]:
0074 |             raise ValueError("plan integrity failure")
0075 |         if result["result_json"] is not None and fingerprint(json.loads(result["result_json"])) != result["result_hash"]:
0076 |             raise ValueError("receipt integrity failure")
0077 |         return result
0078 | 
0079 |     def plan(self, request_id: str) -> ExperimentPlan:
0080 |         return ExperimentPlan.model_validate_json(self.get(request_id)["plan_json"])
0081 | 
0082 |     def decide(self, request_id: str, plan_hash: str, approve: bool):
0083 |         with self.connection() as conn:
0084 |             conn.execute("BEGIN IMMEDIATE")
0085 |             row = conn.execute("SELECT plan_hash,approved FROM runs WHERE request_id=?", (request_id,)).fetchone()
0086 |             if row is None or row[0] != plan_hash:
0087 |                 raise ValueError("approval plan hash mismatch")
0088 |             if row[1] is not None and row[1] != int(approve):
0089 |                 raise ValueError("approval decision is immutable; create a new reviewed plan")
0090 |             conn.execute("UPDATE runs SET approved=? WHERE request_id=?", (int(approve), request_id))
0091 | 
0092 |     def claim(self, plan: ExperimentPlan):
0093 |         with self.connection() as conn:
0094 |             conn.execute("BEGIN IMMEDIATE")
0095 |             row = conn.execute("SELECT * FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
0096 |             if row is None or row["plan_hash"] != fingerprint(plan) or row["approved"] != 1:
0097 |                 raise ValueError("missing matching approval")
0098 |             if row["job_status"] != "new":
0099 |                 raise RuntimeError("worker outcome unknown; reconcile receipt, no automatic retry")
0100 |             conn.execute("UPDATE runs SET job_status='running',charged_battles=? WHERE request_id=?",
0101 |                          (plan.battles, plan.request_id))
0102 | 
0103 |     def complete(self, plan: ExperimentPlan, result: dict):
0104 |         from .report import build_report
0105 |         build_report(plan, result)  # Check manifest before acknowledging a completed experiment.
0106 |         with self.connection() as conn:
0107 |             conn.execute("BEGIN IMMEDIATE")
0108 |             row = conn.execute("SELECT * FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
0109 |             if row is None or row["plan_hash"] != fingerprint(plan) or row["approved"] != 1:
0110 |                 raise ValueError("receipt does not match approved plan")
0111 |             if row["job_status"] == "completed" and row["result_hash"] == fingerprint(result):
0112 |                 return
0113 |             if row["job_status"] != "running":
0114 |                 raise ValueError("receipt is immutable or operation was never admitted")
0115 |             conn.execute("UPDATE runs SET job_status='completed',result_json=?,result_hash=? WHERE request_id=?",
0116 |                          (canonical(result), fingerprint(result), plan.request_id))
```
