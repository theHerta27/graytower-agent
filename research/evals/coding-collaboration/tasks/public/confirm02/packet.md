# confirm02 — 配对报告和源码冻结评审

为精简结果报告和源码扫描，候选调整了配对集合校验、AV指标和游戏指纹文件选择。请判断是否仍能拒绝重复结果、保持指标方向，以及把本次运行实际导入的规则源码全部纳入冻结。无需评价统计显著性或提出更多样本。

这是评测专用候选：从真实只读源码构造，可能含benchmark注入修改，也可能无缺陷。它不是对原仓库已有缺陷的断言。各条件获得完全相同的有限资料包。请仅用此包完成评审，不查找隐藏真值或包外文件。

## 业务规则与范围

1. 一个(policy,seed)恰好代表一场baseline与一场candidate，结果行不能重复，即使重复行完全相同。
2. paired_av_ratio_median定义为共同获胜样本的candidate.elapsed_av / baseline.elapsed_av的中位数；小于1表示候选更快。
3. game-core/combat_core及services/verification-agent/verification_agent中的所有Python源文件均属于冻结输入，包含包入口__init__.py；导入包时入口也可能执行代码。
4. 报告仍仅为DESCRIPTIVE_ONLY，不应据此宣称总体非劣；此项并非本候选需要修复的缺陷。

## 输出
只返回JSON对象：{"findings":[{"path":"仓库名/相对路径","line":候选行号,"title":"简短标题","why":"根因与业务后果","evidence":"源码链路及具体触发例子","fix":"最小修正建议"}]}。没有问题时findings为空数组。按独立根因合并重复现象，引用下文候选文件行号。证据要能从包内核对；不要填自信度、issue_id或猜测评分规则。

## 冻结候选diff
```diff
--- a/mihoyo-agent-project/src/agent_workbench/verification/report.py
+++ b/mihoyo-agent-project/src/agent_workbench/verification/report.py
@@ -14,7 +14,7 @@
     expected = {(policy, seed) for policy in plan.policies for seed in plan.seeds}
     rows = result.get("rows", [])
     actual = [(r["policy"], r["seed"]) for r in rows]
-    if len(actual) != len(expected) or set(actual) != expected:
+    if set(actual) != expected:
         raise ValueError("missing, duplicate or foreign paired result")
     groups = {}
     for policy in plan.policies:
@@ -30,7 +30,7 @@
                 raise ValueError("invalid nonpositive battle AV")
             transitions[f'{b["outcome"]}->{c["outcome"]}'] += 1
             if b["outcome"] == c["outcome"] == "win":
-                ratios.append(cav / bav)
+                ratios.append(bav / cav)
         bw = sum(r["baseline"]["outcome"] == "win" for r in data)
         cw = sum(r["candidate"]["outcome"] == "win" for r in data)
         groups[policy] = dict(pairs=len(data), baseline_win_rate=bw / len(data),
--- a/mihoyo-agent-project/src/agent_workbench/verification/combat_worker.py
+++ b/mihoyo-agent-project/src/agent_workbench/verification/combat_worker.py
@@ -16,7 +16,7 @@
 
 def source_fingerprint(root: Path) -> str:
     roots = [root / "game-core" / "combat_core", root / "services" / "verification-agent" / "verification_agent"]
-    paths = [p for folder in roots for p in folder.rglob("*.py")]
+    paths = [p for folder in roots for p in folder.rglob("*.py") if p.name != "__init__.py"]
     paths += [root / "configs/combat/v2/baseline.json", root / "configs/combat/v2/scenario.json"]
     if not paths or not all(p.is_file() for p in paths):
         raise ValueError("incomplete game checkout")
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
0014 |     expected = {(policy, seed) for policy in plan.policies for seed in plan.seeds}
0015 |     rows = result.get("rows", [])
0016 |     actual = [(r["policy"], r["seed"]) for r in rows]
0017 |     if set(actual) != expected:
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
0033 |                 ratios.append(bav / cav)
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

### mihoyo-agent-project/src/agent_workbench/verification/combat_worker.py:1-110
```python
0001 | """Read-only adapter to the trusted combat-foundation checkout.
0002 | 
0003 | Runs only closed numeric candidates. This is NOT a sandbox for generated code.
0004 | No model credential, shell command, or dynamically chosen module is accepted.
0005 | """
0006 | import argparse
0007 | import hashlib
0008 | import json
0009 | import os
0010 | from pathlib import Path
0011 | import subprocess
0012 | import sys
0013 | 
0014 | from .contracts import ExperimentPlan, canonical, fingerprint
0015 | 
0016 | 
0017 | def source_fingerprint(root: Path) -> str:
0018 |     roots = [root / "game-core" / "combat_core", root / "services" / "verification-agent" / "verification_agent"]
0019 |     paths = [p for folder in roots for p in folder.rglob("*.py") if p.name != "__init__.py"]
0020 |     paths += [root / "configs/combat/v2/baseline.json", root / "configs/combat/v2/scenario.json"]
0021 |     if not paths or not all(p.is_file() for p in paths):
0022 |         raise ValueError("incomplete game checkout")
0023 |     h = hashlib.sha256()
0024 |     for path in sorted(paths):
0025 |         h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
0026 |     return h.hexdigest()
0027 | 
0028 | 
0029 | class CombatAdapter:
0030 |     def __init__(self, root: Path, python: Path | None = None):
0031 |         self.root = root.resolve(strict=True)
0032 |         self.python = python or Path(sys.executable)
0033 | 
0034 |     def _call(self, operation: str, plan: ExperimentPlan) -> dict:
0035 |         # Construct an allowlisted environment rather than copying developer credentials.
0036 |         env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}}
0037 |         env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]), PYTHONUTF8="1",
0038 |                    LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
0039 |         proc = subprocess.run([str(self.python), "-m", "agent_workbench.verification.combat_worker",
0040 |                                operation, "--game-root", str(self.root)], input=canonical(plan),
0041 |                               text=True, encoding="utf-8", capture_output=True, env=env, timeout=180)
0042 |         if proc.returncode:
0043 |             raise ValueError("game worker rejected input: " + proc.stderr[-2000:])
0044 |         return json.loads(proc.stdout)
0045 | 
0046 |     def validate(self, plan):
0047 |         return self._call("validate", plan)
0048 | 
0049 |     def execute(self, plan):
0050 |         return self._call("execute", plan)
0051 | 
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
0109 | if __name__ == "__main__":
0110 |     main()
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

### mihoyo-agent-project/src/agent_workbench/verification/store.py:104-116
```python
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
