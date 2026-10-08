"""Import closed evidence for one usable local demo; never copy model grants."""
from contextlib import closing
import argparse
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from agent_workbench.domain._shared import Artifacts
from agent_workbench.jobs import JobStore
from agent_workbench.workbench_store import WorkbenchStore
from agent_workbench.tasks import TaskStore

def prepare(source,target):
    target.mkdir(parents=True,exist_ok=True)
    JobStore(target);WorkbenchStore(target);TaskStore(target)
    original=Artifacts(source/'artifacts');destination=Artifacts(target/'artifacts')
    for file in original.root.glob('*.json'):
        value=original.read(file.stem)
        assert destination.put(value,'imported-history')['sha256']==file.stem
    for filename,tables in [('jobs.sqlite',['confirmations','requests','jobs']),
                           ('workbench.sqlite',['operations','candidates']),('tasks.sqlite',['tasks','task_events'])]:
        with closing(sqlite3.connect((source/filename).as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(target/filename)) as new,new:
            for table in tables:
                rows=old.execute('SELECT * FROM '+table).fetchall()
                # Preserve original values/identities. Authority and call ledgers
                # stay in their closed source scope; no new model calls here.
                columns=[r[1] for r in old.execute('PRAGMA table_info('+table+')')]
                for row in rows:
                    if table=='operations' and row[columns.index('status')]!='completed':continue
                    new.execute('INSERT OR IGNORE INTO '+table+' VALUES ('+','.join('?' for _ in row)+')',row)
    print(json.dumps({'imported_from':str(source),'data':str(target),'new_model_calls':0,'new_executions':0,'grants_imported':False}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args();prepare(args.source.resolve(),args.data.resolve())
