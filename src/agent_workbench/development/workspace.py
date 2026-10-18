"""Git-backed candidate materialization and bounded, recoverable file edits."""
from contextlib import closing
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import subprocess
import tempfile
import threading

MAX_FILE = 500_000
MAX_TREE = 12_000_000
READ_ROOTS = ('game-core/combat_core/', 'game-core/tests/v2/', 'configs/combat/v2/', 'contracts/')
EDIT_ROOTS = ('game-core/combat_core/', 'configs/combat/v2/')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def git(project, *args):
    result = subprocess.run(['git', '-c', 'safe.directory='+Path(project).resolve().as_posix(),
        '-c', 'core.autocrlf=false', '-C', str(project), *args], capture_output=True, timeout=40)
    if result.returncode:
        raise ValueError('Git operation failed: '+result.stderr.decode('utf-8', errors='replace')[-500:])
    return result.stdout


def clean_name(name):
    if (not isinstance(name, str) or not name or len(name) > 250 or '\\' in name or ':' in name
            or name.startswith('/') or any(ord(c) < 32 for c in name)):
        raise ValueError('invalid project-relative path')
    parts = name.split('/')
    if any(p in ('', '.', '..') or p.endswith((' ', '.')) or
           re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in parts):
        raise ValueError('unsupported path component')
    return name


def readable(name):
    return (name in ('README.md', 'pyproject.toml', 'scripts/accept_combat_v2.py',
                     'configs/combat/baseline.json') or name.startswith(READ_ROOTS)) and PurePosixPath(name).suffix in ('.py', '.json', '.md', '.toml', '.gz')


def editable(name):
    return ((name.startswith(EDIT_ROOTS[0]) and name.endswith('.py')) or
            (name.startswith(EDIT_ROOTS[1]) and name.endswith('.json')))


def item(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'content': base64.b64encode(raw).decode('ascii')}


