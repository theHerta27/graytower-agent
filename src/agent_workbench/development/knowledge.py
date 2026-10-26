"""Confirmed Git documents and deterministic, snapshot-only lexical retrieval.

This module has no model or mutable-workspace read path. Confirmation is a
host/user action; document prose never grants authority to the agent.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import copy
import hashlib
import re
import sqlite3
from pathlib import Path

from .workspace import clean_name, digest, encoded, git

MAX_FILE = 500_000
MAX_SNAPSHOT = 1_000_000
MAX_DOCUMENTS = 1200
MAX_CHUNK = 1800
MAX_HEADING = 1000
SCHEMA = 'development-knowledge-v1'


def _text(value, maximum=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise ValueError('invalid knowledge metadata')
    return value


def _path(path):
    clean_name(path)
    if path != 'README.md' and not (path.startswith('docs/') and path.endswith('.md')):
        raise ValueError('knowledge source must be README.md or docs Markdown')
    return path


def _scope(workspace):
    project = _text(workspace.metadata['project'])
    version = workspace.metadata['baseline_commit']
    if not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', version):
        raise ValueError('knowledge requires an immutable Git commit')
    return project, version


def _entries(workspace):
    project, version = _scope(workspace)
    entries = {}
    for entry in git(project, 'ls-tree', '-rlz', version).split(b'\0'):
        if not entry:
            continue
        header, raw_name = entry.split(b'\t', 1)
        name = raw_name.decode('utf-8', errors='replace')
        try:
            _path(name)
        except ValueError:
            continue
        mode, kind, oid, size = header.decode('ascii').split()
        if mode not in ('100644', '100755') or kind != 'blob':
            continue
        entries[name] = (oid, int(size))
        if len(entries) > MAX_DOCUMENTS:
            raise ValueError('too many knowledge source documents')
    return entries


def _sections(text):
    """ATX/setext sections, ignoring headings inside fenced code blocks."""
    lines = text.splitlines(keepends=True)
    headings, fence = [], None
    for index, line in enumerate(lines):
        stripped = line.rstrip('\r\n')
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', stripped)
        if marker:
            run, remainder = marker.groups()
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1] and not remainder.strip():
                fence = None
            continue
        if fence:
            continue
        match = re.match(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$', stripped)
        if match:
            heading = re.sub(r'[ \t]+#+[ \t]*$', '', match[2] or '').strip()
            headings.append((index, len(match[1]), heading))
            continue
        underline = re.fullmatch(r' {0,3}(=+|-+)[ \t]*', stripped)
        if underline and index and lines[index-1].strip() and not re.match(r'^\s*(?:#|`{3,}|~{3,})', lines[index-1]):
            start = index-1
            if not headings or headings[-1][0] != start:
                headings.append((start, 1 if underline[1][0] == '=' else 2, lines[start].strip()))
    if not headings or headings[0][0] > 0:
        headings.insert(0, (0, 0, ''))
    result = []
    for index, (start, level, heading) in enumerate(headings):
        if len(heading) > MAX_HEADING:
            raise ValueError('Markdown heading exceeds supported limit')
        end = headings[index+1][0] if index+1 < len(headings) else len(lines)
        if end > start:
            result.append(dict(heading=heading, start_line=start+1, end_line=end,
                               text=''.join(lines[start:end]), level=level))
    return result


def _identity(document):
    return digest({key: document[key] for key in ('project', 'path', 'version', 'sha256', 'title', 'headings')})


def _chunk_id(chunk):
    return digest({key: value for key, value in chunk.items() if key != 'id'})


def _chunks(document, sections):
    chunks = []
    for section in sections:
        buffer, start, end = '', section['start_line'], section['start_line']

        def append():
            chunk = {key: document[key] for key in ('path', 'title', 'version')}
            chunk.update(document_id=document['id'], text=buffer, heading=section['heading'],
                         start_line=start, end_line=end, index=len(chunks))
            chunk['id'] = _chunk_id(chunk)
            chunks.append(chunk)

        for number, line in enumerate(section['text'].splitlines(keepends=True), section['start_line']):
            for offset in range(0, len(line), MAX_CHUNK):
                piece = line[offset:offset+MAX_CHUNK]
                if buffer and len(buffer)+len(piece) > MAX_CHUNK:
                    append(); buffer = ''
                if not buffer:
                    start = number
                buffer += piece; end = number
        if buffer:
            append()
    return chunks


class KnowledgeBase:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS development_knowledge (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, version TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS development_knowledge_scope
                    ON development_knowledge(project, version, status);
            ''')

    @contextmanager
    def _connection(self):
        with closing(sqlite3.connect(self.database, timeout=30)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    def sources(self, workspace):
        return [{'path': path} for path in sorted(_entries(workspace))]

    def preview_file(self, workspace, path):
        _path(path)
        project, version = _scope(workspace)
        entry = _entries(workspace).get(path)
        if entry is None:
            raise ValueError('knowledge source missing or not a regular Git blob')
        oid, size = entry
        if size > MAX_FILE:
            raise ValueError('knowledge source exceeds 500 KB')
        raw = git(project, 'cat-file', 'blob', oid)
        if len(raw) > MAX_FILE:
            raise ValueError('knowledge source exceeds 500 KB')
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('knowledge source must be UTF-8 Markdown') from error
        if '\x00' in text:
            raise ValueError('knowledge source contains binary text')
        sections = _sections(text)
        title = next((s['heading'] for s in sections if s['level'] == 1 and s['heading']), Path(path).stem)
        return dict(path=path, version=version, sha256=hashlib.sha256(raw).hexdigest(), title=title,
                    sections=[{k: v for k, v in s.items() if k != 'level'} for s in sections])

    def import_file(self, workspace, path, headings=None):
        preview = self.preview_file(workspace, path)
        # Preview text is the exact Git blob partition; there is no file-system read.
        sections = _sections(''.join(section['text'] for section in preview['sections']))
        if headings is not None:
            if not isinstance(headings, list) or not headings or len(headings) > MAX_DOCUMENTS:
                raise ValueError('select a nonempty list of exact Markdown headings')
            if any(not isinstance(h, str) or not h.strip() or len(h) > MAX_FILE for h in headings):
                raise ValueError('invalid knowledge heading')
            headings = sorted(set(headings))
            selected = set()
            for heading in headings:
                matches = [i for i, section in enumerate(sections) if section['heading'] == heading]
                if len(matches) != 1:
                    raise ValueError('unknown or ambiguous Markdown heading')
                index = matches[0]; selected.add(index)
                for child in range(index+1, len(sections)):
                    if sections[child]['level'] <= sections[index]['level']:
                        break
                    selected.add(child)
            sections = [section for i, section in enumerate(sections) if i in selected]
        document = {key: preview[key] for key in ('path', 'version', 'sha256', 'title')}
        document.update(project=_scope(workspace)[0], status='pending', headings=headings)
        document['id'] = _identity(document)
        document['chunks'] = _chunks(document, sections)
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT payload FROM development_knowledge WHERE id=?', (document['id'],)).fetchone()
            if row is not None:
                return _decode(row['payload'])
            count = connection.execute('SELECT COUNT(*) FROM development_knowledge WHERE project=?',
                                       (document['project'],)).fetchone()[0]
            if count >= MAX_DOCUMENTS:
                raise ValueError('too many imported knowledge documents')
            connection.execute('INSERT INTO development_knowledge VALUES (?,?,?,?,?)',
                (document['id'], document['project'], document['version'], document['status'], encoded(document).decode()))
        return document

    def list(self, project, version=None):
        _text(project)
        if version is not None:
            _text(version, 100)
        query = 'SELECT payload FROM development_knowledge WHERE project=?'
        parameters = [project]
        if version is not None:
            query += ' AND version=?'; parameters.append(version)
        with self._connection() as connection:
            rows = connection.execute(query+' ORDER BY id', parameters).fetchall()
        return sorted((_decode(row['payload']) for row in rows), key=lambda d: (d['path'], d['version'], d['id']))

    @staticmethod
    def _read(connection, project, document_id):
        _text(project); _text(document_id, 64)
        row = connection.execute('SELECT payload FROM development_knowledge WHERE project=? AND id=?',
                                 (project, document_id)).fetchone()
        if row is None:
            raise ValueError('knowledge document not found')
        return _decode(row['payload'])

    def set_status(self, project, document_id, status):
        if status not in ('pending', 'confirmed'):
            raise ValueError('knowledge status must be pending or confirmed')
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            document = self._read(connection, project, document_id)
            document['status'] = status
            connection.execute('UPDATE development_knowledge SET status=?,payload=? WHERE project=? AND id=?',
                               (status, encoded(document).decode(), project, document_id))
        return document

    def delete(self, project, document_id):
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            document = self._read(connection, project, document_id)
            connection.execute('DELETE FROM development_knowledge WHERE project=? AND id=?', (project, document_id))
        return document

    def snapshot(self, project, version):
        _text(version, 100)
        snapshot = dict(schema=SCHEMA, project=project, version=version,
                        documents=[d for d in self.list(project, version) if d['status'] == 'confirmed'])
        _validate_snapshot(snapshot)
        return snapshot


def _decode(value):
    import json
    return json.loads(value)


def _validate_snapshot(snapshot):
    """Fail closed on scope/identity drift; the caller separately seals snapshot bytes."""
    try:
        if not isinstance(snapshot, dict) or snapshot.get('schema') != SCHEMA:
            raise ValueError('unsupported knowledge snapshot')
        if len(encoded(snapshot)) > MAX_SNAPSHOT:
            raise ValueError('knowledge snapshot exceeds 1 MB')
        project = _text(snapshot['project']); version = _text(snapshot['version'], 100)
        documents = snapshot['documents']
        if not isinstance(documents, list) or len(documents) > MAX_DOCUMENTS:
            raise ValueError('invalid knowledge documents')
        ids, chunk_ids, chunks = set(), set(), []
        for document in documents:
            if document['project'] != project or document['version'] != version or document['status'] != 'confirmed':
                raise ValueError('knowledge scope or confirmation mismatch')
            _path(document['path']); _text(document['title'], MAX_HEADING)
            if not re.fullmatch(r'[a-f0-9]{64}', document['sha256']):
                raise ValueError('invalid source SHA256')
            headings = document['headings']
            if headings is not None and (not isinstance(headings, list) or not headings or
                    any(not isinstance(h, str) or not h.strip() or len(h) > MAX_HEADING for h in headings) or headings != sorted(set(headings))):
                raise ValueError('invalid selected headings')
            if document['id'] != _identity(document) or document['id'] in ids:
                raise ValueError('invalid document identity')
            ids.add(document['id'])
            if not isinstance(document['chunks'], list) or len(document['chunks']) > 10000:
                raise ValueError('invalid document chunks')
            previous = 0
            for index, chunk in enumerate(document['chunks']):
                if (chunk['document_id'] != document['id'] or type(chunk['index']) is not int or chunk['index'] != index or
                        any(chunk[key] != document[key] for key in ('path', 'title', 'version'))):
                    raise ValueError('chunk source metadata mismatch')
                if (type(chunk['start_line']) is not int or type(chunk['end_line']) is not int or
                        not 1 <= chunk['start_line'] <= chunk['end_line'] or chunk['start_line'] < previous):
                    raise ValueError('invalid source line range')
                previous = chunk['end_line']
                if (not isinstance(chunk['text'], str) or not chunk['text'] or len(chunk['text']) > MAX_CHUNK or
                        not isinstance(chunk['heading'], str) or len(chunk['heading']) > MAX_HEADING or
                        chunk['id'] != _chunk_id(chunk) or chunk['id'] in chunk_ids):
                    raise ValueError('invalid frozen chunk identity')
                chunk_ids.add(chunk['id']); chunks.append(chunk)
        return chunks
    except (KeyError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError('malformed knowledge snapshot') from error


def _tokens(text):
    tokens = re.findall(r'[a-z0-9_]+', text.casefold())
    for segment in re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]+', text):
        tokens.extend(segment[i:i+2] for i in range(len(segment)-1))
    return tokens


def search_knowledge(snapshot, query, limit=5):
    if not isinstance(query, str) or len(query) > 500 or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('require query at most 500 characters and limit 1..10')
    chunks = _validate_snapshot(snapshot)
    tokens = sorted(set(_tokens(query)))
    if not tokens or not chunks:
        return []
    # The tokenizer emits only literal word/bigram terms; quoting also protects
    # the FTS grammar. Every call owns its connection, including graph threads.
    match = ' OR '.join('"'+token.replace('"', '""')+'"' for token in tokens)
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.execute('CREATE VIRTUAL TABLE search_chunks USING fts5(terms, tokenize="unicode61 tokenchars _")')
        connection.executemany('INSERT INTO search_chunks(rowid,terms) VALUES (?,?)',
            ((index+1, ' '.join(_tokens(chunk['title']+' '+chunk['heading']+' '+chunk['text']))) for index, chunk in enumerate(chunks)))
        rows = connection.execute('SELECT rowid,bm25(search_chunks) FROM search_chunks WHERE search_chunks MATCH ? ORDER BY bm25(search_chunks),rowid LIMIT ?',
                                  (match, limit)).fetchall()
    result = []
    for rowid, score in rows:
        chunk = copy.deepcopy(chunks[rowid-1])
        matched = set(_tokens(chunk['title']+' '+chunk['heading']+' '+chunk['text'])) & set(tokens)
        chunk.update(score=-score, reason='FTS5 BM25 lexical match: '+', '.join(sorted(matched)))
        result.append(chunk)
    return result


def read_knowledge(snapshot, chunk_id, start_char=0, max_chars=None):
    _text(chunk_id, 64)
    if type(start_char) is not int or start_char < 0 or (max_chars is not None and
            (type(max_chars) is not int or not 1 <= max_chars <= 500)):
        raise ValueError('require start_char >= 0 and max_chars 1..500')
    for chunk in _validate_snapshot(snapshot):
        if chunk['id'] == chunk_id:
            value=copy.deepcopy(chunk)
            if start_char >= len(chunk['text']):
                raise ValueError('start_char is outside the frozen chunk')
            if max_chars is not None:
                end=min(start_char+max_chars,len(chunk['text']))
                value.update(text=chunk['text'][start_char:end],start_char=start_char,
                             next_char=end if end<len(chunk['text']) else None,total_chars=len(chunk['text']))
            elif start_char:
                raise ValueError('max_chars required for paged read')
            return value
    raise ValueError('knowledge chunk not found in frozen snapshot')
