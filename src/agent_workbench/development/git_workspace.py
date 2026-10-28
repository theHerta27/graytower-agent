"""Task branches and restricted linked worktrees; old snapshots remain separate."""
import json
from pathlib import Path
import sqlite3
import stat
import uuid
from contextlib import closing, contextmanager
from .workspace import ProjectWorkspace, digest, editable
from .git_support import (FileLock, git, oid, common_dir, repository_lock, read_tree,
    create_worktree, atomic_json, snapshot_tree, commit_tree, configure_sparse, commit_tree_id)


class GitWorkspace(ProjectWorkspace):
    def __init__(self, control):
        self.control = Path(control).resolve()
        self.path = self.control/'workspace'
        self.metadata = json.loads((self.control/'project.json').read_text(encoding='utf-8'))
        self._lock = FileLock(self.control/'mutation.lock')
        self.baseline = read_tree(self.metadata['project'],self.metadata['baseline_commit'])
        if digest(self.baseline) != self.metadata['baseline_tree_hash']:
            raise ValueError('baseline snapshot damaged')
        with self._lock:
            self._recover()
            self._validate()

    def mutation_lock(self):
        return self._lock

    @contextmanager
    def delivery_lock(self):
        # A running model keeps driver.lock, but readers can still take the
        # short mutation lock between tool writes and show live progress.
        with FileLock(self.control/'driver.lock'),self._lock:
            yield

    def _recover(self):
        archive=self.control/'archive.json'
        if not self.metadata.get('archived') and not self.path.exists() and archive.exists():
            saved=json.loads(archive.read_text(encoding='utf-8'))
            if (saved['view']['candidate_commit']!=self.metadata['candidate_commit']
                or digest(saved['tree'])!=saved['view']['tree_hash']
                or oid(self.metadata['project'],'refs/heads/'+self.metadata['task_branch'])!=self.metadata['candidate_commit']):
                raise ValueError('归档现场不一致，请人工核对。')
            registered=git(self.metadata['project'],'worktree','list','--porcelain').decode()
            if 'worktree '+self.path.as_posix()+'\n' in registered:
                raise ValueError('工作树仍有登记，不能把缺失目录当作已清理。')
            self.metadata['archived']=True
            atomic_json(self.control/'project.json',self.metadata)
        if self.metadata.get('archived'): return
        journal=self.control/'freeze.json'
        if not journal.exists(): return
        record=json.loads(journal.read_text(encoding='utf-8'))
        if record['state']!='prepared': return
        actual=oid(self.path)
        if actual==record['before'] and self.metadata['candidate_commit']==actual:
            self._validate()
            record['state']='not_applied'; atomic_json(journal,record)
            return
        if actual!=record['after'] or self.metadata['candidate_commit'] not in (record['before'],record['after']):
            raise ValueError('冻结操作中断后出现其他提交，请人工核对。')
        self._validate(expected_head=actual,check_index=False)
        index=git(self.path,'write-tree').decode().strip()
        allowed={git(self.path,'rev-parse',c+'^{tree}').decode().strip() for c in (record['before'],record['after'])}
        tree=read_tree(self.path,actual)
        if index not in allowed or digest(ProjectWorkspace.snapshot(self))!=digest(tree):
            raise ValueError('冻结操作中断后文件或暂存区另有变化，保留现场。')
        self._refresh_index(actual,tree)
        self.metadata['candidate_commit']=actual
        atomic_json(self.control/'project.json',self.metadata)
        record['state']='completed'; atomic_json(journal,record)

    def _refresh_index(self,commit,tree):
        git(self.path,'read-tree',commit)
        all_names=git(self.path,'ls-files','-z')
        git(self.path,'update-index','--skip-worktree','-z','--stdin',data=all_names)
        git(self.path,'update-index','--no-skip-worktree','-z','--stdin',data=b''.join(n.encode()+b'\0' for n in tree['files']))
        configure_sparse(self.path,tree['files'])

    def ensure_idle(self):
        self._validate()
        if self.metadata.get('archived'): raise ValueError('任务已归档，仅可查看记录。')
        for claimed in (self.control/'runs').glob('*/claimed'):
            result = claimed.parent/'run-result.json'
            if not result.exists() or not json.loads(result.read_text(encoding='utf-8')).get('closed'):
                raise ValueError('Agent 任务尚未结束，请先继续并结束原任务，再准备交付。')

    @classmethod
    def create(cls, project, control, ref='HEAD'):
        project, control = Path(project).resolve(), Path(control).resolve()
        if control.exists() or control.is_relative_to(project) or project.is_relative_to(control):
            raise ValueError('require a fresh control directory outside the source project')
        if Path(git(project,'rev-parse','--show-toplevel').decode().strip()).resolve()!=project:
            raise ValueError('select the Git project root')
        with repository_lock(project):
            if git(project,'status','--porcelain','--untracked-files=no').strip():
                raise ValueError('source has uncommitted changes; save a version before creating a task')
            branch = git(project,'symbolic-ref','--short','HEAD').decode().strip()
            commit = oid(project,str(ref)); tree = read_tree(project,commit)
            identity = uuid.uuid4().hex
            task_branch = 'graytower/task-'+identity
            control.mkdir(parents=True)
            atomic_json(control/'creation.json',{'project':str(project),'branch':task_branch,'commit':commit,'state':'creating'})
            registered = create_worktree(project,control/'workspace',commit,tree,task_branch)
            atomic_json(control/'project.json',{'schema':'development-project-v2','mode':'git_worktree',
                'project':str(project),'baseline_commit':commit,'baseline_tree_hash':digest(tree),
                'candidate_commit':commit,'task_branch':task_branch,'target_branch':branch,
                'common_dir':str(common_dir(project)),**registered})
            with closing(sqlite3.connect(control/'edits.sqlite')) as db,db:
                db.execute('CREATE TABLE edits (id TEXT PRIMARY KEY,input TEXT NOT NULL,before_hash TEXT,after_hash TEXT,content TEXT,status TEXT NOT NULL)')
            atomic_json(control/'creation.json',{'project':str(project),'branch':task_branch,'commit':commit,'state':'ready'})
        return cls(control)

    def _validate(self,*,expected_head=None,check_index=True):
        latest = json.loads((self.control/'project.json').read_text(encoding='utf-8'))
        self.metadata = latest
        if latest.get('archived'):
            return latest
        pointer = self.path/'.git'
        for part in (self.path,pointer,*self.path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('linked worktree metadata')
        if not pointer.is_file() or pointer.stat().st_nlink!=1 or pointer.read_text(encoding='utf-8')!=latest['git_pointer']:
            raise ValueError('Git 工作树指针已经改变。')
        raw_pointer=pointer.read_text(encoding='utf-8')
        if not raw_pointer.startswith('gitdir: '):raise ValueError('Git 工作树指针格式错误。')
        directory=Path(raw_pointer[len('gitdir: '):].strip())
        if not directory.is_absolute():directory=self.path/directory
        directory=directory.resolve()
        actual_common=(directory/(directory/'commondir').read_text(encoding='utf-8').strip()).resolve()
        if str(directory)!=latest['git_dir'] or actual_common!=Path(latest['common_dir']):
            raise ValueError('Git 工作树身份不匹配。')
        if Path((directory/'gitdir').read_text(encoding='utf-8').strip()).resolve()!=pointer.resolve():
            raise ValueError('Git 工作树登记路径不匹配。')
        if ((directory/'HEAD').read_text(encoding='utf-8').strip()!='ref: refs/heads/'+latest['task_branch']
            or oid(self.path)!=(expected_head or latest['candidate_commit'])):
            raise ValueError('任务分支或 HEAD 被外部改变。')
        if check_index and git(self.path,'write-tree').decode().strip()!=commit_tree_id(str(self.path),expected_head or latest['candidate_commit']):
            raise ValueError('候选 index 暂存区被外部改变。')
        return latest

    def snapshot(self):
        with self._lock:
            self._validate()
            if self.metadata.get('archived'):
                return json.loads((self.control/'archive.json').read_text(encoding='utf-8'))['tree']
            return super().snapshot()

    def inspect(self):
        with self._lock:
            self._validate()
            if self.metadata.get('archived'):
                return {**json.loads((self.control/'archive.json').read_text(encoding='utf-8'))['view'],'archived':True}
            snapshot = self.snapshot()
            before,after = self.baseline['files'],snapshot['files']
            view = {**self.metadata,'tree_hash':digest(snapshot),
                'changed_files':sorted(k for k in set(before)|set(after) if before.get(k)!=after.get(k)),
                'added_files':sorted(set(after)-set(before)),'deleted_files':sorted(set(before)-set(after)),
                'files':[{'path':n,'sha256':v['sha256'],'editable':editable(n)} for n,v in after.items()],
                'scope_check':'PASS','tests_run':False}
            tree = snapshot_tree(self.path,self.metadata['baseline_commit'],snapshot)
            view['patch'] = git(self.path,'diff','--no-ext-diff','--no-textconv','--binary',
                self.metadata['baseline_commit'],tree,'--').decode('utf-8')
            view['git_tree'] = tree
            return view

    def freeze(self):
        with self._lock, repository_lock(self.path):
            self._validate()
            if self.metadata.get('archived'): raise ValueError('任务已经归档，不能继续修改。')
            tree = self.snapshot()
            full_tree = snapshot_tree(self.path,self.metadata['baseline_commit'],tree)
            previous = self.metadata['candidate_commit']
            if full_tree==git(self.path,'rev-parse',previous+'^{tree}').decode().strip(): return previous
            commit = commit_tree(self.path,full_tree,[previous],'Graytower: freeze candidate')
            atomic_json(self.control/'freeze.json',{'before':previous,'after':commit,'state':'prepared'})
            git(self.path,'update-ref','refs/heads/'+self.metadata['task_branch'],commit,previous)
            self._refresh_index(commit,tree)
            self.metadata['candidate_commit'] = commit
            atomic_json(self.control/'project.json',self.metadata)
            atomic_json(self.control/'freeze.json',{'before':previous,'after':commit,'state':'completed'})
            return commit

    def write_file(self, *args, **kwargs):
        with self._lock:
            self._validate()
            if self.metadata.get('archived'): raise ValueError('任务已经归档，不能继续修改。')
            return super().write_file(*args, **kwargs)

    def read_file(self, name):
        if self.metadata.get('archived'):
            import base64
            from .workspace import clean_name
            clean_name(name)
            value = self.snapshot()['files'].get(name)
            if value is None: raise ValueError('归档中没有该文件。')
            return {'path':name,'sha256':value['sha256'],'text':base64.b64decode(value['content']).decode()}
        return super().read_file(name)

    def archive(self):
        from .checks import CheckJobs
        from .git_delivery import GitDelivery, FrozenWorktree
        with self.delivery_lock(),repository_lock(self.metadata['project']):
            self._validate()
            if self.metadata.get('archived'): return self.inspect()
            for database in self.control.rglob('checks.sqlite'):
                if any(j['status'] in ('running','unknown') for j in CheckJobs(database.parent).list()):
                    raise ValueError('仍有进行中或结果未知的检查，请先核对回执。')
            with closing(sqlite3.connect(self.control/'edits.sqlite')) as db:
                if db.execute("SELECT 1 FROM edits WHERE status!='completed' LIMIT 1").fetchone():
                    raise ValueError('仍有未完成的编辑，请先恢复原操作。')
            for result in (self.control/'runs').glob('*/claimed'):
                output = result.parent/'run-result.json'
                if not output.exists() or not json.loads(output.read_text(encoding='utf-8')).get('closed'):
                    raise ValueError('仍有未结束的 Agent 任务。')
            delivery = GitDelivery(self)
            with closing(delivery.connect()) as db:
                records = [json.loads(row[0]) for row in db.execute('SELECT data FROM preparations')]
            for record in records:
                if record['state'] in ('preparing','conflict','applying','abandoning'):
                    raise ValueError('仍有未完成或待处理冲突的交付目录，请先处理。')
                if Path(record['worktree_path']).exists(): FrozenWorktree(record).snapshot()
            self.freeze()
            view,tree = self.inspect(),self.snapshot()
            atomic_json(self.control/'archive.json',{'view':view,'tree':tree,'deliveries':records})
            # Every candidate/receipt was validated before any removal. Use Git's
            # own registered-worktree cleanup, never a recursive directory delete.
            for record in records:
                path = Path(record['worktree_path']).resolve()
                if path.exists():
                    if not path.is_relative_to(self.control/'deliveries'): raise ValueError('交付目录越界。')
                    git(self.metadata['project'],'worktree','remove',str(path))
            git(self.metadata['project'],'worktree','remove',str(self.path))
            self.metadata['archived']=True
            atomic_json(self.control/'project.json',self.metadata)
            return self.inspect()