class ProjectWorkspace:
    def __init__(self, control):
        self.control = Path(control).resolve()
        self.path = self.control / 'workspace'
        self.metadata = json.loads((self.control / 'project.json').read_text(encoding='utf-8'))
        self.baseline = json.loads((self.control / 'baseline.json').read_text(encoding='utf-8'))
        if digest(self.baseline) != self.metadata['baseline_tree_hash']:
            raise ValueError('baseline snapshot damaged')
        self._lock = threading.Lock()

    @classmethod
    def create(cls, project, control, ref='HEAD'):
        project, control = Path(project).resolve(), Path(control).resolve()
        if control.exists() or control.is_relative_to(project) or project.is_relative_to(control):
            raise ValueError('require a fresh control directory outside the source project')
        if Path(git(project, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != project:
            raise ValueError('select the Git project root')
        if git(project, 'status', '--porcelain', '--untracked-files=no').strip():
            raise ValueError('source has uncommitted changes; save a version before creating a task')
        commit = git(project, 'rev-parse', '--verify', '--end-of-options', str(ref)+'^{commit}').decode().strip()
        files, total = {}, 0
        entries = git(project, 'ls-tree', '-rz', commit).split(b'\0')
        for entry in entries:
            if not entry:
                continue
            header, raw_name = entry.split(b'\t', 1)
            name = raw_name.decode('utf-8')
            if not readable(name):
                continue
            clean_name(name)
            mode, kind, oid = header.decode('ascii').split()
            if kind != 'blob' or mode not in ('100644', '100755'):
                raise ValueError('linked source entries are unsupported')
            raw = git(project, 'cat-file', 'blob', oid)
            total += len(raw)
            if len(raw) > MAX_FILE or total > MAX_TREE or len(files) >= 2000:
                raise ValueError('project exceeds supported candidate limits')
            files[name] = item(raw)
        if not files or not any(editable(n) for n in files):
            raise ValueError('project has no supported game rule source')
        tree = {'schema': 'development-tree-v1', 'files': files}
        control.mkdir(parents=True)
        workspace = control / 'workspace'
        workspace.mkdir()
        for name, value in files.items():
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(value['content']))
        (control / 'baseline.json').write_bytes(encoded(tree))
        (control / 'project.json').write_bytes(encoded({'schema': 'development-project-v1',
            'project': str(project), 'baseline_commit': commit, 'baseline_tree_hash': digest(tree)}))
        with closing(sqlite3.connect(control / 'edits.sqlite')) as db, db:
            db.execute('CREATE TABLE edits (id TEXT PRIMARY KEY,input TEXT NOT NULL,before_hash TEXT,after_hash TEXT,content TEXT,status TEXT NOT NULL)')
        return cls(control)

    @classmethod
    def open(cls, control):
        return cls(control)

    def _path(self, name):
        clean_name(name)
        if not readable(name):
            raise ValueError('file outside supported project scope')
        path = self.path / name
        for p in (path, *path.parents):
            if not p.exists() and not p.is_symlink():
                continue
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked paths are unsupported')
        if path.exists():
            info = path.stat()
            if not path.is_file() or info.st_nlink != 1 or info.st_size > MAX_FILE:
                raise ValueError('require bounded regular file without hardlinks')
        return path

    def snapshot(self):
        files, total = {}, 0
        for path in sorted(self.path.rglob('*')):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked candidate entry')
            if path.is_dir():
                continue
            name = path.relative_to(self.path).as_posix()
            raw = self._path(name).read_bytes()
            total += len(raw)
            if total > MAX_TREE or len(files) >= 2000:
                raise ValueError('candidate exceeds supported limits')
            files[name] = item(raw)
        original = self.baseline['files']
        for name in set(files) | set(original):
            if not editable(name) and files.get(name) != original.get(name):
                raise ValueError('readonly project material changed')
        return {'schema': 'development-tree-v1', 'files': files}

    def inspect(self):
        tree = self.snapshot()
        before, after = self.baseline['files'], tree['files']
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        patch = []
        for name in changed:
            old = base64.b64decode(before[name]['content']).decode('utf-8') if name in before else ''
            new = base64.b64decode(after[name]['content']).decode('utf-8') if name in after else ''
            patch.extend(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile='a/'+name if name in before else '/dev/null', tofile='b/'+name if name in after else '/dev/null'))
        return {**self.metadata, 'tree_hash': digest(tree), 'changed_files': changed,
            'added_files': sorted(set(after)-set(before)), 'deleted_files': sorted(set(before)-set(after)),
            'patch': ''.join(patch), 'files': [{'path': n, 'sha256': v['sha256'], 'editable': editable(n)} for n, v in after.items()],
            'scope_check': 'PASS', 'tests_run': False}

    def read_file(self, name):
        self.snapshot()
        raw = self._path(name).read_bytes()
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'text': raw.decode('utf-8')}

    def search(self, query, limit=30):
        if not isinstance(query, str) or not query or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('require bounded literal search')
        result = []
        for name, value in self.snapshot()['files'].items():
            if name.endswith('.gz'):
                continue
            for n, line in enumerate(base64.b64decode(value['content']).decode('utf-8').splitlines(), 1):
                if query.casefold() in line.casefold():
                    result.append({'path': name, 'line': n, 'text': line[:600]})
                    if len(result) >= limit:
                        return result
        return result

    def _current(self, name):
        path = self._path(name)
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    def write_file(self, operation_id, path, expected_sha256, content, *, _after_write=None):
        if (not isinstance(operation_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,120}', operation_id)
                or (expected_sha256 is not None and not re.fullmatch(r'[a-f0-9]{64}', str(expected_sha256)))
                or (content is not None and not isinstance(content, str))):
            raise ValueError('invalid edit input')
        clean_name(path)
        if not editable(path):
            raise ValueError('file is not editable game source')
        if content is not None and len(content.encode('utf-8')) > MAX_FILE:
            raise ValueError('edit exceeds file limit')
        desired = hashlib.sha256(content.encode('utf-8')).hexdigest() if content is not None else None
        value = encoded({'path': path, 'expected_sha256': expected_sha256, 'content': content}).decode()
        with self._lock, closing(sqlite3.connect(self.control / 'edits.sqlite', timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM edits WHERE id=?', (operation_id,)).fetchone()
            if row is None:
                current_tree = self.snapshot()['files']
                projected = sum(len(base64.b64decode(v['content'])) for v in current_tree.values())
                if path in current_tree:
                    projected -= len(base64.b64decode(current_tree[path]['content']))
                projected += len(content.encode('utf-8')) if content is not None else 0
                if projected > MAX_TREE or (path not in current_tree and content is not None and len(current_tree) >= 2000):
                    raise ValueError('edit exceeds candidate limits')
                current = self._current(path)
                if current != expected_sha256 or (current is None and content is None):
                    raise ValueError('file changed or deletion has no target')
                db.execute('INSERT INTO edits VALUES (?,?,?,?,?,?)',
                    (operation_id, value, current, desired, content, 'prepared'))
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM edits WHERE id=?', (operation_id,)).fetchone()
            if row['input'] != value:
                raise ValueError('operation id reused with different input')
            current = self._current(path)
            if current == row['after_hash']:
                pass
            elif current == row['before_hash'] and row['status'] == 'prepared':
                target = self._path(path)
                if content is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fd, temporary = tempfile.mkstemp(prefix='edit-', dir=self.control)
                    try:
                        with os.fdopen(fd, 'wb') as stream:
                            stream.write(content.encode('utf-8')); stream.flush(); os.fsync(stream.fileno())
                        os.replace(temporary, target)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                if _after_write:
                    _after_write()
            else:
                raise ValueError('candidate changed since recorded edit')
            db.execute("UPDATE edits SET status='completed' WHERE id=?", (operation_id,))
            return {'operation_id': operation_id, 'path': path, 'before_sha256': row['before_hash'],
                    'after_sha256': row['after_hash'], 'status': 'completed'}
