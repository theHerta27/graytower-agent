"""Local operator CLI: prepare -> inspect hash -> approve/reject -> show/resume."""
import argparse
import json
from pathlib import Path
import sys

from .combat_worker import CombatAdapter, source_fingerprint
from .contracts import ExperimentPlan
from .workflow import Verification


def main():
    parser = argparse.ArgumentParser(description="Verification: frozen, approved, descriptive game experiments")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--game-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").add_argument("proposal", type=Path)
    for command in ["approve", "reject", "resume", "show"]:
        p = sub.add_parser(command)
        p.add_argument("request_id")
        if command in ("approve", "reject"):
            p.add_argument("--plan-hash", required=True)
    args = parser.parse_args()
    app = Verification(args.data, CombatAdapter(args.game_root))
    try:
        if args.command == "prepare":
            value = json.loads(args.proposal.read_text(encoding="utf-8"))
            value.setdefault("game_fingerprint", source_fingerprint(args.game_root.resolve(strict=True)))
            result = app.prepare(ExperimentPlan.model_validate(value))
        elif args.command in ("approve", "reject"):
            result = app.decide(args.request_id, args.plan_hash, args.command == "approve")
        else:
            result = getattr(app, args.command)(args.request_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({"error": str(exc), "action": "inspect frozen input and ledger; no automatic retry"},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
