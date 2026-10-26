"""Knowledge boundaries use real Git blobs, never working-copy document reads."""
import copy
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from agent_workbench.development.workspace import ProjectWorkspace

try:
    from agent_workbench.development.knowledge import KnowledgeBase, search_knowledge, read_knowledge
except ModuleNotFoundError:
    KnowledgeBase = None


TEXT = '# Combat Guide\nOpening text.\n## Effects\n护盾刷新遵循最大值规则。\n### Refresh\nUse shield_refresh and DamageContext.\n## Resources\n技能点不能为负数。\n'


class DevelopmentKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(KnowledgeBase, 'frozen knowledge store is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.write('game-core/combat_core/v2/effects.py', 'VALUE = 1\n')
        self.write('README.md', '# Project\nLocal game rules.\n')
        self.write('docs/combat.md', TEXT)
        self.write('docs/nested/input.md', '# Input\nValidate resource_amount.\n')
        self.write('private.md', '# Private\nnot allowed\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')
        self.workspace = ProjectWorkspace.create(self.source, self.root / 'task')
        self.project = self.workspace.metadata['project']
        self.version = self.workspace.metadata['baseline_commit']
        self.kb = KnowledgeBase(self.root / 'knowledge.sqlite')

    def git(self, *args, input=None):
        return subprocess.check_output(['git', '-c', 'safe.directory='+self.source.as_posix(),
            '-C', str(self.source), *args], input=input, stderr=subprocess.PIPE)

    def write(self, name, text):
        path = self.source / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode('utf-8'))

    def confirmed(self, path='docs/combat.md', headings=None):
        document = self.kb.import_file(self.workspace, path, headings)
        return self.kb.set_status(self.project, document['id'], 'confirmed')

    def test_sources_and_preview_are_baseline_git_blobs(self):
        self.write('docs/combat.md', 'uncommitted replacement')
        self.write('docs/new.md', 'untracked')
        self.assertEqual([x['path'] for x in self.kb.sources(self.workspace)],
            ['README.md', 'docs/combat.md', 'docs/nested/input.md'])
        preview = self.kb.preview_file(self.workspace, 'docs/combat.md')
        self.assertEqual(preview['sha256'], hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertEqual(preview['version'], self.version)
        self.assertEqual(preview['title'], 'Combat Guide')
        refresh = next(x for x in preview['sections'] if x['heading'] == 'Refresh')
        self.assertEqual((refresh['start_line'], refresh['end_line']), (5, 6))
        self.assertEqual(refresh['text'], '### Refresh\nUse shield_refresh and DamageContext.\n')

    def test_parent_selection_includes_descendants_and_omits_siblings(self):
        doc = self.kb.import_file(self.workspace, 'docs/combat.md', ['Effects'])
        self.assertEqual(doc['status'], 'pending')
        self.assertEqual(doc['headings'], ['Effects'])
        self.assertEqual([x['heading'] for x in doc['chunks']], ['Effects', 'Refresh'])
        self.assertEqual(doc['chunks'][0]['start_line'], 3)
        self.assertNotIn('技能点', ''.join(x['text'] for x in doc['chunks']))

    def test_idempotency_preserves_confirmation_and_canonical_selection(self):
        first = self.confirmed(headings=['Resources', 'Effects'])
        again = self.kb.import_file(self.workspace, 'docs/combat.md', ['Effects', 'Resources', 'Effects'])
        self.assertEqual(first, again)
        self.assertEqual(len(self.kb.list(self.project)), 1)
        reopened = KnowledgeBase(self.root / 'knowledge.sqlite')
        self.assertEqual(reopened.list(self.project)[0], first)

    def test_pending_old_version_and_other_project_are_excluded(self):
        self.kb.import_file(self.workspace, 'README.md')
        doc = self.confirmed()
        self.assertEqual(self.kb.snapshot(self.project, self.version)['documents'], [doc])
        self.assertEqual(self.kb.snapshot(self.project, 'a'*40)['documents'], [])
        self.assertEqual(self.kb.snapshot('another-project', self.version)['documents'], [])
        self.assertEqual(self.kb.list(self.project, 'a'*40), [])
        with self.assertRaises(ValueError): self.kb.set_status('other', doc['id'], 'confirmed')
        with self.assertRaises(ValueError): self.kb.delete('other', doc['id'])
        with self.assertRaises(ValueError): self.kb.set_status(self.project, doc['id'], 'published')

    def test_new_commit_import_has_distinct_identity_and_keeps_old_source(self):
        old = self.confirmed()
        self.write('docs/combat.md', TEXT+'New baseline only.\n')
        self.git('add', '.'); self.git('commit', '-qm', 'second')
        other = ProjectWorkspace.create(self.source, self.root / 'task2')
        newer = self.kb.import_file(other, 'docs/combat.md')
        self.assertNotEqual(old['id'], newer['id'])
        self.assertEqual(self.kb.preview_file(self.workspace, 'docs/combat.md')['sha256'], old['sha256'])
        self.assertEqual(self.kb.snapshot(self.project, self.version)['documents'], [old])

    def test_paths_cannot_escape_or_address_arbitrary_files(self):
        for path in ('../README.md', '/README.md', 'D:/README.md', 'docs/../README.md',
                     'docs\\combat.md', 'private.md', 'docs//combat.md', 'docs/missing.md'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.kb.preview_file(self.workspace, path)
            with self.subTest(import_path=path), self.assertRaises(ValueError):
                self.kb.import_file(self.workspace, path)

    def test_git_symlink_is_never_previewed_or_listed(self):
        oid = self.git('hash-object', '-w', '--stdin', input=b'../private.md').decode().strip()
        self.git('update-index', '--add', '--cacheinfo', '120000,'+oid+',docs/link.md')
        self.git('commit', '-qm', 'linked document')
        linked = copy.copy(self.workspace)
        linked.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        self.assertNotIn('docs/link.md', [x['path'] for x in self.kb.sources(linked)])
        with self.assertRaises(ValueError): self.kb.preview_file(linked, 'docs/link.md')

    def test_unknown_and_ambiguous_headings_are_rejected(self):
        for headings in (['missing'], [], 'Effects', [3]):
            with self.subTest(headings=headings), self.assertRaises(ValueError):
                self.kb.import_file(self.workspace, 'docs/combat.md', headings)
        self.write('docs/duplicate.md', '# One\n## Same\nA\n## Same\nB\n')
        self.git('add', '.'); self.git('commit', '-qm', 'duplicate headings')
        duplicate = copy.copy(self.workspace)
        duplicate.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        with self.assertRaises(ValueError): self.kb.import_file(duplicate, 'docs/duplicate.md', ['Same'])

    def test_code_fence_headings_are_not_sections_and_setext_is_supported(self):
        self.write('docs/markdown.md', 'Guide\n=====\n```python\n# not a heading\n```\nRules\n-----\nText.\n')
        self.git('add', '.'); self.git('commit', '-qm', 'markdown')
        altered = copy.copy(self.workspace)
        altered.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        preview = self.kb.preview_file(altered, 'docs/markdown.md')
        self.assertEqual([x['heading'] for x in preview['sections']], ['Guide', 'Rules'])

    def test_chinese_and_latin_lexical_search_has_citations_and_no_unrelated_hits(self):
        self.confirmed()
        snapshot = self.kb.snapshot(self.project, self.version)
        for query, expected in [('护盾刷新', 'Effects'), ('shield_refresh', 'Refresh'), ('DamageContext', 'Refresh')]:
            with self.subTest(query=query):
                hits = search_knowledge(snapshot, query)
                self.assertEqual(hits[0]['heading'], expected)
                self.assertEqual(hits[0]['path'], 'docs/combat.md')
                self.assertEqual(hits[0]['version'], self.version)
                self.assertIn('score', hits[0]); self.assertIn('reason', hits[0])
                self.assertEqual(read_knowledge(snapshot, hits[0]['id'])['text'], hits[0]['text'])
        for query in ('nonexistent_unique', '', ' ', '%', '" OR * : %'):
            self.assertEqual(search_knowledge(snapshot, query), [])
        with self.assertRaises(ValueError): read_knowledge(snapshot, 'unknown')

    def test_frozen_retrieval_survives_database_deletion_and_status_change(self):
        doc = self.confirmed()
        snapshot = self.kb.snapshot(self.project, self.version)
        before = search_knowledge(snapshot, '护盾刷新')
        self.kb.set_status(self.project, doc['id'], 'pending')
        self.assertEqual(self.kb.snapshot(self.project, self.version)['documents'], [])
        self.assertEqual(self.kb.delete(self.project, doc['id'])['id'], doc['id'])
        self.assertEqual(search_knowledge(snapshot, '护盾刷新'), before)
        before[0]['text'] = 'caller mutation'
        self.assertNotEqual(read_knowledge(snapshot, before[0]['id'])['text'], 'caller mutation')

    def test_snapshot_tampering_is_rejected(self):
        self.confirmed()
        snapshot = self.kb.snapshot(self.project, self.version)
        mutations = [lambda s: s.update(schema='other'), lambda s: s.update(version='wrong'),
            lambda s: s['documents'][0].update(status='pending'),
            lambda s: s['documents'][0].update(sha256='0'*64),
            lambda s: s['documents'][0]['chunks'][0].update(text='injected'),
            lambda s: s['documents'][0]['chunks'][0].update(start_line=0)]
        for mutate in mutations:
            broken = copy.deepcopy(snapshot); mutate(broken)
            with self.assertRaises(ValueError): search_knowledge(broken, 'shield')
            with self.assertRaises(ValueError): read_knowledge(broken, snapshot['documents'][0]['chunks'][0]['id'])

    def test_query_and_limit_bounds(self):
        snapshot = self.kb.snapshot(self.project, self.version)
        for query, limit in [('a'*501, 5), (None, 5), ('a', 0), ('a', 11), ('a', True)]:
            with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                search_knowledge(snapshot, query, limit)

    def test_large_file_is_rejected_before_blob_read(self):
        self.write('docs/large.md', 'x'*500001)
        self.git('add', '.'); self.git('commit', '-qm', 'oversized')
        altered = copy.copy(self.workspace)
        altered.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        with self.assertRaises(ValueError): self.kb.preview_file(altered, 'docs/large.md')

    def test_long_lines_are_bounded_chunks_with_accurate_ranges(self):
        self.write('docs/long.md', '# Long\n'+('shield_refresh '*300)+'\nNext line.\n')
        self.git('add', '.'); self.git('commit', '-qm', 'long text')
        altered = copy.copy(self.workspace)
        altered.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        doc = self.kb.import_file(altered, 'docs/long.md')
        self.assertGreater(len(doc['chunks']), 2)
        self.assertTrue(all(len(x['text']) <= 1800 for x in doc['chunks']))
        self.assertEqual(''.join(x['text'] for x in doc['chunks']), '# Long\n'+('shield_refresh '*300)+'\nNext line.\n')
        self.assertEqual(doc['chunks'][-1]['end_line'], 3)

    def test_snapshot_size_is_bounded(self):
        for n in range(3): self.write(f'docs/big{n}.md', '# Large\n'+'x'*350000)
        self.git('add', '.'); self.git('commit', '-qm', 'snapshot bound')
        altered = copy.copy(self.workspace)
        altered.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        for n in range(3):
            doc = self.kb.import_file(altered, f'docs/big{n}.md')
            self.kb.set_status(self.project, doc['id'], 'confirmed')
        # The stored JSON includes citation metadata for every bounded chunk.
        with self.assertRaises(ValueError): self.kb.snapshot(self.project, altered.metadata['baseline_commit'])

    def test_pathological_heading_is_rejected_before_metadata_amplification(self):
        self.write('docs/heading.md', '# '+('A'*10000)+'\nBody.\n')
        self.git('add', '.'); self.git('commit', '-qm', 'huge heading')
        altered = copy.copy(self.workspace)
        altered.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        with self.assertRaises(ValueError): self.kb.preview_file(altered, 'docs/heading.md')

    def test_invalid_utf8_and_binary_markdown_are_rejected(self):
        for name, raw in [('utf8', b'\xff'), ('binary', b'# Title\n\x00')]:
            (self.source / 'docs' / (name+'.md')).write_bytes(raw)
        self.git('add', '.'); self.git('commit', '-qm', 'invalid text')
        altered = copy.copy(self.workspace)
        altered.metadata = {**self.workspace.metadata, 'baseline_commit': self.git('rev-parse', 'HEAD').decode().strip()}
        for name in ('utf8', 'binary'):
            with self.assertRaises(ValueError): self.kb.import_file(altered, 'docs/'+name+'.md')

    def test_search_connections_are_owned_by_each_call(self):
        from concurrent.futures import ThreadPoolExecutor
        self.confirmed()
        snapshot = self.kb.snapshot(self.project, self.version)
        with ThreadPoolExecutor(max_workers=4) as pool:
            outputs = list(pool.map(lambda _: search_knowledge(snapshot, 'shield_refresh'), range(8)))
        self.assertTrue(outputs[0])
        self.assertTrue(all(output == outputs[0] for output in outputs))

    def test_malformed_snapshot_shapes_raise_value_error(self):
        for snapshot in (None, [], {}, {'schema': 'development-knowledge-v1'},
                         dict(schema='development-knowledge-v1', project=self.project, version=self.version, documents=[None])):
            with self.assertRaises(ValueError): search_knowledge(snapshot, 'shield')


if __name__ == '__main__': unittest.main()
