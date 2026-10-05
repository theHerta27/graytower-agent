"""Service-side repository. The game and its validators run only in a child process."""
import json
import os
from pathlib import Path
import subprocess

from ._shared import Artifacts, TRUSTED_GAME_ROOT, check_changes, check_plan, encoded, trusted_root, valid_hash


class CandidateRepository:
    def __init__(self, data_dir: Path, game_root: Path = TRUSTED_GAME_ROOT, game_python: Path | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.game_root = trusted_root(game_root)
        expected_python = (self.game_root / ".venv/Scripts/python.exe").resolve(strict=True)
        self.game_python = Path(game_python).resolve(strict=True) if game_python else expected_python
        if self.game_python != expected_python:
            raise ValueError("only the trusted game interpreter is supported")
        self.artifacts = Artifacts(self.data_dir / "artifacts")

    def _call(self, operation, payload):
        # Do not inherit model credentials, proxies, PYTHONPATH or tracing settings.
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        env.update(PYTHONUTF8="1", LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
        process = subprocess.run(
            [str(self.game_python), "-I", "-B", "-X", "utf8", str(Path(__file__).with_name("worker.py")), operation,
             "--game-root", str(self.game_root), "--artifacts", str(self.artifacts.root)],
            input=encoded(payload).decode("utf-8"), text=True, encoding="utf-8", capture_output=True,
            timeout=180, env=env, cwd=self.data_dir,
        )
        if process.returncode:
            raise ValueError("trusted game worker rejected input: " + process.stderr[-2400:].strip())
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid game worker response") from exc
        if not isinstance(result, dict):
            raise ValueError("invalid game worker response")
        return result

    def describe(self) -> dict:
        return self._call("describe", {})

    def create(self, request: str, changes: list[dict], author="config", parent_manifest: str | None = None) -> dict:
        check_changes(request, changes, author)
        if parent_manifest is not None:
            self.get(valid_hash(parent_manifest))
        return self._call("author", {"request": request, "changes": changes, "author": author,
                                     "parent_manifest": parent_manifest})

    def get(self, manifest_hash: str) -> dict:
        return self._call("inspect", {"manifest_hash": valid_hash(manifest_hash)})

    def verify(self, manifest_hash: str, seeds: list[int], policies: list[str]) -> dict:
        check_plan(seeds, policies)
        return self._call("verify", {"manifest_hash": valid_hash(manifest_hash), "seeds": seeds, "policies": policies})

    def read_artifact(self, artifact_hash: str) -> dict:
        return self.artifacts.read(artifact_hash)
