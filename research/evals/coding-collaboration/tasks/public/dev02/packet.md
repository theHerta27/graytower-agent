# dev02 — 实验恢复与账本对账调查

一次进程中断后，实验恢复偶发接受了旧批准或不完整结果。请结合冻结候选及诊断记录，审查领域账本的批准、worker准入、收据提交三段边界。checkpoint只用于路由，不能当作已经完成实验的事实。不要推断未展示的网络或数据库故障。

这是评测专用候选：从真实只读源码构造，可能含benchmark注入修改，也可能无缺陷。它不是对原仓库已有缺陷的断言。各条件获得完全相同的有限资料包。请仅用此包完成评审，不查找隐藏真值或包外文件。

## 业务规则与范围

1. 批准必须与同一request_id的不可变plan_hash完全匹配。API调用者可能拿着旧版本/另一个计划的hash，不能仅凭ID批准。
2. worker被准入后即保守计入完整冻结场次数。进程死于execute中时，running表示外部结果未知，没有可对账领域收据时必须拒绝自动重试。
3. 完整收据必须绑定plan_hash、game_fingerprint，且每个(policy,seed)恰有一个baseline/candidate结果；complete提交前必须验证。
4. 领域completed后checkpoint未同步可安全恢复；既有completed账本应避免再次执行或再次扣账。日志中的时钟、checkpoint节点名均不构成批准。

## 输出
只返回JSON对象：{"findings":[{"path":"仓库名/相对路径","line":候选行号,"title":"简短标题","why":"根因与业务后果","evidence":"源码链路及具体触发例子","fix":"最小修正建议"}]}。没有问题时findings为空数组。按独立根因合并重复现象，引用下文候选文件行号。证据要能从包内核对；不要填自信度、issue_id或猜测评分规则。

## 冻结候选diff
```diff
--- a/mihoyo-agent-project/src/agent_workbench/verification/store.py
+++ b/mihoyo-agent-project/src/agent_workbench/verification/store.py
@@ -83,7 +83,7 @@
         with self.connection() as conn:
             conn.execute("BEGIN IMMEDIATE")
             row = conn.execute("SELECT plan_hash,approved FROM runs WHERE request_id=?", (request_id,)).fetchone()
-            if row is None or row[0] != plan_hash:
+            if row is None:
                 raise ValueError("approval plan hash mismatch")
             if row[1] is not None and row[1] != int(approve):
                 raise ValueError("approval decision is immutable; create a new reviewed plan")
@@ -95,14 +95,14 @@
             row = conn.execute("SELECT * FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
             if row is None or row["plan_hash"] != fingerprint(plan) or row["approved"] != 1:
                 raise ValueError("missing matching approval")
-            if row["job_status"] != "new":
+            if row["job_status"] not in ("new", "running"):
                 raise RuntimeError("worker outcome unknown; reconcile receipt, no automatic retry")
             conn.execute("UPDATE runs SET job_status='running',charged_battles=? WHERE request_id=?",
                          (plan.battles, plan.request_id))
 
     def complete(self, plan: ExperimentPlan, result: dict):
         from .report import build_report
-        build_report(plan, result)  # Check manifest before acknowledging a completed experiment.
+        # The worker has already produced a result; defer reporting to show().
         with self.connection() as conn:
             conn.execute("BEGIN IMMEDIATE")
             row = conn.execute("SELECT * FROM runs WHERE request_id=?", (plan.request_id,)).fetchone()
```


## 相关源码
以下均为应用上述diff后的候选版本；没有出现在diff的文件/行与真实基线相同。行号对应候选完整文件，不是片段内编号。

