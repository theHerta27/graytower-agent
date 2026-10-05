"""Small V1 file capability, separate from Runtime's OS sandbox.

Only the primary thread gets the edit capability. SQLite receipts cover a lost
reply and a crash between the atomic file replacement and receipt completion.
This is a single-host trusted control plane, not an untrusted-code sandbox.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading

FILE = 'configs/combat/v2/baseline.json'
MAX_BYTES = 100_000


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class FileTools:
    def __init__(self, workspace: Path, control: Path):
        self.workspace = Path(os.path.abspath(workspace))
        self.control = Path(control).resolve()
        if self.control.is_relative_to(self.workspace) or self.workspace.is_relative_to(self.control):
            raise ValueError('control and editable workspace must be separate')
        self.control.mkdir(parents=True, exist_ok=True)
        if self.control.stat().st_dev != self.workspace.stat().st_dev:
            raise ValueError('control and workspace must share a volume for atomic replacement')
        self.database = self.control / 'file-operations.sqlite'
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS edits (id TEXT PRIMARY KEY, input TEXT NOT NULL, '
                         'before_hash TEXT NOT NULL, after_hash TEXT NOT NULL, after_text TEXT NOT NULL, '
                         'status TEXT NOT NULL)')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _path(self, path):
        if path != FILE:
            raise ValueError('path outside the bounded Coding workspace capability')
        result = self.workspace / FILE
        # Reject junctions/symlinks at every component, including workspace ancestors.
        for item in (result, *result.parents):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('reparse/symlink paths are unsupported')
        info = result.stat()
        if not result.is_file() or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise ValueError('require one bounded regular file, without hardlinks')
        return result

    def read_file(self, path=FILE):
        raw = self._path(path).read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError('file exceeds read limit')
        return {'path': FILE, 'sha256': _sha(raw), 'text': raw.decode('utf-8')}

    def replace_text(self, operation_id, *, path, expected_sha256, old_text, new_text, _after_write=None):
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 200:
            raise ValueError('invalid operation id')
        if (not isinstance(old_text, str) or not old_text or not isinstance(new_text, str)
                or old_text == new_text or len(old_text) + len(new_text) > MAX_BYTES):
            raise ValueError('require one nonempty bounded text replacement')
        value = {'path': path, 'expected_sha256': expected_sha256, 'old_text': old_text, 'new_text': new_text}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT * FROM edits WHERE id=?', (operation_id,)).fetchone()
            if previous is None:
                current = self.read_file(path)
                if current['sha256'] != expected_sha256:
                    raise ValueError('workspace changed: expected file hash mismatch')
                if current['text'].count(old_text) != 1:
                    raise ValueError('old_text must occur exactly once')
                text = current['text'].replace(old_text, new_text, 1)
                raw = text.encode('utf-8')
                if len(raw) > MAX_BYTES:
                    raise ValueError('file exceeds write limit')
                conn.execute('INSERT INTO edits VALUES (?,?,?,?,?,?)',
                             (operation_id, encoded, current['sha256'], _sha(raw), text, 'prepared'))
                conn.commit()  # Plan survives a process loss before the file write.
                conn.execute('BEGIN IMMEDIATE')
                previous = conn.execute('SELECT * FROM edits WHERE id=?', (operation_id,)).fetchone()
            if previous['input'] != encoded:
                raise ValueError('same operation id with different input')
            current = self.read_file(path)
            if current['sha256'] == previous['after_hash']:
                pass  # Already written, including lost reply or incomplete receipt.
            elif current['sha256'] == previous['before_hash'] and previous['status'] == 'prepared':
                target = self._path(path)
                # A hard crash may leave this private temporary file behind.
                # Keep it outside the candidate tree, on the same volume.
                descriptor, temporary = tempfile.mkstemp(prefix='.coding-write-', dir=self.control)
                try:
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(previous['after_text'].encode('utf-8'))
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                if _after_write:
                    _after_write()
            else:
                raise ValueError('workspace changed since the recorded edit; do not replay')
            conn.execute("UPDATE edits SET status='completed' WHERE id=?", (operation_id,))
            return {'operation_id': operation_id, 'path': FILE, 'before_sha256': previous['before_hash'],
                    'after_sha256': previous['after_hash'], 'status': 'completed'}


EDIT_TOOL = {'type': 'function', 'name': 'edit_text',
             'description': 'Replace one exact text occurrence in the prepared game configuration. Primary thread only; read its current sha256 first.',
             'inputSchema': {'type': 'object', 'additionalProperties': False,
                             'required': ['path', 'expected_sha256', 'old_text', 'new_text'],
                             'properties': {key: {'type': 'string'} for key in
                                            ('path', 'expected_sha256', 'old_text', 'new_text')}}}


def edit_handler(files: FileTools, primary_thread_id: str):
    def handle(method, params):
        if method == 'item/tool/call':
            try:
                if (not primary_thread_id or not isinstance(params, dict)
                        or params.get('threadId') != primary_thread_id or params.get('tool') != 'edit_text'):
                    raise ValueError('edit capability belongs to the primary thread only')
                arguments = params.get('arguments')
                if not isinstance(arguments, dict) or set(arguments) != {'path', 'expected_sha256', 'old_text', 'new_text'}:
                    raise ValueError('invalid edit arguments')
                result = files.replace_text(params.get('callId'), **arguments)
                return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(result)}]}
            except (ValueError, OSError, UnicodeError, TypeError):
                return {'success': False, 'contentItems': [{'type': 'inputText', 'text': 'Edit rejected; check thread capability, path, current hash and unique old text.'}]}
        if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            return {'decision': 'decline'}
        if method == 'item/permissions/requestApproval':
            return {'permissions': {}, 'scope': 'turn'}
        if method == 'item/tool/requestUserInput':
            return {'answers': {}}
        return {}
    return handle
