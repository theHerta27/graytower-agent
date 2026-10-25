"""Project memory behavior against real, reopenable SQLite databases."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

try:
    from agent_workbench.development.memory import ProjectMemory
except ModuleNotFoundError:
    ProjectMemory = None


class DevelopmentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ProjectMemory, '项目记忆尚未实现')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / 'nested' / 'memory.sqlite3'
        self.memory = ProjectMemory(self.database)

    def add(self, content='护盾计算必须保留整数取整规则', **kwargs):
        return self.memory.add('graytower', content, source=kwargs.pop('source', '用户确认需求#1'),
                               version=kwargs.pop('version', 'v2'), **kwargs)

    def test_default_pending_survives_database_reopen_with_evidence(self):
        row = self.add()
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['kind'], 'constraint')
        self.assertEqual(row['source'], '用户确认需求#1')
        self.assertEqual(row['project'], 'graytower')
        self.assertTrue(row['id'])
        self.assertTrue(row['created_at'])
        self.assertEqual(row['updated_at'], row['created_at'])
        reopened = ProjectMemory(self.database)
        self.assertEqual(reopened.list('graytower'), [row])
        self.assertEqual(reopened.retrieve('graytower', '护盾计算', 'v2'), [])

    def test_user_can_edit_confirm_and_delete_without_changing_origin(self):
        original = self.add()
        edited = self.memory.update('graytower', original['id'], content='护盾必须向下取整',
                                    status='confirmed', kind='decision', version='v3')
        self.assertEqual(edited['content'], '护盾必须向下取整')
        self.assertEqual(edited['status'], 'confirmed')
        self.assertEqual(edited['version'], 'v3')
        self.assertEqual(edited['kind'], 'decision')
        self.assertEqual(edited['source'], original['source'])
        self.assertEqual(edited['created_at'], original['created_at'])
        self.assertGreater(edited['updated_at'], original['updated_at'])
        self.assertEqual(ProjectMemory(self.database).list('graytower'), [edited])
        self.assertEqual(self.memory.delete('graytower', edited['id']), edited)
        self.assertEqual(ProjectMemory(self.database).list('graytower'), [])
        self.assertEqual(self.memory.retrieve('graytower', '护盾', 'v3'), [])

    def test_foreign_project_cannot_read_modify_or_delete_record(self):
        original = self.add(status='confirmed')
        self.assertEqual(self.memory.list('other'), [])
        self.assertEqual(self.memory.retrieve('other', '护盾', 'v2'), [])
        for action in (
            lambda: self.memory.update('other', original['id'], content='changed'),
            lambda: self.memory.delete('other', original['id']),
        ):
            with self.assertRaises(ValueError) as caught:
                action()
            self.assertNotIn(original['content'], str(caught.exception))
            self.assertNotIn(original['source'], str(caught.exception))
        self.assertEqual(self.memory.list('graytower'), [original])

    def test_retrieval_filters_pending_old_versions_and_projects(self):
        current = self.add(status='confirmed')
        shared = self.add('护盾规则通过 Python 实现', version='*', status='confirmed')
        old = self.add('护盾旧版允许小数', version='v1', status='confirmed')
        self.add('护盾伤害尚待用户确认')
        self.memory.add('other', '护盾其它项目', source='other user', version='v2', status='confirmed')
        hits = self.memory.retrieve('graytower', '护盾', 'v2')
        self.assertEqual({hit['id'] for hit in hits}, {current['id'], shared['id']})
        self.assertEqual(len(self.memory.list('graytower')), 4)
        self.assertIn(old, self.memory.list('graytower'))
        self.assertEqual({hit['id'] for hit in self.memory.retrieve('graytower', '护盾', '*')}, {shared['id']})

    def test_chinese_and_english_relevance_has_reasons_and_excludes_noise(self):
        shield = self.add(status='confirmed')
        sqlite = self.add('SQLite receipt writes are atomic transactions', status='confirmed', kind='lesson')
        self.add('营地商店使用金币交易', status='confirmed')
        chinese = self.memory.retrieve('graytower', '修改护盾数值时如何取整', 'v2')
        self.assertEqual([row['id'] for row in chinese], [shield['id']])
        self.assertIn('护盾', chinese[0]['reason'])
        self.assertGreater(chinese[0]['score'], 0)
        english = self.memory.retrieve('graytower', 'SQLITE transaction receipt', 'v2')
        self.assertEqual([row['id'] for row in english], [sqlite['id']])
        for irrelevant in ('音效播放音乐', 'latest', '', '   ', '!!!'):
            self.assertEqual(self.memory.retrieve('graytower', irrelevant, 'v2'), [])

    def test_retrieval_ranks_relevance_and_applies_bounded_limit(self):
        for index in range(13):
            self.add(f'护盾规则 {index}', status='confirmed')
        specific = self.add('护盾取整与伤害抵扣顺序', status='confirmed')
        hits = self.memory.retrieve('graytower', '护盾取整伤害', 'v2', limit=2)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]['id'], specific['id'])
        self.assertEqual(len(self.memory.retrieve('graytower', '护盾', 'v2', limit=10)), 10)
        for invalid in (0, -1, 11, True, '2', 1.5):
            with self.subTest(limit=invalid), self.assertRaises(ValueError):
                self.memory.retrieve('graytower', '护盾', 'v2', limit=invalid)

    def test_add_replay_preserves_user_edits_and_confirmation_after_reopen(self):
        original = self.add(memory_id='proposal:run-1:call-1')
        edited = self.memory.update('graytower', original['id'], content='护盾取整已确认',
                                    status='confirmed', version='v3', kind='lesson')
        self.memory = ProjectMemory(self.database)
        replay = self.add(memory_id='proposal:run-1:call-1')
        self.assertEqual(replay, edited)
        self.assertEqual(len(self.memory.list('graytower')), 1)
        for changed in (
            {'content': '不同内容'}, {'source': 'different origin'}, {'version': 'v4'},
            {'status': 'confirmed'}, {'kind': 'decision'},
        ):
            content = changed.get('content', original['content'])
            kwargs = {key: value for key, value in changed.items() if key != 'content'}
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.add(content, memory_id=original['id'], **kwargs)
        with self.assertRaises(ValueError):
            self.memory.add('other', original['content'], source=original['source'],
                            version='v2', memory_id=original['id'])
        self.assertEqual(self.memory.list('graytower'), [edited])

    def test_deleted_proposal_is_not_resurrected_by_replay(self):
        row = self.add(memory_id='deleted-proposal')
        self.memory.delete('graytower', row['id'])
        self.memory = ProjectMemory(self.database)
        with self.assertRaises(ValueError):
            self.add(memory_id=row['id'])
        self.assertEqual(self.memory.list('graytower'), [])

    def test_concurrent_same_proposal_has_one_record(self):
        def propose(_):
            store = ProjectMemory(self.database)
            return store.add('graytower', '护盾顺序', source='tool evidence #2', version='v2',
                             memory_id='same-proposal')
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(propose, range(8)))
        self.assertTrue(all(row == rows[0] for row in rows))
        self.assertEqual(self.memory.list('graytower'), [rows[0]])

    def test_invalid_add_is_rejected_without_partial_writes(self):
        cases = (
            {'content': ''}, {'content': ' '}, {'content': 'x' * 2001}, {'content': None},
            {'source': ''}, {'source': 'x' * 501}, {'version': ''}, {'version': 'x' * 81},
            {'kind': 'permission'}, {'status': 'assumed'}, {'memory_id': ''},
        )
        for invalid in cases:
            content = invalid.get('content', '护盾约束')
            kwargs = {key: value for key, value in invalid.items() if key != 'content'}
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.add(content, **kwargs)
        for project in ('', ' ', 'x' * 1001, None):
            with self.subTest(project=project), self.assertRaises(ValueError):
                self.memory.add(project, 'content', source='user', version='v2')
        self.assertEqual(self.memory.list('graytower'), [])

    def test_invalid_edits_do_not_mutate_record_or_evidence(self):
        row = self.add()
        for invalid in (
            {'source': 'forged'}, {'project': 'other'}, {'id': 'other'},
            {'created_at': 'later'}, {'status': 'assumed'}, {'kind': 'permission'},
            {'version': 'x' * 81}, {'content': 'x' * 2001}, {'content': ''},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.memory.update('graytower', row['id'], **invalid)
        with self.assertRaises(ValueError):
            self.memory.update('graytower', 'missing', status='confirmed')
        with self.assertRaises(ValueError):
            self.memory.delete('graytower', 'missing')
        self.assertEqual(self.memory.list('graytower'), [row])


if __name__ == '__main__':
    unittest.main()
