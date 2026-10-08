"""Program-owned worker: loads trusted game code, never code candidates."""
import json
from pathlib import Path
import sys
value=json.load(sys.stdin)
sys.path.insert(0,str(Path(value['game_root'])/'game-core'))
from combat_core.host import GameHost
host=GameHost(value['data'],content=value['content'])
operation,args=value['operation'],value['args']
if operation=='start':result=host.create({'session_id':args['session_id']})
elif operation=='observe':result=host.observe(args['session_id'])
elif operation=='command':result=host.command(args['session_id'],args['command'])
else:raise ValueError('unsupported playtest operation')
saved=host.transcript(args['session_id'])['initial_snapshot']
result['play_configuration']={'breaker_multiplier':saved['bundle']['skills']['breaker_skill']['multiplier']}
print(json.dumps(result,ensure_ascii=False))
