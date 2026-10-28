"""Human-reviewed Git integration; model tools cannot call this service."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import uuid
from .workspace import ProjectWorkspace, digest, encoded, editable, item, MAX_TREE
from .git_support import (git, run, oid, common_dir, repository_lock, read_tree,
    create_worktree, configure_sparse, commit_tree, atomic_json)
from .checks import CheckJobs


class FrozenWorktree(ProjectWorkspace):
    def __init__(self, record):
        self.record = record
        self.path = Path(record['worktree_path'])
        self.control = self.path.parent
        self.metadata = {'mode':'git_worktree'}
        self.baseline = read_tree(self.path,record['merge_commit'])

    def snapshot(self):
        record = self.record
        if ((self.path/'.git').is_symlink() or (self.path/'.git').read_text(encoding='utf-8')!=record['git_pointer']
            or str(Path(git(self.path,'rev-parse','--absolute-git-dir').decode().strip()).resolve())!=record['git_dir']
            or oid(self.path)!=record['merge_commit']):
            raise ValueError('交付工作树身份或提交已经改变。')
        if git(self.path,'write-tree').decode().strip()!=record['git_tree']:
            raise ValueError('交付暂存区已经改变。')
        tree = super().snapshot()
        if digest(tree)!=record['tree_hash']:
            raise ValueError('交付文件已经改变，请重新准备。')
        return tree


class GitDelivery:
    def __init__(self, workspace, *, launcher=None):
        if workspace.metadata.get('mode')!='git_worktree':
            raise ValueError('旧任务使用原来的采用/恢复方式。')
        self.workspace = workspace
        self.project = Path(workspace.metadata['project'])
        self.root = workspace.control/'deliveries'
        self.root.mkdir(exist_ok=True)
        self.database = self.root/'deliveries.sqlite'
        self.launcher = launcher
        self._jobs = {}
        with closing(self.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS preparations(id TEXT PRIMARY KEY,data TEXT NOT NULL,state TEXT NOT NULL,approved_hash TEXT)')

    def connect(self):
        db = sqlite3.connect(self.database,timeout=20); db.row_factory=sqlite3.Row
        return db

    def _save(self, record):
        with closing(self.connect()) as db,db:
            db.execute('INSERT INTO preparations VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,state=excluded.state,approved_hash=excluded.approved_hash',
                (record['preparation_id'],encoded(record).decode(),record['state'],record.get('approved_hash')))

    def _get(self, identity=None):
        if identity is not None and (not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity)):
            raise ValueError('准备记录编号无效。')
        with closing(self.connect()) as db:
            row = db.execute('SELECT data FROM preparations WHERE id=?',(identity,)).fetchone() if identity else db.execute('SELECT data FROM preparations ORDER BY rowid DESC LIMIT 1').fetchone()
        if row is None:
            if identity: raise ValueError('找不到交付准备记录。')
            return None
        return json.loads(row['data'])

    def jobs(self, identity):
        self._get(identity)
        if identity not in self._jobs:
            self._jobs[identity] = CheckJobs(self.root/identity/'checks',launcher=self.launcher)
        return self._jobs[identity]

    def _target(self, expected=None):
        meta = self.workspace.metadata
        if common_dir(self.project)!=Path(meta['common_dir']): raise ValueError('原项目已变成另一个仓库。')
        if git(self.project,'symbolic-ref','--short','HEAD').decode().strip()!=meta['target_branch']:
            raise ValueError('原项目分支已切换，请重新准备。')
        head = oid(self.project)
        if expected is not None and head!=expected: raise ValueError('原项目版本已经变化，请重新准备和审阅。')
        if git(self.project,'status','--porcelain','--untracked-files=no').strip():
            raise ValueError('原项目有未提交修改，请先自行处理。')
        directory=Path(git(self.project,'rev-parse','--absolute-git-dir').decode().strip())
        for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply'):
            path=directory/name
            if path.exists(): raise ValueError('原项目有未结束的 Git 操作，请先处理。')
        return head

    def _candidate(self, record):
        self.workspace._validate()
        if (self.workspace.metadata['candidate_commit']!=record['candidate_commit']
            or digest(self.workspace.snapshot())!=record['candidate_hash']):
            raise ValueError('Agent 候选已变化，请重新准备和审阅。')

    def _current(self, record):
        self._target(record['target_commit']); self._candidate(record)

    def _active_operation(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT id FROM preparations WHERE state IN ('applying','applied') LIMIT 1").fetchone()

    def prepare(self, kind='merge', operation_id=None):
        if kind=='revert': return self._prepare_revert(operation_id)
        if kind!='merge' or operation_id is not None: raise ValueError('不支持的交付类型。')
        with self.workspace.delivery_lock(),repository_lock(self.project):
            self.workspace.ensure_idle()
            if self._active_operation(): raise ValueError('已有采用记录，请先完成或撤销该次采用。')
            view = self.workspace.inspect()
            if not view['changed_files']: raise ValueError('当前没有需要合入的修改。')
            target = self._target()
            candidate = self.workspace.freeze()
            identity = uuid.uuid4().hex
            folder = self.root/identity; folder.mkdir()
            record = {'preparation_id':identity,'kind':'merge','target_commit':target,
                'target_branch':self.workspace.metadata['target_branch'],'candidate_commit':candidate,
                'candidate_hash':view['tree_hash'],'state':'preparing','worktree_path':str(folder/'workspace')}
            self._save(record)
            result = run(self.project,'merge-tree','--write-tree','--name-only',target,candidate,allowed=(0,1))
            lines = result.stdout.decode('utf-8').splitlines()
            record['git_tree'] = lines[0]
            if result.returncode:
                record['conflicts'] = lines[1:lines.index('')] if '' in lines else lines[1:]
                self._save(record)
                tree = read_tree(self.project,target)
                record.update(create_worktree(self.project,Path(record['worktree_path']),target,tree))
                union = set(tree['files']) | set(read_tree(self.project,candidate)['files'])
                configure_sparse(record['worktree_path'],union)
                merged = run(record['worktree_path'],'merge','--no-commit','--no-ff','--no-edit',candidate,
                    sparse=True,allowed=(0,1),env={'GIT_AUTHOR_NAME':'Graytower Agent','GIT_AUTHOR_EMAIL':'graytower@localhost',
                    'GIT_COMMITTER_NAME':'Graytower Agent','GIT_COMMITTER_EMAIL':'graytower@localhost'})
                if merged.returncode!=1: raise ValueError('Git 冲突状态与准备计算不一致，请检查保留目录。')
                record['state']='conflict'; self._save(record)
                return self.status(identity)
            return self._finish_prepare(record)

    def _finish_prepare(self, record, *, existing=False):
        parents = [record['target_commit']] if record['kind']=='revert' else [record['target_commit'],record['candidate_commit']]
        commit = commit_tree(self.project,record['git_tree'],parents,
                             'Graytower: revert integration' if record['kind']=='revert' else 'Graytower: reviewed integration candidate')
        record['merge_commit']=commit
        git(self.project,'update-ref','refs/graytower/preparations/'+record['preparation_id'],commit)
        tree = read_tree(self.project,commit)
        record['tree_hash']=digest(tree)
        self._save(record)
        path = Path(record['worktree_path'])
        if existing:
            # The user resolved the staged merge; move only our detached HEAD and
            # keep the already-verified working files. No original branch moves.
            git(path,'update-ref','--no-deref','HEAD',commit,record['target_commit'])
            git(path,'reset','--mixed',commit,sparse=True)
        else:
            record.update(create_worktree(self.project,path,commit,tree))
        record['patch']=git(self.project,'diff','--no-ext-diff','--no-textconv','--binary',record['target_commit'],commit,'--').decode('utf-8')
        record['changed_files']=git(self.project,'diff','--name-only','-z',record['target_commit'],commit).decode().strip('\0').split('\0')
        record['state']='prepared'
        FrozenWorktree(record).snapshot()
        self._save(record)
        return self.status(record['preparation_id'])

    def _prepare_revert(self, operation_id):
        with self.workspace.delivery_lock(),repository_lock(self.project):
            self.workspace.ensure_idle()
            previous = self._get(operation_id)
            if previous is None or previous['kind']!='merge' or previous['state']!='applied':
                raise ValueError('请选择已经采用的合并记录。')
            self._target(previous['merge_commit'])
            view = self.workspace.inspect()
            identity = uuid.uuid4().hex
            folder = self.root/identity; folder.mkdir()
            record = {'preparation_id':identity,'kind':'revert','original_operation':operation_id,
                'target_commit':previous['merge_commit'],'target_branch':previous['target_branch'],
                'candidate_commit':self.workspace.metadata['candidate_commit'],'candidate_hash':view['tree_hash'],
                'state':'preparing','worktree_path':str(folder/'workspace'),
                'git_tree':git(self.project,'rev-parse',previous['target_commit']+'^{tree}').decode().strip()}
            self._save(record)
            return self._finish_prepare(record)

    def resolve(self, identity):
        with self.workspace.delivery_lock(),repository_lock(self.project):
            self.workspace.ensure_idle()
            record = self._get(identity)
            if record['state']!='conflict': raise ValueError('该记录没有待处理冲突。')
            self._current(record)
            path = Path(record['worktree_path'])
            if ((path/'.git').read_text(encoding='utf-8')!=record['git_pointer'] or oid(path)!=record['target_commit']
                or git(path,'rev-parse','MERGE_HEAD').decode().strip()!=record['candidate_commit']):
                raise ValueError('人工处理目录的提交或合并状态已改变。')
            if git(path,'ls-files','-u','-z'): raise ValueError('还有未解决或未暂存的合并冲突。')
            if git(path,'diff','--name-only','--no-ext-diff','--no-textconv').strip():
                raise ValueError('请先 git add 所有已解决的改动。')
            resolved = git(path,'write-tree').decode().strip()
            changed = git(self.project,'diff','--name-only','-z',record['git_tree'],resolved).decode().split('\0')
            if any(name and not editable(name) for name in changed):
                raise ValueError('人工冲突处理修改了允许范围之外的文件。')
            record['git_tree']=resolved; record['human_resolved']=True
            return self._finish_prepare(record,existing=True)

    def check(self, identity):
        with self.workspace.delivery_lock(),repository_lock(self.project):
            self.workspace.ensure_idle()
            record = self._get(identity)
            if record['state']!='prepared': raise ValueError('请先准备没有冲突的合并结果。')
            self._current(record)
            return self.jobs(identity).start(FrozenWorktree(record),'rules')

    def _checks(self, record):
        checks = self.jobs(record['preparation_id']).list(FrozenWorktree(record))
        current = [j for j in checks if j['matches_current_candidate'] and j['matches_current_definition']]
        passed = any(j['check_set']=='rules' and j['status']=='completed' and j['result']['verdict']=='PASS' for j in current)
        failed = any(j['check_set']!='diagnostic' and j['status']=='completed' and j['result']['verdict']=='FAIL' for j in current)
        return checks, passed and not failed

    def _discard_snapshot(self, record):
        path=Path(record['worktree_path'])
        expected=self.root/record['preparation_id']/'workspace'
        if path.resolve()!=expected.resolve() or path.is_symlink():raise ValueError('交付目录不匹配。')
        if not path.exists():return {'absent':True}
        directory=Path(git(path,'rev-parse','--absolute-git-dir').decode().strip()).resolve()
        expected_commit=record.get('merge_commit',record['target_commit'])
        if (common_dir(path)!=common_dir(self.project) or oid(path)!=expected_commit
            or Path((directory/'gitdir').read_text(encoding='utf-8').strip()).resolve()!=(path/'.git').resolve()
            or (record.get('git_pointer') and (path/'.git').read_text(encoding='utf-8')!=record['git_pointer'])):
            raise ValueError('交付目录已被外部改动，不能自动清理。')
        holder=object.__new__(ProjectWorkspace);holder.path=path
        baseline=read_tree(self.project,record['target_commit'])['files']
        files,total={},0
        for entry in sorted(path.rglob('*')):
            if entry==path/'.git':continue
            import stat
            info=entry.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('交付目录有链接，保留现场。')
            if entry.is_dir():continue
            name=entry.relative_to(path).as_posix()
            raw=holder._path(name).read_bytes();total+=len(raw)
            if total>MAX_TREE or len(files)>=2000:raise ValueError('现场超出支持范围，保留目录。')
            value=item(raw)
            if not editable(name) and value!=baseline.get(name):raise ValueError('有额外人工修改的只读文件，请先保存并移出。')
            files[name]=value
        return {'tree':{'schema':'development-tree-v1','files':files},
                'index':git(path,'ls-files','--stage','-z').decode('utf-8'),
                'head':expected_commit,'git_dir':str(directory),'git_pointer':(path/'.git').read_text(encoding='utf-8')}

    def _cleanup_info(self, record):
        result={'preparation_id':record['preparation_id'],'state':record['state'],'cleanup_hash':None}
        if record['state'] in ('prepared','conflict','preparing','abandoning'):
            try:
                snapshot=self._discard_snapshot(record)
                result['cleanup_hash']=record.get('abandon_hash') if record['state']=='abandoning' and snapshot.get('absent') else digest({'id':record['preparation_id'],'snapshot':snapshot})
            except (ValueError,OSError) as exc:result['cleanup_error']=str(exc)
        return result

    def discard(self, identity, cleanup_hash):
        with self.workspace.delivery_lock(),repository_lock(self.project):
            self.workspace.ensure_idle()
            record=self._get(identity)
            if record['state']=='abandoned':return self.status(identity)
            info=self._cleanup_info(record)
            if not cleanup_hash or cleanup_hash!=info['cleanup_hash']:
                raise ValueError(info.get('cleanup_error') or '准备现场已经变化，请重新查看后再废弃。')
            if any(j['status'] in ('running','unknown') for j in self.jobs(identity).list()):
                raise ValueError('检查还未结束，不能清理准备目录。')
            snapshot=self._discard_snapshot(record)
            path=Path(record['worktree_path'])
            backup=path.parent/'abandoned.json'
            if not (record['state']=='abandoning' and snapshot.get('absent')):
                atomic_json(backup,{'preparation':record,'snapshot':snapshot,'cleanup_hash':cleanup_hash})
            elif not backup.exists():raise ValueError('缺少已保存现场，拒绝补记清理成功。')
            record['state']='abandoning';record['abandon_hash']=cleanup_hash;self._save(record)
            if path.exists():
                # Explicit approval is tied to the exact allowed files and
                # index just saved in abandoned.json. Unknown files never pass.
                git(self.project,'worktree','remove','--force',str(path))
            record['state']='abandoned';self._save(record)
            return self.status(identity)

    def status(self, identity=None):
        record = self._get(identity)
        if record is None: return None
        value = {**record,'can_approve':False,'approval_hash':None,'checks':[], 'stale_reason':None}
        value.update(self._cleanup_info(record))
        if identity is None:
            with closing(self.connect()) as db:
                pending=[json.loads(row[0]) for row in db.execute("SELECT data FROM preparations WHERE id!=? AND state IN ('prepared','conflict','preparing','abandoning')",(record['preparation_id'],))]
                applied=db.execute("SELECT id FROM preparations WHERE state='applied' ORDER BY rowid DESC LIMIT 1").fetchone()
            value['other_preparations']=[self._cleanup_info(p) for p in pending]
            value['adopted_preparation']=applied['id'] if applied else None
        if self.workspace.metadata.get('archived'):
            return {**value,'checks':self.jobs(record['preparation_id']).list(),
                    'note':'任务已归档；保留交付与检查记录。','archived':True}
        if record['state'] in ('applying','applied','restored'):
            value['checks']=self.jobs(record['preparation_id']).list()
        if record['state']=='prepared':
            try:
                self._current(record)
                checks, passed = self._checks(record)
                value['checks']=checks
                value['approval_hash']=digest({'record':{k:v for k,v in record.items() if k!='approved_hash'},'checks':checks})
                value['can_approve']=passed
            except ValueError as exc: value['stale_reason']=str(exc)
        if record['state']=='applying': value['note']='合并响应中断；请继续原确认操作，程序会核对实际 Git 版本。'
        elif record['state']=='applied': value['note']='修改已通过 Git 合入 '+record['target_branch']+'。'
        elif record['state']=='restored': value['note']='已新增撤销提交，Git 历史和检查记录均已保留。'
        elif record['state']=='abandoned': value['note']='这次准备已废弃；人工修改和暂存区记录保存在交付目录旁的 abandoned.json。'
        elif record['state']=='conflict': value['note']='存在合并冲突，请在交付目录处理后 git add，再检查处理结果。'
        else: value['note']='先检查准备合入的代码，再审阅差异并确认。'
        return value

    def approve(self, identity, approval_hash, *, _after_merge=None):
        with self.workspace.delivery_lock(),repository_lock(self.project):
            self.workspace.ensure_idle()
            record = self._get(identity)
            if record['state'] in ('applying','applied','restored'):
                if approval_hash!=record.get('approved_hash'): raise ValueError('审批内容不匹配。')
                head = self._target()
                if head==record['merge_commit']:
                    self._completed(record)
                    return self.status(identity)
                if record['state'] in ('applied','restored') or head!=record['target_commit']:
                    raise ValueError('原项目有后续变化，停止自动重试，请人工核对。')
                # An intent was saved but Git did not run. Revalidate the same
                # immutable review without creating another commit.
                record['state']='prepared'; self._save(record)
            if record['state']!='prepared': raise ValueError('该准备记录不能合入。')
            current = self.status(identity)
            if not current['can_approve'] or not approval_hash or current['approval_hash']!=approval_hash:
                raise ValueError(current['stale_reason'] or '检查未通过或审批内容已变化，请重新审阅。')
            self._current(record)
            FrozenWorktree(record).snapshot()
            record['approved_hash']=approval_hash; record['state']='applying'; self._save(record)
            git(self.project,'merge','--ff-only','--no-edit','--no-overwrite-ignore',record['merge_commit'])
            if _after_merge: _after_merge()
            self._target(record['merge_commit'])
            self._completed(record)
            return self.status(identity)

    def _completed(self, record):
        record['state']='restored' if record['kind']=='revert' else 'applied'
        if record['kind']=='revert':
            previous = self._get(record['original_operation'])
            previous['state']='restored'
            previous['reverted_by']=record['merge_commit']
            # Both ledger updates belong to a single local SQLite transaction.
            with closing(self.connect()) as db,db:
                for value in (previous,record):
                    db.execute('UPDATE preparations SET data=?,state=? WHERE id=?',
                        (encoded(value).decode(),value['state'],value['preparation_id']))
        else: self._save(record)
