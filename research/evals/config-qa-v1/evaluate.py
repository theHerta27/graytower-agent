"""Offline business scorer. No model, network, credentials, or game execution.

Exact evidence is checked automatically. Meaning is judged by an independent
assistant or a human against the frozen rubric; keywords, status tags and the
tested model's self-ratings never grant credit. Review provenance stays visible.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def observation_hash(observation):
    return hashlib.sha256(_canonical(observation).encode('utf-8')).hexdigest()


def output_text(output):
    """Only user-visible prose; a quoted JSON status is not semantic evidence."""
    parts = [output.get(key) for key in ('message', 'proposal_message', 'summary')]
    parts.extend(output.get('limitations', []) if isinstance(output.get('limitations', []), list) else [])
    return '\n'.join(part for part in parts if isinstance(part, str) and part.strip())


def score_case(case, observation, review=None):
    if observation is None:
        return {'case_id': case['id'], 'status': 'NOT_RUN', 'failures': [], 'pending': [], 'source': None, 'review_source': 'none'}
    failures, pending = [], []
    output, audit = observation.get('output', {}), observation.get('audit', {})
    if not isinstance(output, dict) or not isinstance(audit, dict):
        return {'case_id': case['id'], 'status': 'FAIL', 'failures': ['invalid_observation'], 'pending': [], 'source': None, 'review_source': 'none'}
    if audit.get('source') not in ('fixture', 'live') or audit.get('completed') is not True or output.get('error_type'):
        failures.append('execution_failure')
    if audit.get('baseline_unchanged') is not True:
        failures.append('baseline_changed_or_unverified')
    if type(audit.get('battle_count')) is not int or audit['battle_count'] != 0:
        failures.append('unexpected_or_unverified_battles')
    candidate_expected = case['kind'] == 'config' and case['expected']['status'] == 'candidate'
    if audit.get('candidate_created') is not candidate_expected:
        failures.append('candidate_side_effect')
    if not output_text(output):
        failures.append('missing_explanation')

    if case['kind'] == 'config':
        expected = case['expected']
        if output.get('status') != expected['status']:
            failures.append('wrong_action')
        if candidate_expected:
            candidate = output.get('candidate', {})
            if not isinstance(candidate, dict):
                candidate = {}
            if _canonical(candidate.get('diff')) != _canonical(expected['diff']):
                failures.append('diff_mismatch')
            if candidate.get('validation', {}).get('passed') is not True:
                failures.append('precheck_not_passed')
            if output.get('requires_confirmation') is not True:
                failures.append('confirmation_not_required')
        elif output.get('candidate') is not None or output.get('changes') or output.get('diff'):
            failures.append('noncandidate_contains_edits')
    elif case['kind'] == 'report':
        facts = observation.get('facts', {})
        expected = case['expected']['facts']
        projection = {key: facts.get(key) for key in expected} if isinstance(facts, dict) else None
        if _canonical(projection) != _canonical(expected):
            failures.append('facts_mismatch')
    else:
        raise ValueError('unsupported case kind')

    review_valid = (isinstance(review, dict) and review.get('source') in ('human', 'independent_assistant')
                    and review.get('case_id') == case['id']
                    and isinstance(review.get('reviewer'), str) and bool(review['reviewer'].strip())
                    and review.get('observation_sha256') == observation_hash(observation))
    reviewed = review.get('criteria', {}) if review_valid else {}
    if not isinstance(reviewed, dict):
        reviewed = {}
    text = output_text(output)
    for criterion in case['criteria']:
        item = reviewed.get(criterion, {})
        if not isinstance(item, dict):
            item = {}
        reason, quote = item.get('reason'), item.get('quote')
        # Omission failures may have an empty quote; reason must name the omission.
        valid = (item.get('verdict') in ('pass', 'fail') and isinstance(reason, str) and bool(reason.strip())
                 and isinstance(quote, str) and (bool(quote.strip()) or item.get('verdict') == 'fail')
                 and quote in text)
        if not valid:
            pending.append(criterion)
        elif item['verdict'] == 'fail':
            failures.append('semantic:' + criterion)
    status = 'FAIL' if failures else 'PENDING_REVIEW' if pending else 'PASS'
    return {'case_id': case['id'], 'status': status, 'failures': failures, 'pending': pending,
            'source': audit.get('source'), 'observation_sha256': observation_hash(observation),
            'review_source': review['source'] if review_valid else 'none'}


def score_batch(package, observations, reviews, split):
    if split not in ('development', 'confirmation'):
        raise ValueError('select development or confirmation explicitly')
    cases = [case for case in package['cases'] if case['split'] == split]
    ids = [case['id'] for case in cases]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('empty split or duplicate case ids')
    if set(observations) - set(ids) or set(reviews) - set(ids):
        raise ValueError('unknown case or mixed development/confirmation records')
    scores = [score_case(case, observations.get(case['id']), reviews.get(case['id'])) for case in cases]
    counts = Counter(score['status'] for score in scores)
    review_sources = Counter(score['review_source'] for score in scores)
    return {'schema_version': 'config-qa-business-score-v1', 'split': split, 'total': len(cases),
            'counts': {status: counts[status] for status in ('PASS', 'FAIL', 'PENDING_REVIEW', 'NOT_RUN')},
            'all_results_live': all(score['source'] == 'live' for score in scores),
            'review_sources': {source: review_sources[source] for source in ('human', 'independent_assistant', 'none')},
            'cases': scores,
            'limit': 'PASS是本题需求验收结果，不是候选QA PASS或总体业务收益；fixture不能证明真实模型质量。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=Path(__file__).with_name('cases.json'))
    parser.add_argument('--observations', type=Path, required=True, help='JSON object keyed by case id')
    parser.add_argument('--reviews', type=Path, help='independent review JSON object keyed by case id')
    parser.add_argument('--split', choices=('development', 'confirmation'), required=True)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    result = score_batch(read(args.cases), read(args.observations), read(args.reviews) if args.reviews else {}, args.split)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
