"""A bounded Python repair case in a real Git worktree, with frozen replay bytes."""
import base64
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import uuid

from .domain._shared import Artifacts, digest, encoded, valid_hash

GAME = Path('D:/Desktop/graytower-game')
GAME_COMMIT = '5c5ec50'
TARGET = 'game-core/combat_core/v2/effects.py'
PROFILE = 'shield-damage-python-v1'
PROFILES = (PROFILE, 'skill-points-python-v1')


def git(root, *args):
    result = subprocess.run(['git', '-c', 'safe.directory='+Path(root).resolve().as_posix(),
                             '-c', 'core.autocrlf=false', '-C', str(root), *args], capture_output=True, timeout=45)
    if result.returncode:
        raise ValueError('Git operation failed: '+result.stderr.decode('utf-8', errors='replace')[-1000:])
    return result.stdout.decode('utf-8').rstrip('\r\n')


def snapshot(path):
    result = {}
    for folder in ('game-core/combat_core', 'configs/combat/v2'):
        for file in sorted((path / folder).rglob('*')):
            if file.is_dir():
                continue
            if file.is_symlink() or getattr(file.lstat(), 'st_file_attributes', 0) & 0x400 or file.stat().st_nlink != 1:
                raise ValueError('scope prohibits linked files')
            if file.suffix not in ('.py', '.json'):
                raise ValueError('scope contains unsupported source file')
            raw = file.read_bytes()
            if len(raw) > 500_000:
                raise ValueError('source file exceeds limit')
            result[file.relative_to(path).as_posix()] = {'sha256': hashlib.sha256(raw).hexdigest(),
                                                       'content': base64.b64encode(raw).decode('ascii')}
    return {'schema_version': 'code-tree-v1', 'files': result}


def write_tree(path, tree):
    if path.exists():
        raise ValueError('replay path already exists')
    path.mkdir(parents=True)
    for name, item in tree['files'].items():
        file = path / name
        if (not file.resolve().is_relative_to(path.resolve()) or '\\' in name or ':' in name
                or not name.startswith(('game-core/combat_core/', 'configs/combat/v2/'))):
            raise ValueError('invalid frozen source path')
        raw = base64.b64decode(item['content'], validate=True)
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('frozen source hash mismatch')
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)


class CodeWorkspace:
    def __init__(self, control, path, preparation):
        self.control, self.path = Path(control), Path(path)
        self.artifacts = Artifacts(self.control / 'artifacts')
        self.preparation = preparation

    def inspect_changes(self):
        before = self.artifacts.read_ref(self.preparation['baseline_tree'], 'code-tree-v1')
        after = snapshot(self.path)
        status = git(self.path, 'status', '--porcelain', '--untracked-files=all').splitlines()
        changed = sorted(k for k in set(before['files']) | set(after['files']) if before['files'].get(k) != after['files'].get(k))
        if (set(before['files']) != set(after['files']) or any(k != TARGET for k in changed)
                or any(line[3:] != TARGET for line in status)
                or git(self.path, 'rev-parse', 'HEAD') != self.preparation['baseline_commit']):
            raise ValueError('workspace changed outside the prepared Python scope')
        return {'before_tree_hash': self.preparation['baseline_tree']['sha256'], 'after_tree_hash': digest(after),
                'after_hash': after['files'][TARGET]['sha256'], 'changed_files': changed,
                'scope_check': 'PASS', 'tests_run': False}

    def read_file(self, name):
        before = self.artifacts.read_ref(self.preparation['baseline_tree'], 'code-tree-v1')
        if name not in before['files']:
            raise ValueError('file outside the prepared source catalog')
        self.inspect_changes()
        # snapshot checks link types and byte bounds before returning content.
        item = snapshot(self.path)['files'][name]
        return {'path': name, 'sha256': item['sha256'],
                'text': base64.b64decode(item['content']).decode('utf-8')}

    def freeze(self, request, *, provenance=None):
        if not isinstance(request, str) or not request.strip() or len(request) > 4000:
            raise ValueError('invalid code request')
        self.inspect_changes()
        status = git(self.path, 'status', '--porcelain', '--untracked-files=all').splitlines()
        if any(line[3:] != TARGET for line in status) or not status:
            raise ValueError('scope requires only the allowed Python file to change')
        before = self.artifacts.read_ref(self.preparation['baseline_tree'], 'code-tree-v1')
        after = snapshot(self.path)
        changed = sorted(k for k in set(before['files']) | set(after['files']) if before['files'].get(k) != after['files'].get(k))
        if changed != [TARGET]:
            raise ValueError('scope requires exactly one allowed file modification')
        patch = git(self.path, 'diff', '--no-ext-diff', '--no-textconv', '--', TARGET)+'\n'
        if not patch.strip():
            raise ValueError('empty code patch')
        manifest = {'schema_version': 'code-candidate-v1', 'kind': 'code', 'profile': PROFILE,
                    'request': request, 'game_commit': self.preparation['game_commit'],
                    'baseline_commit': self.preparation['baseline_commit'], 'case': self.preparation.get('case', 'D-01-controlled-fault'),
                    'baseline_tree': self.preparation['baseline_tree'],
                    'candidate_tree': self.artifacts.put(after, 'code-tree-v1'),
                    'patch': self.artifacts.put({'text': patch}, 'code-patch-v1'),
                    'changed_files': changed, 'added_files': [], 'deleted_files': [],
                    'provenance': provenance or {'source': 'local engineering fixture, not a model run'}}
        manifest['profile'] = self.preparation['profile']
        ref = self.artifacts.put(manifest, 'code-candidate-v1')
        return self.inspect(ref['sha256'])

    def inspect(self, candidate_id):
        manifest = self.artifacts.read(valid_hash(candidate_id))
        if (manifest.get('schema_version') != 'code-candidate-v1' or manifest.get('kind') != 'code'
                or manifest.get('profile') not in PROFILES or manifest['profile'] != self.preparation['profile']):
            raise ValueError('unsupported code candidate')
        if any(manifest.get(key) != self.preparation[key] for key in ('game_commit', 'baseline_commit', 'baseline_tree')):
            raise ValueError('code baseline does not match trusted case preparation')
        for name, schema in (('baseline_tree', 'code-tree-v1'), ('candidate_tree', 'code-tree-v1'), ('patch', 'code-patch-v1')):
            self.artifacts.read_ref(manifest[name], schema)
        before = self.artifacts.read_ref(manifest['baseline_tree'], 'code-tree-v1')['files']
        after = self.artifacts.read_ref(manifest['candidate_tree'], 'code-tree-v1')['files']
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        if (set(before) != set(after) or changed != [TARGET] or manifest['changed_files'] != changed
                or manifest['added_files'] or manifest['deleted_files']):
            raise ValueError('code candidate scope mismatch')
        patch = self.artifacts.read_ref(manifest['patch'], 'code-patch-v1')['text']
        if [line for line in patch.splitlines() if line.startswith('diff --git ')] != [f'diff --git a/{TARGET} b/{TARGET}']:
            raise ValueError('patch outside allowed scope')
        return {'candidate_id': candidate_id, 'manifest': manifest}

    def restore(self, path, candidate_id, *, variant='candidate'):
        manifest = self.inspect(candidate_id)['manifest']
        before = self.artifacts.read_ref(manifest['baseline_tree'], 'code-tree-v1')
        path = Path(path)
        write_tree(path, before)
        if variant == 'candidate':
            # Prevent Git discovering the enclosing workbench repository and
            # silently treating the patch as outside its current subdirectory.
            git(path, 'init', '--quiet')
            patch = self.artifacts.read_ref(manifest['patch'], 'code-patch-v1')['text']
            subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', '-'], input=patch.encode('utf-8'),
                           cwd=path, check=True, capture_output=True, timeout=15)
            expected = self.artifacts.read_ref(manifest['candidate_tree'], 'code-tree-v1')
            if snapshot(path) != expected:
                raise ValueError('replayed patch does not match frozen candidate files')
        elif variant != 'baseline':
            raise ValueError('invalid replay variant')
        return path

    def remove(self):
        # Only remove the exact worktree registered by this preparation, never
        # a computed arbitrary directory. Core artifacts live outside it.
        registered = git(GAME, 'worktree', 'list', '--porcelain')
        if 'worktree '+self.path.resolve().as_posix()+'\n' not in registered+'\n':
            raise ValueError('worktree identity not registered')
        git(GAME, 'worktree', 'remove', '--force', str(self.path))