### mihoyo-agent-project/src/agent_workbench/verification/store.py:38-116
```python
0038 |     def __init__(self, folder: Path):
0039 |         folder.mkdir(parents=True, exist_ok=True)
0040 |         self.path = folder / "domain.sqlite"
0041 |         with self.connection() as conn:
0042 |             conn.execute("""CREATE TABLE IF NOT EXISTS runs (
0043 |                 request_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, plan_hash TEXT NOT NULL,
0044 |                 approved INTEGER, charged_battles INTEGER NOT NULL DEFAULT 0,
0045 |                 job_status TEXT NOT NULL DEFAULT 'new', result_json TEXT, result_hash TEXT)""")
0046 | 
0047 |     @contextmanager
0048 |     def connection(self):
0049 |         conn = sqlite3.connect(self.path, timeout=10)
0050 |         conn.row_factory = sqlite3.Row
0051 |         conn.execute("PRAGMA synchronous=FULL")
0052 |         try:
0053 |             with conn:
0054 |                 yield conn
0055 |         finally:
0056 |             conn.close()
0057 | 
0058 |     def create(self, plan: ExperimentPlan):
0059 |         with self.connection() as conn:
0060 |             conn.execute("INSERT OR IGNORE INTO runs(request_id,plan_json,plan_hash) VALUES(?,?,?)",
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
0086 |             if row is None:
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
0098 |             if row["job_status"] not in ("new", "running"):
0099 |                 raise RuntimeError("worker outcome unknown; reconcile receipt, no automatic retry")
0100 |             conn.execute("UPDATE runs SET job_status='running',charged_battles=? WHERE request_id=?",
0101 |                          (plan.battles, plan.request_id))
0102 | 
0103 |     def complete(self, plan: ExperimentPlan, result: dict):
0104 |         from .report import build_report
0105 |         # The worker has already produced a result; defer reporting to show().
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

### mihoyo-agent-project/src/agent_workbench/verification/workflow.py:37-55
```python
0037 |         def authorize(state):
0038 |             row = self.store.get(state["request_id"])
0039 |             if row["approved"] is None:
0040 |                 interrupt({"plan_hash": row["plan_hash"], "plan": json.loads(row["plan_json"])})
0041 |                 row = self.store.get(state["request_id"])
0042 |             if row["approved"] is None:
0043 |                 raise ValueError("resume is not an approval")
0044 |             return {"approved": bool(row["approved"])}
0045 | 
0046 |         def experiment(state):
0047 |             p = self.store.plan(state["request_id"])
0048 |             row = self.store.get(p.request_id)
0049 |             if row["job_status"] != "completed":
0050 |                 checked_validate(p)
0051 |                 self.store.claim(p)
0052 |                 result = self.game.execute(p)
0053 |                 self.store.complete(p, result)
0054 |             return {"receipt_hash": self.store.get(p.request_id)["result_hash"]}
0055 | 
```

### mihoyo-agent-project/src/agent_workbench/verification/workflow.py:67-104
```python
0067 |         with driver_lock(self.folder):
0068 |             self.store.create(plan)
0069 |             return self._drive(plan.request_id)
0070 | 
0071 |     def decide(self, request_id: str, plan_hash: str, approve: bool):
0072 |         with driver_lock(self.folder):
0073 |             self.store.decide(request_id, plan_hash, approve)
0074 |             return self._drive(request_id)
0075 | 
0076 |     def resume(self, request_id: str):
0077 |         with driver_lock(self.folder):
0078 |             return self._drive(request_id)
0079 | 
0080 |     def _drive(self, request_id: str):
0081 |         row = self.store.get(request_id)
0082 |         with SqliteSaver.from_conn_string(str(self.folder / "checkpoint.sqlite")) as saver:
0083 |             graph = self.graph(saver)
0084 |             config = {"configurable": {"thread_id": request_id}, "recursion_limit": 12}
0085 |             snapshot = graph.get_state(config)
0086 |             if not snapshot.values:
0087 |                 graph.invoke({"request_id": request_id}, config, durability="sync")
0088 |                 snapshot = graph.get_state(config)
0089 |             if snapshot.interrupts and row["approved"] is not None:
0090 |                 graph.invoke(Command(resume={item.id: "reconcile-domain-decision" for item in snapshot.interrupts}),
0091 |                              config, durability="sync")
0092 |             elif snapshot.next and not snapshot.interrupts:
0093 |                 graph.invoke(None, config, durability="sync")
0094 |         return self.show(request_id)
0095 | 
0096 |     def show(self, request_id: str):
0097 |         row = self.store.get(request_id)
0098 |         status = "awaiting_approval" if row["approved"] is None else "rejected" if not row["approved"] else row["job_status"]
0099 |         value = dict(request_id=request_id, status=status, plan_hash=row["plan_hash"],
0100 |                      charged_battles=row["charged_battles"], plan=json.loads(row["plan_json"]))
0101 |         if row["result_json"] is not None:
0102 |             value.update(receipt_hash=row["result_hash"],
0103 |                          report=build_report(self.store.plan(request_id), json.loads(row["result_json"])))
0104 |         return value
```

### mihoyo-agent-project/src/agent_workbench/verification/report.py:9-23
```python
0009 | def build_report(plan: ExperimentPlan, result: dict) -> dict:
0010 |     if result.get("plan_hash") != fingerprint(plan):
0011 |         raise ValueError("receipt plan hash mismatch")
0012 |     if result.get("game_fingerprint") != plan.game_fingerprint:
0013 |         raise ValueError("game fingerprint mismatch")
0014 |     expected = {(policy, seed) for policy in plan.policies for seed in plan.seeds}
0015 |     rows = result.get("rows", [])
0016 |     actual = [(r["policy"], r["seed"]) for r in rows]
0017 |     if len(actual) != len(expected) or set(actual) != expected:
0018 |         raise ValueError("missing, duplicate or foreign paired result")
0019 |     groups = {}
0020 |     for policy in plan.policies:
0021 |         data = [r for r in rows if r["policy"] == policy]
0022 |         ratios = []
0023 |         transitions = Counter()
```

### mihoyo-agent-project/src/agent_workbench/verification/contracts.py:20-65
```python
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

