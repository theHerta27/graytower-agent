"""Trusted game host port for planner playtesting; only frozen JSON is selected."""
import json
import os
from pathlib import Path
import subprocess
import sys

GAME_ROOT=Path('D:/Desktop/graytower-game')
GAME_PYTHON=GAME_ROOT/'.venv/Scripts/python.exe'


class LocalTestGame:
    def __init__(self,releases,*,game_root=GAME_ROOT):
        self.releases,self.game_root=releases,Path(game_root)
    def _call(self,operation,args):
        content=self.releases.config_content()
        env={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','TEMP','TMP')}
        process=subprocess.run([str(GAME_PYTHON),'-I','-B','-X','utf8',str(Path(__file__).with_name('local_game_worker.py'))],
            input=json.dumps({'game_root':str(self.game_root),'data':str(self.releases.root/'local-test-save'),
                'content':str(content) if content else None,'operation':operation,'args':args},ensure_ascii=False),
            text=True,encoding='utf-8',capture_output=True,env=env,timeout=30)
        if process.returncode:raise ValueError('本地规则试玩暂不可用；请核对游戏依赖和配置版本。')
        return json.loads(process.stdout)
    def start(self,session_id):return self._call('start',{'session_id':session_id})
    def observe(self,session_id):return self._call('observe',{'session_id':session_id})
    def command(self,session_id,command):return self._call('command',{'session_id':session_id,'command':command})