def prepare_shield_case(control, path):
    return prepare_python_case(control, path, PROFILE)


def prepare_python_case(control, path, profile):
    if profile not in PROFILES:
        raise ValueError('unsupported bounded Python case')
    control, path = Path(control).resolve(), Path(path).resolve()
    if path.exists() or control.exists() or path == GAME.resolve() or control.is_relative_to(path):
        raise ValueError('case needs new separate workspace/control paths')
    commit = git(GAME, 'rev-parse', GAME_COMMIT+'^{commit}')
    git(GAME, 'worktree', 'add', '--detach', str(path), commit)
    control.mkdir(parents=True)
    target = path / TARGET
    raw = target.read_bytes()
    old, fault_text, case = (b'hp_loss=min(u.hp,left)', b'hp_loss=min(u.hp,amount)', 'D-01-controlled-fault') if profile == PROFILE else (
        b'state.skill_points=min(5,before+gained-spent)', b'state.skill_points=min(4,before+gained-spent)', 'D-02-controlled-fault')
    if raw.count(old) != 1:
        raise ValueError('expected case implementation changed')
    target.write_bytes(raw.replace(old, fault_text, 1))
    git(path, 'add', TARGET)
    git(path, '-c', 'user.name=graytower-demo', '-c', 'user.email=local@localhost', '-c', 'commit.gpgsign=false',
        'commit', '-m', 'test-case: '+case)
    fault = git(path, 'rev-parse', 'HEAD')
    git(GAME, 'update-ref', 'refs/demo-cases/shield-'+uuid.uuid4().hex, fault)
    artifacts = Artifacts(control / 'artifacts')
    preparation = {'case': case, 'profile': profile, 'game_commit': commit,
                   'baseline_commit': fault, 'editable_files': [TARGET],
                   'baseline_tree': artifacts.put(snapshot(path), 'code-tree-v1')}
    (control / 'preparation.json').write_bytes(encoded(preparation))
    return CodeWorkspace(control, path, preparation)


def runtime_workspace(data, path, preparation):
    control = Path(data).resolve() / 'control'
    saved = json.loads((control / 'preparation.json').read_text(encoding='utf-8'))
    if encoded(saved) != encoded(preparation) or saved.get('profile') not in PROFILES:
        raise ValueError('Python Runtime preparation does not match its trusted record')
    return CodeWorkspace(control, path, saved)
