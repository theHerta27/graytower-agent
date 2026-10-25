"""Local project memory with explicit confirmation and bounded lexical retrieval.

The caller binds the project identity and decides which actions are user edits.
This store never interprets memory text as an authorization or permission grant.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid


_FIELDS = ('id', 'project', 'content', 'source', 'version', 'kind', 'status',
           'created_at', 'updated_at')
_KINDS = frozenset(('constraint', 'decision', 'lesson'))
_STATUSES = frozenset(('pending', 'confirmed'))
_EDITABLE = frozenset(('content', 'version', 'kind', 'status'))


def _text(name, value, maximum):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or '\x00' in value):
        raise ValueError(f'invalid memory {name}')
    return value


def _validate(fields):
    for name, maximum in (('content', 2000), ('source', 500), ('version', 80)):
        if name in fields:
            _text(name, fields[name], maximum)
    for name, allowed in (('kind', _KINDS), ('status', _STATUSES)):
        if name in fields and (not isinstance(fields[name], str) or fields[name] not in allowed):
            raise ValueError(f'invalid memory {name}')


def _tokens(text):
    """Whole Latin words plus Chinese bigrams, without external tokenizers."""
    words = set(re.findall(r'[a-z0-9_]+', text.casefold()))
    for segment in re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]+', text):
        words.update(segment[index:index + 2] for index in range(len(segment) - 1))
    return words


class ProjectMemory:
    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS project_memories (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    version TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS project_memories_scope
                    ON project_memories(project, status, version);
                CREATE TABLE IF NOT EXISTS project_memory_origins (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    request_hash TEXT NOT NULL
                );
            ''')

    @contextmanager
    def _connection(self):
        with closing(sqlite3.connect(self.database, timeout=30)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    @staticmethod
    def _read(connection, project, memory_id):
        row = connection.execute(
            'SELECT * FROM project_memories WHERE project = ? AND id = ?',
            (project, memory_id),
        ).fetchone()
        if row is None:
            raise ValueError('memory not found')
        return dict(row)

    def add(self, project: str, content: str, *, source: str, version: str,
            kind='constraint', status='pending', memory_id=None) -> dict:
        _text('project', project, 1000)
        request = dict(project=project, content=content, source=source,
                       version=version, kind=kind, status=status)
        _validate(request)
        if memory_id is None:
            memory_id = uuid.uuid4().hex
        _text('id', memory_id, 200)
        request_hash = hashlib.sha256(json.dumps(
            request, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
        ).encode('utf-8')).hexdigest()
        with self._connection() as connection:
            # Reserve and materialize together; two replays cannot both insert.
            connection.execute('BEGIN IMMEDIATE')
            origin = connection.execute(
                'SELECT project, request_hash FROM project_memory_origins WHERE id = ?',
                (memory_id,),
            ).fetchone()
            if origin is not None:
                if origin['project'] != project or origin['request_hash'] != request_hash:
                    raise ValueError('memory id unavailable for this request')
                return self._read(connection, project, memory_id)
            timestamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            row = dict(id=memory_id, **request, created_at=timestamp, updated_at=timestamp)
            connection.execute(
                'INSERT INTO project_memory_origins(id, project, request_hash) VALUES (?, ?, ?)',
                (memory_id, project, request_hash),
            )
            connection.execute(
                'INSERT INTO project_memories (' + ', '.join(_FIELDS) + ') VALUES ('
                + ', '.join('?' for _ in _FIELDS) + ')',
                tuple(row[field] for field in _FIELDS),
            )
            return row

    def list(self, project: str) -> list[dict]:
        _text('project', project, 1000)
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT * FROM project_memories WHERE project = ? ORDER BY created_at, id',
                (project,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update(self, project: str, memory_id: str, /, **fields) -> dict:
        _text('project', project, 1000)
        _text('id', memory_id, 200)
        if set(fields) - _EDITABLE:
            raise ValueError('only content, version, kind and status may be edited')
        _validate(fields)
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            previous = self._read(connection, project, memory_id)
            if fields:
                fields['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='microseconds')
                connection.execute(
                    'UPDATE project_memories SET '
                    + ', '.join(field + ' = ?' for field in fields)
                    + ' WHERE project = ? AND id = ?',
                    (*fields.values(), project, memory_id),
                )
                previous.update(fields)
            return previous

    def delete(self, project: str, memory_id: str) -> dict:
        _text('project', project, 1000)
        _text('id', memory_id, 200)
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            previous = self._read(connection, project, memory_id)
            connection.execute('DELETE FROM project_memories WHERE project = ? AND id = ?',
                               (project, memory_id))
            # Retain only the origin fingerprint, so replay cannot restore content.
            return previous

    def retrieve(self, project: str, query: str, version: str, limit=5) -> list[dict]:
        _text('project', project, 1000)
        _text('version', version, 80)
        if not isinstance(query, str) or len(query) > 8000:
            raise ValueError('invalid memory query')
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError('memory retrieval limit must be an integer from 1 to 10')
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        with self._connection() as connection:
            candidates = connection.execute(
                "SELECT * FROM project_memories WHERE project = ? AND status = 'confirmed' "
                "AND (version = ? OR version = '*') ORDER BY created_at, id",
                (project, version),
            ).fetchall()
        hits = []
        for candidate in candidates:
            row = dict(candidate)
            matched = query_tokens & _tokens(row['content'])
            if matched:
                row['score'] = round(len(matched) / len(query_tokens), 6)
                row['reason'] = '词法匹配：' + '、'.join(sorted(matched)[:12])
                hits.append(row)
        hits.sort(key=lambda row: (-row['score'], row['created_at'], row['id']))
        return hits[:limit]
