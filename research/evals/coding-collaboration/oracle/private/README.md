# Frozen benchmark truth

This directory is evaluator-only. Never send it, `prepare_tasks.py`, or any candidate/baseline snapshot here to a solver. Solvers receive the exact bytes of one `tasks/public/<task_id>/packet.md` under every execution condition. Public metadata contains no issue counts.

The suite has two development tasks and four independently reserved confirmation tasks. All six use small, explicitly marked benchmark candidates based on real repository code. Five candidates contain deliberate regressions; one is a behavior-preserving local change. These are not allegations that the regressions exist in the live repositories.

`manifest.json` freezes packet hashes, oracle hashes, split and input identities. Each oracle also records original source byte hashes and full candidate snapshot hashes. `prepare_tasks.py` refuses to overwrite an existing differing frozen file. Confirmation packets and oracles were fixed before any solver output was read. The development recovery packet was shortened before its first run to remove repetitive log context; confirmation packets were not changed.

`exhaustive_within_scope` means the listed known injected root causes within the explicitly bounded candidate-diff review scope. It does not mean every latent repository defect has been exhausted. A finding unmatched by an issue ID must receive independent source-based adjudication: verified additional defects are recorded separately, uncertainty remains unresolved, and neither the frozen task nor its oracle denominator is rewritten after seeing a model result. The evaluator supports `novel_tp` and `unresolved` for that purpose.

Aliases are retrieval aids for human adjudication, not an automatic keyword scorer. A true positive requires compatible location, trigger, root cause and causal evidence. Multiple symptoms of the same root cause count once. Evidence not supplied in the public packet cannot be required to solve the task. Scores concern review findings, not delivered patch correctness, production reliability, general model quality, or Unity acceptance.

Run the verifier from any directory:

```powershell
& 'D:\Desktop\combat-foundation\.venv\Scripts\python.exe' -B 'D:\Desktop\mihoyo-agent-project\research\evals\coding-collaboration\oracle\private\verify_oracles.py'
```

The verifier executes frozen Python functions with real pydantic combat state, real SQLite transactions and asyncio task/queue behavior. Its one C# display check explicitly verifies the exact source expression and arithmetic witness, without claiming C# compilation or Unity execution. It checks all packet, oracle, candidate and live helper source hashes before executing. `verification.json` records every observation and verifier identity. Public recovery logs are labeled diagnostic fixtures and end before recovery admission; they are not disguised production logs.

No model API, paid request, Unity process, old-source modification, model-response inspection or repository-wide write is part of preparing or verifying this suite.
