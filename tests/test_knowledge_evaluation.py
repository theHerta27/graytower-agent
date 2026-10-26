"""Offline retrieval metrics and complete real-Git evaluation fixture."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    from agent_workbench.development.knowledge_evaluation import evaluate_retrieval, retrieval_metrics
except ModuleNotFoundError:
    evaluate_retrieval = retrieval_metrics = None


class KnowledgeMetricTests(unittest.TestCase):
    def test_hand_calculated_section_recall_preserves_chunk_ranks(self):
        self.assertIsNotNone(retrieval_metrics, 'retrieval evaluator is not implemented')
        rows = [
            {'expected': ['A', 'B'], 'retrieved_source_ids': ['A', 'A', 'C', 'B']},
            {'expected': ['C'], 'retrieved_source_ids': ['B', 'C']},
            {'expected': ['D'], 'retrieved_source_ids': []},
            {'expected': [], 'retrieved_source_ids': ['B']},
        ]
        scores = retrieval_metrics(rows)
        self.assertEqual(scores['relevant_queries'], 3)
        self.assertEqual(scores['unrelated_queries'], 1)
        self.assertAlmostEqual(scores['hit_at_k']['1'], 1/3)
        self.assertAlmostEqual(scores['recall_at_k']['1'], 1/6)
        self.assertAlmostEqual(scores['hit_at_k']['3'], 2/3)
        self.assertAlmostEqual(scores['recall_at_k']['3'], 1/2)
        self.assertAlmostEqual(scores['recall_at_k']['5'], 2/3)
        self.assertEqual(scores['false_positive_at_k']['1']['count'], 1)
        self.assertEqual(scores['false_positive_at_k']['5']['rate'], 1)

    def test_empty_denominators_are_unknown_not_perfect_scores(self):
        self.assertIsNotNone(retrieval_metrics)
        scores = retrieval_metrics([{'expected': [], 'retrieved_source_ids': []}])
        self.assertIsNone(scores['hit_at_k']['1'])
        self.assertIsNone(scores['recall_at_k']['3'])
        self.assertEqual(scores['false_positive_at_k']['5']['rate'], 0)


class KnowledgeEvaluationGitTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(evaluate_retrieval, 'retrieval evaluator is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root/'source'; self.project.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        code = self.project/'game-core/combat_core/v2/effects.py'
        code.parent.mkdir(parents=True); code.write_bytes(b'VALUE = 1\n')
        self.text = '# Fixture\n## Speed\nremaining_distance preserves action progress.\n## History\nold_untrusted_rule\n'
        source = self.project/'docs/rules.md'; source.parent.mkdir()
        source.write_bytes(self.text.encode())
        self.git('add', '.'); self.git('commit', '-qm', 'fixture')
        self.head = self.git('rev-parse', 'HEAD').decode().strip()
        self.corpus = {'schema': 'knowledge-retrieval-corpus-v1', 'project': self.project.as_posix(),
            'game_head': self.head, 'confirmation': 'audit_fixture_only', 'sources': [{
                'id': 'speed', 'path': 'docs/rules.md', 'source_path': source.as_posix(),
                'heading': 'Speed', 'sha256': hashlib.sha256(self.text.encode()).hexdigest(),
                'section_sha256': hashlib.sha256(b'## Speed\nremaining_distance preserves action progress.\n').hexdigest()}]}
        self.queries = {'schema': 'knowledge-retrieval-queries-v1', 'queries': [
            {'id': 'dev-speed', 'split': 'dev', 'query': 'remaining_distance', 'expected': ['speed']},
            {'id': 'holdout-unrelated', 'split': 'holdout', 'query': 'banana oven', 'expected': []},
            {'id': 'holdout-synonym', 'split': 'holdout', 'query': 'haste gauge carryover', 'expected': ['speed']},
        ]}
        self.corpus_path = self.root/'corpus.json'; self.queries_path = self.root/'queries.json'
        self.save()

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'safe.directory='+self.project.as_posix(),
            '-C', str(self.project), *args], stderr=subprocess.PIPE)

    def save(self):
        self.corpus_path.write_text(json.dumps(self.corpus), encoding='utf-8')
        self.queries_path.write_text(json.dumps(self.queries), encoding='utf-8')

    def evaluate(self, output):
        return evaluate_retrieval(self.project, output, corpus_path=self.corpus_path, queries_path=self.queries_path)

    def test_complete_fixture_seals_exact_sections_and_keeps_misses(self):
        output = self.root/'evaluation'
        result = self.evaluate(output)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['cost_usd'], '0')
        self.assertEqual(result['game_head'], self.head)
        self.assertEqual(result['confirmation'], 'audit_fixture_only')
        self.assertEqual(result['queries'][0]['retrieved_source_ids'], ['speed'])
        self.assertEqual(result['queries'][1]['results'], [])
        self.assertEqual(result['queries'][2]['missing_at_5'], ['speed'])
        self.assertEqual(result['metrics']['all']['hit_at_k']['1'], .5)
        self.assertGreaterEqual(result['queries'][0]['elapsed_ms'], 0)
        snapshot = json.loads((output/'snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual(len(snapshot['documents']), 1)
        self.assertEqual(snapshot['documents'][0]['headings'], ['Speed'])
        self.assertNotIn('old_untrusted_rule', json.dumps(snapshot))
        hit = result['queries'][0]['results'][0]
        self.assertEqual(hit['document_id'], snapshot['documents'][0]['id'])
        self.assertEqual(hit['source_id'], 'speed')
        self.assertEqual(hit['version'], self.head)
        self.assertEqual((hit['start_line'], hit['end_line']), (2, 3))
        self.assertTrue((output/'evaluation-report.md').is_file())
        self.assertTrue((output/'manifest.json').is_file())
        self.assertTrue((output/'task/request.json').is_file())
        self.assertFalse((self.project/'project-knowledge.sqlite').exists())
        self.assertEqual(self.git('status', '--porcelain').strip(), b'')
        with self.assertRaisesRegex(ValueError, 'fresh'):
            self.evaluate(output)

    def test_wrong_version_and_blob_hash_are_rejected_without_task(self):
        for field in ('game_head', 'sha256'):
            original = copy.deepcopy(self.corpus)
            if field == 'game_head': self.corpus[field] = '0'*40
            else: self.corpus['sources'][0][field] = '0'*64
            self.save(); output = self.root/field
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'version|hash'):
                self.evaluate(output)
            self.assertFalse((output/'task').exists())
            self.corpus = original

    def test_section_hash_and_unknown_expected_source_are_rejected(self):
        self.corpus['sources'][0]['section_sha256'] = '0'*64
        self.save()
        with self.assertRaisesRegex(ValueError, 'section.*hash'):
            self.evaluate(self.root/'section-hash')
        self.corpus['sources'][0]['section_sha256'] = hashlib.sha256(
            b'## Speed\nremaining_distance preserves action progress.\n').hexdigest()
        self.queries['queries'][0]['expected'] = ['not-in-corpus']
        self.save()
        with self.assertRaisesRegex(ValueError, 'expected'):
            self.evaluate(self.root/'bad-query')

    def test_output_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.evaluate(self.project/'evaluation')


if __name__ == '__main__':
    unittest.main()