## 诊断记录
```text
# 受控诊断fixture；按相同代码分支构造，非线上自然故障证据。
# 时间为逻辑时钟，hash缩写只用于日志展示，数据库中保存完整hash。
001.010 probe_01 prepare plan_hash=p01 seeds=[11,12] policies=[balanced] battles=4
001.020 probe_01 graph node=validate passed=true source_fingerprint=stable
001.030 probe_01 graph interrupt=authorize checkpoint_saved=true
001.040 probe_01 operator decide request_id=probe_01 plan_hash=p01 approve=true
001.050 probe_01 domain status=running charged_battles=4
001.060 probe_01 worker_pair policy=balanced seed=11 baseline=win candidate=win
001.070 probe_01 worker_pair policy=balanced seed=12 baseline=win candidate=win
001.080 probe_01 domain status=completed receipt_hash=r01
001.090 probe_01 graph checkpoint_saved=true report=DESCRIPTIVE_ONLY
002.010 probe_02 prepare plan_hash=p02 seeds=[11,12] policies=[balanced] battles=4
002.020 probe_02 graph node=validate passed=true source_fingerprint=stable
002.030 probe_02 graph interrupt=authorize checkpoint_saved=true
002.040 probe_02 operator decide request_id=probe_02 plan_hash=p02 approve=true
002.050 probe_02 domain status=running charged_battles=4
002.060 probe_02 worker_pair policy=balanced seed=11 baseline=win candidate=win
002.070 probe_02 worker_pair policy=balanced seed=12 baseline=win candidate=win
002.080 probe_02 domain status=completed receipt_hash=r02
002.090 probe_02 graph checkpoint_saved=true report=DESCRIPTIVE_ONLY
003.010 probe_03 prepare plan_hash=p03 seeds=[11,12] policies=[balanced] battles=4
003.020 probe_03 graph node=validate passed=true source_fingerprint=stable
003.030 probe_03 graph interrupt=authorize checkpoint_saved=true
003.040 probe_03 operator decide request_id=probe_03 plan_hash=p03 approve=true
003.050 probe_03 domain status=running charged_battles=4
003.060 probe_03 worker_pair policy=balanced seed=11 baseline=win candidate=win
003.070 probe_03 worker_pair policy=balanced seed=12 baseline=win candidate=win
003.080 probe_03 domain status=completed receipt_hash=r03
003.090 probe_03 graph checkpoint_saved=true report=DESCRIPTIVE_ONLY
004.010 probe_04 prepare plan_hash=p04 seeds=[11,12] policies=[balanced] battles=4
004.020 probe_04 graph node=validate passed=true source_fingerprint=stable
004.030 probe_04 graph interrupt=authorize checkpoint_saved=true
004.040 probe_04 operator decide request_id=probe_04 plan_hash=p04 approve=true
004.050 probe_04 domain status=running charged_battles=4
004.060 probe_04 worker_pair policy=balanced seed=11 baseline=win candidate=win
004.070 probe_04 worker_pair policy=balanced seed=12 baseline=win candidate=win
004.080 probe_04 domain status=completed receipt_hash=r04
004.090 probe_04 graph checkpoint_saved=true report=DESCRIPTIVE_ONLY
005.010 probe_05 prepare plan_hash=p05 seeds=[11,12] policies=[balanced] battles=4
005.020 probe_05 graph node=validate passed=true source_fingerprint=stable
005.030 probe_05 graph interrupt=authorize checkpoint_saved=true
005.040 probe_05 operator decide request_id=probe_05 plan_hash=p05 approve=true
005.050 probe_05 domain status=running charged_battles=4
005.060 probe_05 worker_pair policy=balanced seed=11 baseline=win candidate=win
005.070 probe_05 worker_pair policy=balanced seed=12 baseline=win candidate=win
005.080 probe_05 domain status=completed receipt_hash=r05
005.090 probe_05 graph checkpoint_saved=true report=DESCRIPTIVE_ONLY
006.010 probe_06 prepare plan_hash=p06 seeds=[11,12] policies=[balanced] battles=4
006.020 probe_06 graph node=validate passed=true source_fingerprint=stable
006.030 probe_06 graph interrupt=authorize checkpoint_saved=true
006.040 probe_06 operator decide request_id=probe_06 plan_hash=p06 approve=true
006.050 probe_06 domain status=running charged_battles=4
006.060 probe_06 worker_pair policy=balanced seed=11 baseline=win candidate=win
006.070 probe_06 worker_pair policy=balanced seed=12 baseline=win candidate=win
006.080 probe_06 domain status=completed receipt_hash=r06
006.090 probe_06 graph checkpoint_saved=true report=DESCRIPTIVE_ONLY
017.010 interrupted prepare plan_hash=p17 battles=4
017.020 interrupted operator decide plan_hash=p17 approve=true
017.030 interrupted domain status=running charged_battles=4 result_json=null
017.040 interrupted worker spawned pid=fixture-17
017.050 interrupted process_exit=74 checkpoint_next=experiment worker_outcome=unavailable
018.010 interrupted new_process resume request_id=interrupted
018.020 interrupted checkpoint next=experiment interrupt_count=0
018.030 interrupted domain status=running charged_battles=4 result_json=null
018.040 interrupted graph enters experiment
018.050 interrupted diagnostic_boundary=before_claim
# 本次日志在恢复准入前停止；请由候选源码推导后续是否安全。
```
