"""Explicit local-test adoption and rollback. Never alters the running game."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from .artifact_views import frozen_candidate
from .code_tools import CodeCatalog
from .code_candidates import snapshot, git
from .code_sandbox import CodeTestJobs
from .jobs import JobStore,canonical,digest


class ReleaseService:
    def __init__(self,root,repo):
        self.root,self.repo=Path(root),repo
        self.path=self.root/'releases.sqlite'
        with closing(self.connect()) as db,db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,kind TEXT NOT NULL,metadata TEXT NOT NULL,hash TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS active(kind TEXT PRIMARY KEY,version TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,input TEXT NOT NULL,result TEXT NOT NULL,hash TEXT NOT NULL);
            ''')
            if 'history' not in {r[1] for r in db.execute('PRAGMA table_info(active)')}:
                db.execute("ALTER TABLE active ADD COLUMN history TEXT NOT NULL DEFAULT '[]'")
                # Existing V1 pointers have only their first activation. Preserve
                # that known predecessor without inventing intervening history.
                for kind,version in db.execute('SELECT kind,version FROM active').fetchall():
                    if version!='baseline':
                        metadata=db.execute('SELECT metadata FROM versions WHERE id=?',(version,)).fetchone()
                        predecessor=json.loads(metadata[0]).get('previous_release','baseline')
                        db.execute('UPDATE active SET history=? WHERE kind=?',(canonical([predecessor]),kind))

    def connect(self):return sqlite3.connect(self.path,timeout=10)

    def _prior(self,operation,value):
        if not isinstance(operation,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}',operation):
            raise ValueError('invalid release operation')
        with closing(self.connect()) as db:
            row=db.execute('SELECT input,result,hash FROM operations WHERE id=?',(operation,)).fetchone()
        if row:
            if row[0]!=canonical(value):raise ValueError('release operation input changed')
            result=json.loads(row[1])
            if digest(result)!=row[2]:raise ValueError('release receipt damaged')
            return result

    def version(self,version):
        with closing(self.connect()) as db:
            row=db.execute('SELECT metadata,hash FROM versions WHERE id=?',(version,)).fetchone()
        if row is None:raise KeyError(version)
        result=json.loads(row[0])
        if digest(result)!=row[1]:raise ValueError('release identity damaged')
        return result

    def status(self):
        with closing(self.connect()) as db:
            active=dict(db.execute('SELECT kind,version FROM active'))
        return {kind:{'active_release':active.get(kind,'baseline'),
                       'version':self.version(active[kind]) if active.get(kind,'baseline')!='baseline' else None}
                for kind in ('config','code')}

    @staticmethod
    def _write(file,value):
        raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        file.parent.mkdir(parents=True,exist_ok=True)
        if file.exists():
            if file.read_bytes()!=raw:raise ValueError('local version bytes changed')
        else:
            with file.open('xb') as stream:stream.write(raw)

    def config_content(self):
        version=self.status()['config']['active_release']
        if version=='baseline':return None
        metadata=self.version(version)
        candidate=frozen_candidate(self.repo,metadata['candidate_id'])
        folder=self.root/'releases'/version/'content'
        for field,name in [('candidate','baseline.json'),('scenario','scenario.json')]:
            ref=candidate['manifest'][field]
            value=self.repo.artifacts.read_ref(ref,ref['schema'])
            if json.loads((folder/name).read_text(encoding='utf-8'))!=value:
                raise ValueError('adopted configuration changed')
        return folder

    def adopt(self,operation,candidate_id,request_id,*,accept_sample=False):
        value={'action':'adopt','candidate_id':candidate_id,'request_id':request_id,'accept_sample':accept_sample}
        prior=self._prior(operation,value)
        if prior:return prior
        jobs=JobStore(self.root)
        request=jobs.get(request_id);report=request['report']
        receipts=jobs.receipts(request_id)
        if (request['manifest_hash']!=candidate_id or report is None or not receipts
                or report.get('jobs')!=receipts or report.get('verdict')=='FAIL'):
            raise ValueError('matching completed verification required')
        catalog=CodeCatalog(self.root)
        kind='code' if candidate_id in catalog.ids() else 'config'
        if kind=='config' and (report.get('structural_verdict')!='PASS' or not accept_sample):
            raise ValueError('explicit acknowledgement of limited sample evidence required')
        if kind=='code' and report.get('verdict')!='PASS':
            raise ValueError('complete passing code checks required')
        version='local_'+digest({'candidate':candidate_id,'kind':kind})[:20]
        metadata={'release_id':version,'kind':kind,'candidate_id':candidate_id,'verification_request':request_id,
                  'scope':'本地测试版本；不修改玩家正式存档或正在进行的战斗。'}
        if kind=='config':
            candidate=frozen_candidate(self.repo,candidate_id)
            for field,name in [('candidate','baseline.json'),('scenario','scenario.json')]:
                ref=candidate['manifest'][field]
                self._write(self.root/'releases'/version/'content'/name,self.repo.artifacts.read_ref(ref,ref['schema']))
            metadata['limited_sample_accepted']=True
        else:
            workspace=catalog.workspace(candidate_id)
            folder=self.root/'releases'/version/'source'
            if folder.exists():
                if snapshot(folder)!=catalog.artifacts.read_ref(workspace.inspect(candidate_id)['manifest']['candidate_tree'],'code-tree-v1'):
                    raise ValueError('local code version changed')
            else:workspace.restore(folder,candidate_id)
            check=CodeTestJobs(self.root).run(workspace,candidate_id,'candidate',run_id='adopt_'+operation)
            if check['verdict']!='PASS':raise ValueError('local version recheck did not pass')
            if not git(folder,'status','--porcelain'):
                commit=git(folder,'rev-parse','HEAD')
            else:
                git(folder,'add','game-core/combat_core','configs/combat/v2')
                git(folder,'-c','user.name=graytower-local','-c','user.email=local@localhost','-c','commit.gpgsign=false',
                    'commit','-m','Adopt tested local Python candidate '+candidate_id[:12])
                commit=git(folder,'rev-parse','HEAD')
            metadata.update(code_commit=commit,test_receipt=check)
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute('SELECT version,history FROM active WHERE kind=?',(kind,)).fetchone()
            previous=active[0] if active else 'baseline'
            history=json.loads(active[1]) if active else []
            history.append(previous)
            old=db.execute('SELECT metadata FROM versions WHERE id=?',(version,)).fetchone()
            if old:
                metadata=json.loads(old[0])
            else:
                metadata['previous_release']=previous
                db.execute('INSERT INTO versions VALUES (?,?,?,?)',(version,kind,canonical(metadata),digest(metadata)))
            result={'operation_id':operation,'kind':kind,'active_release':version,'previous_release':previous,'version':metadata}
            db.execute('INSERT OR REPLACE INTO active VALUES (?,?,?)',(kind,version,canonical(history)))
            db.execute('INSERT INTO operations VALUES (?,?,?,?)',(operation,canonical(value),canonical(result),digest(result)))
        return result

    def rollback(self,operation,kind):
        value={'action':'rollback','kind':kind}
        prior=self._prior(operation,value)
        if prior:return prior
        if kind not in ('config','code'):raise ValueError('invalid release kind')
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT version,history FROM active WHERE kind=?',(kind,)).fetchone()
            current=row[0] if row else 'baseline'
            history=json.loads(row[1]) if row else []
            target=history.pop() if history else 'baseline'
            if target!='baseline':self.version(target)
            result={'operation_id':operation,'kind':kind,'active_release':target,'previous_release':current,
                    'note':'只切回本地测试版本；旧存档、报告和数据库记录保留。'}
            db.execute('INSERT OR REPLACE INTO active VALUES (?,?,?)',(kind,target,canonical(history)))
            db.execute('INSERT INTO operations VALUES (?,?,?,?)',(operation,canonical(value),canonical(result),digest(result)))
        return result
