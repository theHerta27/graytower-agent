"""One local camp/Unity demo; no model keys or paid calls."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT.parent / 'graytower-game'
sys.path[:0] = [str(ROOT / 'src'), str(GAME / 'game-core'), str(GAME / 'scripts')]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='灰塔营地：中文离线剧情与真实战斗演示')
    parser.add_argument('--data', type=Path, default=ROOT / 'local-data/story-demo-v1')
    args = parser.parse_args()
    from play_live import ensure_port_free, LaunchError
    try:
        ensure_port_free()
    except LaunchError as exc:
        print(str(exc)+'\n若营地已启动，请直接打开 http://127.0.0.1:8780/camp 。', flush=True)
        raise SystemExit(1)
    from agent_workbench.npc.demo import create_demo_app
    import uvicorn
    print('打开 http://127.0.0.1:8780/camp 开始。NPC 为离线台词演示，战斗与支援真实执行。', flush=True)
    print('结束时关闭游戏窗口，再在此按 Ctrl+C。', flush=True)
    uvicorn.run(create_demo_app(args.data, GAME), host='127.0.0.1', port=8780, access_log=False)
