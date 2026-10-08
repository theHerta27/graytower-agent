"""Start the local product demo with models disabled and existing evidence intact."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from agent_workbench.workbench import create_app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,default=ROOT/'local-data/v1-product/data')
    parser.add_argument('--port',type=int,default=18784);args=parser.parse_args()
    original=ROOT/'local-data/python-coding-d01-v1'
    app=create_app(args.data,code_demo_root=original if (original/'closed.json').exists() else None)
    import uvicorn
    print('任务中心：http://127.0.0.1:'+str(args.port)+'/tasks',flush=True)
    print('模型调用关闭；查看证据、重新检查和本地规则试玩不会调用模型。',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)
