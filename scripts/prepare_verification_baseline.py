"""Restore the frozen numeric baseline from sibling game Git history; no model calls."""
import argparse
import io
from pathlib import Path
import subprocess
import tarfile

REVISION = 'fdb9e8387af696482bf2b57d1543484f8b08495c'


def prepare(game):
    game = Path(game).resolve(strict=True)
    target = game / 'local-data/verification-baseline'
    marker = target / '.baseline-revision'
    if target.exists():
        if not marker.is_file() or marker.read_text().strip() != REVISION:
            raise ValueError('Existing baseline is not this frozen revision; no files overwritten')
        return target
    raw = subprocess.check_output(['git', 'archive', '--format=tar', REVISION], cwd=game)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        for member in members:
            path = (target / member.name).resolve()
            if not path.is_relative_to(target.resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe archive member')
        target.mkdir(parents=True)
        archive.extractall(target, members=members)
    marker.write_text(REVISION + '\n', encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='还原固定数值验证基线，不修改当前游戏源码')
    parser.add_argument('--game', type=Path, default=Path(__file__).resolve().parents[2] / 'graytower-game')
    args = parser.parse_args()
    print(prepare(args.game))
