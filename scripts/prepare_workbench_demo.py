"""Copy real saved evidence into an isolated UI workspace; zero model/battle calls.

Historical ledgers are closed. They are never copied as a fresh spending grant.
The web server starts with model access disabled unless separately configured.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agent_workbench.domain import CandidateRepository
from agent_workbench.jobs import JobStore, digest

DATA = ROOT / 'local-data/workbench-v1'
SOURCE = ROOT / 'local-data/config-development-v1'


def main():
    if DATA.exists():
        raise RuntimeError('UI workspace already exists; refusing to replace its state')
    DATA.mkdir(parents=True)
    original = SOURCE / 'dev-c01'
    source_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in [original / 'jobs.sqlite', *(original / 'artifacts').glob('*.json')]}
    # SQLite backup is consistent and opens the sealed source explicitly read-only.
    with sqlite3.connect((original / 'jobs.sqlite').as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(DATA / 'jobs.sqlite') as dst:
            src.backup(dst)
    shutil.copytree(original / 'artifacts', DATA / 'artifacts')
    # A second real Config draft is available for explicit UI inspection/confirmation.
    # Copy only content addressed inputs, never credentials, model logs, or a grant.
    second = SOURCE / 'dev-c02'
    for path in (second / 'artifacts').glob('*.json'):
        target = DATA / 'artifacts' / path.name
        if target.exists():
            if path.read_bytes() != target.read_bytes():
                raise RuntimeError('content-addressed artifact collision')
        else:
            shutil.copyfile(path, target)
    observations = json.loads((SOURCE / 'observations.json').read_text(encoding='utf-8'))
    repo = CandidateRepository(DATA)
    for case_id in ('dev-c01', 'dev-c02'):
        candidate = observations[case_id]['output']['candidate']
        assert repo.get(candidate['manifest_hash']) == candidate
    report = JobStore(DATA).get('dev-c01-qa')['report']
    original_report = json.loads((SOURCE / 'qa-delivery.json').read_text(encoding='utf-8'))['report']
    assert report == original_report
    for path, expected in source_hashes.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    provenance = {'source': 'Copied real 2026-10-05 Config/QA evidence, not a fresh Agent run',
                  'original_root': str(SOURCE), 'model_enabled': False,
                  'historical_model_budget': 'Closed; old ledgers never grant new calls here',
                  'request_id': 'dev-c01-qa', 'report_hash': digest(report),
                  'inspection_candidate': observations['dev-c02']['output']['candidate']['manifest_hash'],
                  'candidate_hashes': [observations[c]['output']['candidate']['manifest_hash']
                                       for c in ('dev-c01', 'dev-c02')],
                  'source_files_unchanged': True, 'new_model_calls': 0, 'new_battles': 0}
    (DATA / 'demo-provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(provenance, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
