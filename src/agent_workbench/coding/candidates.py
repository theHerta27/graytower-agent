"""Import one trusted numeric config from an isolated Coding workspace.

This is a local file-edit boundary, not an untrusted code or build sandbox.
Control-plane artifacts live outside the editable workspace. Review results are
declared provenance only; the importer never upgrades them to a passed Review.
"""
import hashlib
import os
from pathlib import Path
import stat

from agent_workbench.domain import CandidateRepository
from agent_workbench.domain._shared import (
    CODING_MAX_BYTES, CODING_TARGET, FIELD, coding_diff, coding_file, coding_tree,
    digest, encoded, read_coding_file,
)


def _no_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("coding workspace symlink/reparse point is forbidden")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ValueError("coding workspace hardlink is forbidden")
    return info


def _path_chain(path):
    # Do this before resolve(), which would erase symlink/junction evidence.
    path = Path(os.path.abspath(path))
    for item in reversed((path, *path.parents)):
        if os.path.lexists(item):
            _no_link(item)
    return path


def _snapshot(root):
    root = _path_chain(root)
    if not stat.S_ISDIR(_no_link(root).st_mode):
        raise ValueError("coding workspace root must be a directory")
    tree, contents = {}, {}

    def visit(folder):
        for path in sorted(folder.iterdir()):
            name = path.relative_to(root).as_posix()
            if len(tree) >= 64:
                raise ValueError("coding workspace contains too many entries")
            info = _no_link(path)
            if stat.S_ISDIR(info.st_mode):
                tree[name] = {"type": "directory"}
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                if info.st_size > CODING_MAX_BYTES:
                    raise ValueError("coding workspace file exceeds byte limit")
                with path.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    raw = stream.read(CODING_MAX_BYTES + 1)
                    finished = os.fstat(stream.fileno())
                final = _no_link(path)
                identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_nlink)
                if any(identity(item) != identity(info) for item in (opened, finished, final)):
                    raise ValueError("coding workspace changed while reading")
                if len(raw) > CODING_MAX_BYTES:
                    raise ValueError("coding workspace file exceeds byte limit")
                tree[name] = {"type": "file", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
                contents[name] = raw
            else:
                raise ValueError("coding workspace contains unsupported filesystem entry")

    try:
        visit(root)
    except OSError as exc:
        raise ValueError("coding workspace could not be read safely") from exc
    return tree, contents


class CodingWorkspace:
    def __init__(self, root: Path, repo: CandidateRepository, preparation: dict):
        self.root = _path_chain(root)
        self.repo = repo
        self.preparation = dict(preparation)
        seal = self.repo.artifacts.read_ref(self.preparation, "coding-workspace-v1")
        if seal.get("workspace_root") != str(self.root):
            raise ValueError("coding workspace path does not match preparation")

    @classmethod
    def prepare(cls, workspace: Path, repo: CandidateRepository):
        """Copy exact trusted baseline bytes into a new, otherwise empty root."""
        root = _path_chain(workspace)
        if (root.is_relative_to(repo.game_root) or repo.game_root.is_relative_to(root)
                or root.is_relative_to(repo.artifacts.root) or repo.artifacts.root.is_relative_to(root)):
            raise ValueError("coding workspace overlaps trusted game or authority artifacts")
        if os.path.lexists(root):
            raise ValueError("coding workspace must be a new directory")
        baseline = repo.game_root / CODING_TARGET
        raw = baseline.read_bytes()
        # Decode before copying; an invalid audited baseline is not editable input.
        coding_diff(raw, raw, allow_unchanged=True)
        target = root / CODING_TARGET
        target.parent.mkdir(parents=True)
        with target.open("xb") as stream:
            stream.write(raw)
        tree, contents = _snapshot(root)
        if tree != coding_tree(raw) or contents != {CODING_TARGET: raw}:
            raise ValueError("coding workspace preparation changed while copying")
        seal = {"schema_version": "coding-workspace-v1", "kind": "numeric_config", "workspace_root": str(root),
                "target_path": CODING_TARGET, "before_file": repo.artifacts.put(coding_file(raw), "coding-file-v1"),
                "before_snapshot": tree, "before_tree_hash": digest(tree)}
        return cls(root, repo, repo.artifacts.put(seal, "coding-workspace-v1"))

    def _inspect(self):
        seal = self.repo.artifacts.read_ref(self.preparation, "coding-workspace-v1")
        before = read_coding_file(self.repo.artifacts, seal["before_file"])
        if (seal["workspace_root"] != str(self.root) or seal["target_path"] != CODING_TARGET
                or seal["before_snapshot"] != coding_tree(before)
                or seal["before_tree_hash"] != digest(coding_tree(before))):
            raise ValueError("coding workspace preparation mismatch")
        if hashlib.sha256((self.repo.game_root / CODING_TARGET).read_bytes()).hexdigest() != hashlib.sha256(before).hexdigest():
            raise ValueError("coding baseline source fingerprint drift")
        tree, contents = _snapshot(self.root)
        if set(contents) != {CODING_TARGET} or tree != coding_tree(contents[CODING_TARGET]):
            raise ValueError("coding workspace full tree contains unauthorized changes")
        after = contents[CODING_TARGET]
        diff = coding_diff(before, after, allow_unchanged=True)
        # A second complete read detects ordinary concurrent edits. V1 has one
        # local driver; this does not claim hostile-process filesystem isolation.
        if _snapshot(self.root) != (tree, contents):
            raise ValueError("coding workspace changed during inspection")
        return seal, before, after, tree, diff

    def inspect_changes(self) -> dict:
        """Read-only preflight; no candidate or artifact is written."""
        seal, before, after, tree, diff = self._inspect()
        return {"diff": diff, "before_hash": hashlib.sha256(before).hexdigest(),
                "after_hash": hashlib.sha256(after).hexdigest(), "before_tree_hash": seal["before_tree_hash"],
                "after_tree_hash": digest(tree), "files": tree}

    def import_candidate(self, request: str, provenance: dict | None = None) -> dict:
        """Freeze allowed bytes as a coding-authored numeric_config manifest."""
        if provenance is None:
            provenance = {}
        if not isinstance(provenance, dict) or len(encoded(provenance)) > 32000:
            raise ValueError("coding provenance must be a bounded object")
        seal, before, after, tree, diff = self._inspect()
        if not diff:
            raise ValueError("coding candidate must change the audited numeric value")
        source = {"schema_version": "coding-source-v1", "target_path": CODING_TARGET,
                  "preparation": self.preparation, "before_file": seal["before_file"],
                  "after_file": self.repo.artifacts.put(coding_file(after), "coding-file-v1"),
                  "before_snapshot": seal["before_snapshot"], "after_snapshot": tree,
                  "before_tree_hash": seal["before_tree_hash"], "after_tree_hash": digest(tree), "diff": diff,
                  "provenance": {"status": "declared_unverified", "details": provenance}, "review_status": "pending"}
        ref = self.repo.artifacts.put(source, "coding-source-v1")
        if self._inspect()[2:] != (after, tree, diff):
            raise ValueError("coding workspace changed before import")
        candidate = self.repo.create(request, [{"path": FIELD, "value": diff[0]["after"]}], author="coding", coding_source=ref)
        if self._inspect()[2:] != (after, tree, diff):
            raise ValueError("coding workspace changed during import; frozen artifact was not delivered")
        return candidate
