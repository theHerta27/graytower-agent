"""Import closed real Coding evidence into a new, model-disabled UI data root.

Only immutable artifacts and the consistent JobStore are copied. No historical
grant, model ledger, Runtime workspace or credential becomes execution authority.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from agent_workbench.coding.service import CodingService


def prepare(source: Path, data: Path):
    source, data = Path(source).resolve(), Path(data).resolve()
    if data.exists():
        raise FileExistsError('UI workspace already exists; refusing to replace its state')
    if source == data or source in data.parents:
        raise ValueError('UI copy must be outside the sealed source directory')
    closed_path = source / 'closed.json'
    if not closed_path.is_file() or json.loads(closed_path.read_text(encoding='utf-8')).get('unused_calls_closed') is not True:
        raise ValueError('only a completed, closed source batch can be imported')
    summary = json.loads((source / 'coding-summary.json').read_text(encoding='utf-8'))
    if not summary['runs'] or any(mode not in ('single', 'auto') for mode in summary['runs']):
        raise ValueError('invalid Coding summary')
    paths = [closed_path, source / 'coding-summary.json', source / 'data/jobs.sqlite',
             *(source / 'data/artifacts').glob('*.json'),
             *(source / ('candidate-' + mode + '.json') for mode in summary['runs'])]
    source_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    data.mkdir(parents=True)
    with closing(sqlite3.connect((source / 'data/jobs.sqlite').as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(data / 'jobs.sqlite')) as copied:
            original.backup(copied)
    shutil.copytree(source / 'data/artifacts', data / 'artifacts')
    service = CodingService(data)
    run_ids = []
    for mode, run in summary['runs'].items():
        candidate = service.repo.get(run['manifest_hash'])
        if candidate != json.loads((source / ('candidate-' + mode + '.json')).read_text(encoding='utf-8')):
            raise ValueError('source candidate summary differs from immutable artifacts')
        operation_id = 'coding-demo-' + mode
        service.import_completed(operation_id=operation_id, request=candidate['manifest']['request'],
            mode=mode, manifest_hash=run['manifest_hash'], runtime_receipt=run['runtime_receipt'],
            seconds=run['seconds'], budget=summary['budget'])
        run_ids.append(operation_id)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != expected for path, expected in source_hashes.items()):
        raise ValueError('source changed during the copy')
    provenance = {'source': str(source), 'description': 'Copied saved Coding/QA evidence, not a new Agent run',
        'run_ids': run_ids, 'manifest_hashes': [run['manifest_hash'] for run in summary['runs'].values()],
        'source_file_sha256': {path.relative_to(source).as_posix(): sha for path, sha in source_hashes.items()},
        'source_files_unchanged': True, 'model_enabled': False, 'coding_enabled': False,
        'new_model_calls': 0, 'new_battles': 0,
        'budget_scope': 'The displayed budget is one shared closed Coding grant; do not sum it across runs.'}
    (data / 'demo-provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'local-data/coding-runtime-demo-v1')
    parser.add_argument('--data', type=Path, default=ROOT / 'local-data/coding-workbench-v1')
    args = parser.parse_args()
    result = prepare(args.source, args.data)
    print(json.dumps({key: value for key, value in result.items() if key != 'source_file_sha256'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
