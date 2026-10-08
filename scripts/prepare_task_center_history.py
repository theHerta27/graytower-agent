"""Read-only backup of prior business evidence; never copy a spending grant."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    source, target = args.source.resolve(strict=True), args.data.resolve()
    if target.exists():
        raise RuntimeError('refusing to replace an existing demo')
    files = list((source / 'artifacts').glob('*.json'))
    databases = [source / name for name in ('jobs.sqlite', 'workbench.sqlite') if (source / name).is_file()]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files + databases}
    target.mkdir(parents=True)
    for db in databases:
        with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target / db.name) as dst:
            src.backup(dst)
    shutil.copytree(source / 'artifacts', target / 'artifacts')
    if before != {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files + databases}:
        raise RuntimeError('source changed during backup')
    (target / 'history-provenance.json').write_text(json.dumps({
        'source': str(source), 'source_files': before, 'mode': 'historical_view',
        'new_model_calls': 0, 'new_battles': 0, 'grants_copied': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('历史演示数据已准备；未调用模型，未重新执行战斗。')


if __name__ == '__main__':
    main()
