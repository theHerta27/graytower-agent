"""Offline scorer behavior, never real-model quality or battle acceptance."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1] / 'research/evals/config-qa-v1'


class BusinessAcceptanceTests(unittest.TestCase):
    def setUp(self):
        path = PACKAGE / 'evaluate.py'
        self.assertTrue(path.is_file(), 'the business scorer is not implemented yet')
        spec = importlib.util.spec_from_file_location('business_evaluate', path)
        self.scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.scorer)
        self.package = json.loads((PACKAGE / 'cases.json').read_text(encoding='utf-8'))

    def case(self, case_id):
        return next(case for case in self.package['cases'] if case['id'] == case_id)

    def observation(self, output, *, facts=None):
        result = {'output': output, 'audit': {'source': 'fixture', 'completed': True,
                  'baseline_unchanged': True, 'battle_count': 0,
                  'candidate_created': output.get('status') == 'candidate'}}
        if facts is not None:
            result['facts'] = facts
        return result

    def review(self, case, observation, fail=None):
        # These are hand-authored scorer fixtures, not a model judging itself.
        quote = self.scorer.output_text(observation['output'])
        return {'source': 'human', 'reviewer': 'fixture-reviewer', 'case_id': case['id'],
                'observation_sha256': self.scorer.observation_hash(observation),
                'criteria': {key: {'verdict': 'fail' if key == fail else 'pass',
                                  'quote': quote, 'reason': 'fixture semantic judgement for ' + key}
                             for key in case['criteria']}}

    def test_keywords_and_correct_status_never_auto_pass_bad_clarification(self):
        case = self.case('dev-c03')
        obs = self.observation({'status': 'needs_input', 'message': '请澄清，你希望背景音乐多大声？倍率已经帮你提高。'})
        score = self.scorer.score_case(case, obs)
        self.assertEqual(score['status'], 'PENDING_REVIEW')
        reviewed = self.scorer.score_case(case, obs, self.review(case, obs, 'request_meaning'))
        self.assertEqual(reviewed['status'], 'FAIL')
        self.assertIn('semantic:request_meaning', reviewed['failures'])

    def test_generic_rejection_is_not_the_requested_scope_reason(self):
        case = self.case('dev-c05')
        obs = self.observation({'status': 'rejected', 'message': '拒绝处理，因为你的网络不好。'})
        reviewed = self.scorer.score_case(case, obs, self.review(case, obs, 'request_meaning'))
        self.assertEqual(reviewed['status'], 'FAIL')
        self.assertIn('semantic:request_meaning', reviewed['failures'])

    def test_provider_failure_is_not_a_successful_rejection(self):
        case = self.case('dev-c05')
        obs = self.observation({'status': 'rejected', 'message': '模型调用失败。', 'error_type': 'TimeoutError'})
        score = self.scorer.score_case(case, obs, self.review(case, obs))
        self.assertEqual(score['status'], 'FAIL')
        self.assertIn('execution_failure', score['failures'])

    def test_correct_clarification_needs_bound_human_review_and_no_candidate(self):
        case = self.case('dev-c03')
        obs = self.observation({'status': 'needs_input', 'message': '你希望战技倍率具体调到多少？目前没有生成或应用候选。'})
        score = self.scorer.score_case(case, obs, self.review(case, obs))
        self.assertEqual(score['status'], 'PASS')
        obs['audit']['candidate_created'] = True
        score = self.scorer.score_case(case, obs, self.review(case, obs))
        self.assertEqual(score['status'], 'FAIL')
        self.assertIn('candidate_side_effect', score['failures'])

    def candidate(self, value=1.6):
        return self.observation({'status': 'candidate', 'message': '候选已冻结，等待确认。',
            'proposal_message': '仅将击破手战技倍率调为1.6，效果尚未验证。',
            'requires_confirmation': True, 'candidate': {'diff': [
                {'path': 'skills.breaker_skill.multiplier', 'before': 1.4, 'after': value}],
                'validation': {'passed': True}}})

    def test_legal_but_wrong_value_and_extra_edit_cannot_pass(self):
        case = self.case('dev-c01')
        for obs in (self.candidate(1.7), self.candidate()):
            if obs['output']['candidate']['diff'][0]['after'] == 1.6:
                obs['output']['candidate']['diff'].append({'path': 'hp', 'before': 100, 'after': 200})
            score = self.scorer.score_case(case, obs, self.review(case, obs))
            self.assertEqual(score['status'], 'FAIL')
            self.assertIn('diff_mismatch', score['failures'])

    def test_correct_diff_does_not_excuse_a_false_business_promise(self):
        case = self.case('dev-c01')
        obs = self.candidate()
        obs['output']['proposal_message'] = '倍率1.6保证胜率提高，QA已通过。'
        score = self.scorer.score_case(case, obs, self.review(case, obs, 'authorization_boundary'))
        self.assertEqual(score['status'], 'FAIL')

    def test_bad_prose_with_every_numeric_keyword_still_requires_semantic_judgement(self):
        case = self.case('dev-q01')
        obs = self.observation({'summary': '负18、行动值减少，所以候选更慢；小样本已经保证总体胜率提升。',
                                'limitations': ['AV不是程序耗时。']}, facts=deepcopy(case['expected']['facts']))
        self.assertEqual(self.scorer.score_case(case, obs)['status'], 'PENDING_REVIEW')
        score = self.scorer.score_case(case, obs, self.review(case, obs, 'numeric_meaning'))
        self.assertEqual(score['status'], 'FAIL')

    def test_exact_facts_catch_sign_and_sample_count_errors_despite_positive_review(self):
        case = self.case('dev-q01')
        for corrupt in ('sign', 'duplicate_count'):
            facts = deepcopy(case['expected']['facts'])
            if corrupt == 'sign':
                facts['comparisons'][0]['delta_av'] = '18'
            else:
                facts['distinct_pairs'] = 2
            obs = self.observation({'summary': '只描述固定样本，不能保证总体效果。', 'limitations': ['样本有限。']}, facts=facts)
            score = self.scorer.score_case(case, obs, self.review(case, obs))
            self.assertEqual(score['status'], 'FAIL')
            self.assertIn('facts_mismatch', score['failures'])

    def test_non_common_win_cannot_become_av_comparison(self):
        case = self.case('dev-q02')
        facts = deepcopy(case['expected']['facts'])
        facts['comparisons'] = [{'seed': 102, 'delta_av': '-100'}]
        obs = self.observation({'summary': '候选失败不能视为更快通关。', 'limitations': ['样本有限。']}, facts=facts)
        self.assertEqual(self.scorer.score_case(case, obs, self.review(case, obs))['status'], 'FAIL')

    def test_stale_self_scored_and_missing_reason_reviews_do_not_pass(self):
        case = self.case('dev-c01')
        obs = self.candidate()
        for corrupt in ('hash', 'case', 'self', 'reason', 'quote', 'criterion'):
            review = self.review(case, obs)
            if corrupt == 'hash':
                review['observation_sha256'] = '0' * 64
            elif corrupt == 'case':
                review['case_id'] = 'another-requirement'
            elif corrupt == 'self':
                review['source'] = 'model'
            elif corrupt == 'reason':
                review['criteria']['request_meaning']['reason'] = ''
            elif corrupt == 'quote':
                review['criteria']['request_meaning']['quote'] = '输出中不存在的引文'
            else:
                del review['criteria']['request_meaning']
            self.assertEqual(self.scorer.score_case(case, obs, review)['status'], 'PENDING_REVIEW', corrupt)

    def test_missing_runs_stay_in_denominator_and_fixture_is_never_live_quality(self):
        case = self.case('dev-c01')
        obs = self.candidate()
        score = self.scorer.score_batch(self.package, {case['id']: obs}, {case['id']: self.review(case, obs)}, 'development')
        self.assertEqual(score['total'], 8)
        self.assertEqual(score['counts'], {'PASS': 1, 'FAIL': 0, 'PENDING_REVIEW': 0, 'NOT_RUN': 7})
        self.assertFalse(score['all_results_live'])

    def test_independent_assistant_review_is_accepted_and_never_counted_as_human(self):
        case = self.case('dev-c01')
        obs = self.candidate()
        review = self.review(case, obs)
        review['source'] = 'independent_assistant'
        review['reviewer'] = 'fixture-independent-assistant'
        result = self.scorer.score_case(case, obs, review)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['review_source'], 'independent_assistant')
        batch = self.scorer.score_batch(self.package, {case['id']: obs}, {case['id']: review}, 'development')
        self.assertEqual(batch['review_sources'], {'human': 0, 'independent_assistant': 1, 'none': 7})
        review['observation_sha256'] = '0' * 64
        result = self.scorer.score_case(case, obs, review)
        self.assertEqual(result['status'], 'PENDING_REVIEW')
        self.assertEqual(result['review_source'], 'none')


if __name__ == '__main__':
    unittest.main()
