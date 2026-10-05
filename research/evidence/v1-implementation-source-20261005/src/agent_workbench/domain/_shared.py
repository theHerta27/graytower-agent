"""Content-addressed storage and the explicitly supported local execution profile."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

TRUSTED_GAME_ROOT = Path("D:/Desktop/combat-foundation")
PROFILE = "trusted-combat-numeric-v1"
FIELD = "skills.breaker_skill.multiplier"
SCOPE = {FIELD: {"minimum": 1.4, "maximum": 1.7}}
POLICIES = ("balanced", "survival", "basic_only")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def valid_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("artifact hash must be 64 lowercase hexadecimal characters")
    return value


class Artifacts:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, sha):
        result = (self.root / (valid_hash(sha) + ".json")).resolve()
        if result.parent != self.root:
            raise ValueError("artifact path escapes repository")
        return result

    def read(self, sha):
        try:
            raw = self.path(sha).read_bytes()
        except FileNotFoundError:
            raise ValueError("artifact hash not found") from None
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("artifact hash mismatch")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or encoded(value) != raw:
                raise ValueError("noncanonical artifact content")
            return value
        except (json.JSONDecodeError, UnicodeError, TypeError) as exc:
            raise ValueError("invalid artifact JSON") from exc

    def read_ref(self, ref, schema):
        if (not isinstance(ref, dict) or set(ref) != {"artifact_id", "sha256", "schema"}
                or ref["artifact_id"] != ref["sha256"] or ref["schema"] != schema):
            raise ValueError("wrong artifact reference or schema")
        return self.read(ref["sha256"])

    def put(self, value, schema):
        raw = encoded(value)
        sha = hashlib.sha256(raw).hexdigest()
        target = self.path(sha)
        # A crash can leave an unreferenced temp, never a partial hash-addressed file.
        fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                self.read(sha)
        finally:
            os.unlink(temporary)
        return {"artifact_id": sha, "sha256": sha, "schema": schema}


def trusted_root(root):
    root = Path(root).resolve(strict=True)
    if root != TRUSTED_GAME_ROOT.resolve(strict=True):
        raise ValueError("only the explicitly trusted game checkout is supported")
    return root


def source_snapshot(root):
    root = trusted_root(root)
    paths = [path for folder in (root / "game-core/combat_core", root / "services/verification-agent/verification_agent")
             for path in folder.rglob("*.py")]
    paths += [root / "configs/combat/v2/baseline.json", root / "configs/combat/v2/scenario.json"]
    if len(paths) < 3 or not all(path.is_file() for path in paths):
        raise ValueError("incomplete trusted game checkout")
    files = {}
    for path in sorted(paths):
        if not path.resolve().is_relative_to(root):
            raise ValueError("game source escapes trusted checkout")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"fingerprint": digest(files), "files": files}


def check_changes(request, changes, author):
    if author != "config":
        raise ValueError("only the config Author may create this numeric candidate profile")
    if not isinstance(request, str) or not request.strip() or len(request) > 4000:
        raise ValueError("request must contain 1-4000 characters")
    if not isinstance(changes, list) or len(changes) != 1:
        raise ValueError("V1 requires exactly one audited numeric change")
    change = changes[0]
    if not isinstance(change, dict) or set(change) != {"path", "value"} or change["path"] != FIELD:
        raise ValueError("change outside the audited numeric catalog")
    value = change["value"]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("numeric value required; coercion is forbidden")
    if not 1.4 <= value <= 1.7 or value == 1.4:
        raise ValueError("candidate must change baseline within [1.4, 1.7]")


def check_plan(seeds, policies):
    if (not isinstance(seeds, list) or not 1 <= len(seeds) <= 50
            or any(type(seed) is not int or not 0 <= seed < 2**63 for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("require 1-50 unique integer seeds in [0, 2**63)")
    if (not isinstance(policies, list) or not 1 <= len(policies) <= 3
            or any(type(policy) is not str or policy not in POLICIES for policy in policies)
            or len(set(policies)) != len(policies)):
        raise ValueError("require unique supported policies")
