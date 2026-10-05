"""Content-addressed storage and the explicitly supported local execution profile."""
import base64
import copy
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
CODING_TARGET = "configs/combat/v2/baseline.json"
CODING_MAX_BYTES = 2 * 1024 * 1024


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
    if author not in ("config", "coding"):
        raise ValueError("only config/coding Authors may create this numeric candidate profile; code/build unsupported")
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


def coding_file(raw):
    if not isinstance(raw, bytes) or len(raw) > CODING_MAX_BYTES:
        raise ValueError("coding file exceeds supported byte limit")
    return {"schema_version": "coding-file-v1", "content_base64": base64.b64encode(raw).decode("ascii"),
            "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def read_coding_file(artifacts, ref):
    value = artifacts.read_ref(ref, "coding-file-v1")
    if set(value) != {"schema_version", "content_base64", "sha256", "size"}:
        raise ValueError("malformed coding file artifact")
    try:
        raw = base64.b64decode(value["content_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed coding file bytes") from exc
    if encoded(coding_file(raw)) != encoded(value):
        raise ValueError("coding file byte hash/size mismatch")
    return raw


def coding_tree(raw):
    """The complete permitted workspace tree, including otherwise empty dirs."""
    return {"configs": {"type": "directory"}, "configs/combat": {"type": "directory"},
            "configs/combat/v2": {"type": "directory"},
            CODING_TARGET: {"type": "file", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}}


def strict_config(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate coding JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite coding JSON value: " + value)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if not isinstance(value, dict):
            raise ValueError("coding config must be an object")
        encoded(value)  # Reject overflowing exponents as well as NaN/Infinity.
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid coding config JSON") from exc


def coding_diff(before, after, allow_unchanged=False):
    base, candidate = strict_config(before), strict_config(after)
    try:
        original = base["skills"]["breaker_skill"]["multiplier"]
        value = candidate["skills"]["breaker_skill"]["multiplier"]
        expected = copy.deepcopy(base)
        expected["skills"]["breaker_skill"]["multiplier"] = value
    except (KeyError, TypeError) as exc:
        raise ValueError("coding config is missing the audited numeric field") from exc
    if encoded(expected) != encoded(candidate):
        raise ValueError("coding workspace changes fields outside the numeric scope")
    if original != 1.4:
        raise ValueError("coding baseline is not the audited original")
    if allow_unchanged and type(value) in (int, float) and value == 1.4:
        return []
    check_changes("coding config import", [{"path": FIELD, "value": value}], "coding")
    return [{"path": FIELD, "before": original, "after": value}]


def validate_coding_source(artifacts, ref, baseline_sha, expected_diff):
    """Independently bind imported bytes and the full allowed tree to a candidate.

    Provenance is a declaration, not proof of an SDK run or a passed Review.
    Nothing in this artifact authorizes execution of code/build candidates.
    """
    source = artifacts.read_ref(ref, "coding-source-v1")
    fields = {"schema_version", "target_path", "preparation", "before_file", "after_file",
              "before_snapshot", "after_snapshot", "before_tree_hash", "after_tree_hash",
              "diff", "provenance", "review_status"}
    if (set(source) != fields or source["schema_version"] != "coding-source-v1"
            or source["target_path"] != CODING_TARGET or source["review_status"] != "pending"):
        raise ValueError("malformed coding source artifact")
    preparation = artifacts.read_ref(source["preparation"], "coding-workspace-v1")
    if (set(preparation) != {"schema_version", "kind", "workspace_root", "target_path", "before_file",
                             "before_snapshot", "before_tree_hash"}
            or preparation["schema_version"] != "coding-workspace-v1" or preparation["kind"] != "numeric_config"
            or preparation["target_path"] != CODING_TARGET
            or not isinstance(preparation["workspace_root"], str)
            or not Path(preparation["workspace_root"]).is_absolute()):
        raise ValueError("malformed coding workspace preparation")
    before = read_coding_file(artifacts, source["before_file"])
    after = read_coding_file(artifacts, source["after_file"])
    if hashlib.sha256(before).hexdigest() != baseline_sha:
        raise ValueError("coding baseline source fingerprint drift")
    for label, raw in (("before", before), ("after", after)):
        tree = coding_tree(raw)
        if source[label + "_snapshot"] != tree or source[label + "_tree_hash"] != digest(tree):
            raise ValueError("coding workspace snapshot does not match frozen bytes")
    if any(preparation[key] != source[key] for key in ("before_file", "before_snapshot", "before_tree_hash")):
        raise ValueError("coding source does not match workspace preparation")
    diff = coding_diff(before, after)
    if encoded(diff) != encoded(expected_diff) or encoded(diff) != encoded(source["diff"]):
        raise ValueError("coding source diff does not match candidate")
    provenance = source["provenance"]
    if (not isinstance(provenance, dict) or set(provenance) != {"status", "details"}
            or provenance["status"] != "declared_unverified" or not isinstance(provenance["details"], dict)
            or len(encoded(provenance)) > 32768):
        raise ValueError("coding provenance must be a bounded unverified declaration")
    return source


def check_plan(seeds, policies):
    if (not isinstance(seeds, list) or not 1 <= len(seeds) <= 50
            or any(type(seed) is not int or not 0 <= seed < 2**63 for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("require 1-50 unique integer seeds in [0, 2**63)")
    if (not isinstance(policies, list) or not 1 <= len(policies) <= 3
            or any(type(policy) is not str or policy not in POLICIES for policy in policies)
            or len(set(policies)) != len(policies)):
        raise ValueError("require unique supported policies")
