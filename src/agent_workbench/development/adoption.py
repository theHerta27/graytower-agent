"""Human-only adoption and restore. Never exposed as an Agent tool."""
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import uuid
from .workspace import clean_name,editable,encoded,git
from .checks import CheckJobs


def file_hash(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


class Adoption:
    def __init__(self,workspace,*,jobs=None):
        self.workspace=workspace;self.project=Path(workspace.metadata['project']).resolve()
        self.jobs=jobs or CheckJobs(workspace.control/'checks')
        self.database=workspace.control/'adoptions.sqlite'
        with closing(self.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS changes(id TEXT PRIMARY KEY,tree_hash TEXT NOT NULL,plan TEXT NOT NULL,state TEXT NOT NULL)')

    def connect(self):
        db=sqlite3.connect(self.database,timeout=20);db.row_factory=sqlite3.Row;return db

    def _path(self,name):
        clean_name(name)
        if not editable(name):raise ValueError('只允许采用支持范围内的源码或配置。')
        path=self.project/name
        for part in (path,*path.parents):
            if not part.exists() and not part.is_symlink():continue
            info=part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('采用目标包含链接，请先改用普通项目目录。')
        if path.exists() and (not path.is_file() or path.stat().st_nlink!=1):
            raise ValueError('采用目标必须是普通文件。')
        return path

    def _raw(self,name):
        path=self._path(name);return path.read_bytes() if path.exists() else None

    def _head(self):
        if git(self.project,'rev-parse','HEAD').decode().strip()!=self.workspace.metadata['baseline_commit']:
            raise ValueError('开发项目版本已经变化，请基于最新提交创建新任务。')

    @staticmethod
    def _public(row):
        if row is None:return None
        return {'operation_id':row['id'],'tree_hash':row['tree_hash'],'state':row['state'],
                'changed_files':[x['path'] for x in json.loads(row['plan'])],
                'note':'修改已写入开发项目，尚未自动Git提交。' if row['state']=='applied' else
                       '已恢复采用前的文件。' if row['state']=='restored' else '操作中断；请继续原操作完成对账。'}

    def status(self):
        with closing(self.connect()) as db:
            row=db.execute('SELECT * FROM changes ORDER BY rowid DESC LIMIT 1').fetchone()
        value=self._public(row)
        if value:
            value['matches_current_candidate']=value['tree_hash']==self.workspace.inspect()['tree_hash']
            if value['state']=='prepared':value['note']='采用中断：原项目可能已部分写入，请继续采用或恢复。'
            elif value['state']=='restoring':value['note']='恢复中断：原项目可能仍有部分修改，请继续恢复。'
            elif value['state']=='applied' and not value['matches_current_candidate']:
                value['note']='之前版本已采用，当前候选另有修改；请先恢复，再检查并采用新候选。'
        return value

    def _advance(self,db,row,direction,after_write):
        plan=json.loads(row['plan'])
        # Check the entire set before touching any file. No later user edit is overwritten.
        for entry in plan:
            if file_hash(self._raw(entry['path'])) not in (entry['before_hash'],entry['after_hash']):
                raise ValueError('文件已有后续修改，已停止以免覆盖：'+entry['path'])
        for entry in plan:
            desired=entry[direction+'_hash']
            if file_hash(self._raw(entry['path']))==desired:continue
            target=self._path(entry['path']);content=entry[direction]
            if content is None:target.unlink()
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                fd,temp=tempfile.mkstemp(prefix='.graytower-',dir=target.parent)
                try:
                    with os.fdopen(fd,'wb') as stream:
                        stream.write(base64.b64decode(content));stream.flush();os.fsync(stream.fileno())
                    os.replace(temp,target)
                finally:
                    if os.path.exists(temp):os.unlink(temp)
            if after_write:after_write()
        state='applied' if direction=='after' else 'restored'
        db.execute('UPDATE changes SET state=? WHERE id=?',(state,row['id']))
        return self._public({**dict(row),'state':state})

    def apply(self,expected_tree_hash,*,_after_write=None):
        view=self.workspace.inspect()
        if view['tree_hash']!=expected_tree_hash:raise ValueError('候选已经变化，请重新查看差异后采用。')
        if not view['changed_files']:raise ValueError('当前没有需要采用的修改。')
        checks=[j for j in self.jobs.list(self.workspace) if j['matches_current_candidate']
                and j['matches_current_definition'] and j['status']=='completed' and j['check_set']!='diagnostic']
        if not any(j['result']['verdict']=='PASS' for j in checks) or any(j['result']['verdict']=='FAIL' for j in checks):
            raise ValueError('请先运行检查；当前必须有可信检查通过，且没有当前版本的失败检查。')
        self._head()
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM changes WHERE state!='restored' ORDER BY rowid DESC LIMIT 1").fetchone()
            if row:
                if row['tree_hash']!=expected_tree_hash or row['state']=='restoring':
                    raise ValueError('请先完成或恢复已有采用操作。')
                if row['state']=='applied':
                    if any(file_hash(self._raw(e['path']))!=e['after_hash'] for e in json.loads(row['plan'])):
                        raise ValueError('开发项目已有后续修改，不重复覆盖。')
                    return self._public(row)
            else:
                if git(self.project,'status','--porcelain','--untracked-files=no').strip():
                    raise ValueError('开发项目有未提交修改，请先提交或自行处理，再采用候选。')
                tree=self.workspace.snapshot()['files'];plan=[]
                for name in view['changed_files']:
                    before=self._raw(name)
                    baseline=self.workspace.baseline['files'].get(name)
                    expected=baseline['sha256'] if baseline else None
                    if file_hash(before)!=expected:raise ValueError('原文件与基线不一致，拒绝覆盖：'+name)
                    after=tree.get(name)
                    plan.append({'path':name,'before':base64.b64encode(before).decode() if before is not None else None,
                                 'before_hash':file_hash(before),'after':after['content'] if after else None,
                                 'after_hash':after['sha256'] if after else None})
                operation=uuid.uuid4().hex
                db.execute('INSERT INTO changes VALUES (?,?,?,?)',(operation,expected_tree_hash,encoded(plan).decode(),'prepared'))
                db.commit();db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT * FROM changes WHERE id=?',(operation,)).fetchone()
            return self._advance(db,row,'after',_after_write)

    def restore(self,operation_id,*,_after_write=None):
        self._head()
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM changes WHERE id=?',(operation_id,)).fetchone()
            if row is None:raise ValueError('没有找到该采用记录。')
            if row['state']=='restored':return self._public(row)
            db.execute("UPDATE changes SET state='restoring' WHERE id=?",(operation_id,))
            db.commit();db.execute('BEGIN IMMEDIATE')
            return self._advance(db,row,'before',_after_write)
