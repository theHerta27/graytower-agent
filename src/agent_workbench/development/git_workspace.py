"""Task branches and restricted linked worktrees; old snapshots remain separate."""
import json
from pathlib import Path
import sqlite3
import stat
import uuid
from contextlib import closing
from .workspace import ProjectWorkspace, digest
from .git_support import (FileLock, git, oid, common_dir, repository_lock, read_tree,
    create_worktree, atomic_json, snapshot_tree, commit_tree, configure_sparse)


class GitWorkspace(ProjectWorkspace):
    def __init__(self, control):
        self.control = Path(control).resolve()
        self.path = self.control/'workspace'
        self.metadata = json.loads((self.control/'project.json').read_text(encoding='utf-8'))
        self._lock = FileLock(self.control/'mutation.lock')
        self.baseline = read_tree(self.metadata['project'],self.metadata['baseline_commit'])
        if digest(self.baseline) != self.metadata['baseline_tree_hash']:
            raise ValueError('baseline snapshot damaged')
        self._validate()

    def mutation_lock(self):
        return self._lock

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

    def _validate(self):
        latest = json.loads((self.control/'project.json').read_text(encoding='utf-8'))
        self.metadata = latest
        pointer = self.path/'.git'
        for part in (self.path,pointer,*self.path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('linked worktree metadata')
        if not pointer.is_file() or pointer.stat().st_nlink!=1 or pointer.read_text(encoding='utf-8')!=latest['git_pointer']:
            raise ValueError('Git 工作树指针已经改变。')
        directory = Path(git(self.path,'rev-parse','--absolute-git-dir').decode().strip()).resolve()
        if str(directory)!=latest['git_dir'] or common_dir(self.path)!=Path(latest['common_dir']):
            raise ValueError('Git 工作树身份不匹配。')
        if Path((directory/'gitdir').read_text(encoding='utf-8').strip()).resolve()!=pointer.resolve():
            raise ValueError('Git 工作树登记路径不匹配。')
        if (git(self.path,'symbolic-ref','--short','HEAD').decode().strip()!=latest['task_branch']
            or oid(self.path)!=latest['candidate_commit']):
            raise ValueError('任务分支或 HEAD 被外部改变。')
        if git(self.path,'write-tree').decode().strip()!=git(self.path,'rev-parse','HEAD^{tree}').decode().strip():
            raise ValueError('候选 index 暂存区被外部改变。')
        return latest

    def snapshot(self):
        with self._lock:
            self._validate()
            return super().snapshot()

    def inspect(self):
        with self._lock:
            view = super().inspect()
            tree = snapshot_tree(self.path,self.metadata['baseline_commit'],self.snapshot())
            view['patch'] = git(self.path,'diff','--no-ext-diff','--no-textconv','--binary',
                self.metadata['baseline_commit'],tree,'--').decode('utf-8')
            view['git_tree'] = tree
            return view

    def freeze(self):
        with self._lock, repository_lock(self.path):
            self._validate()
            tree = self.snapshot()
            full_tree = snapshot_tree(self.path,self.metadata['baseline_commit'],tree)
            previous = self.metadata['candidate_commit']
            if full_tree==git(self.path,'rev-parse',previous+'^{tree}').decode().strip(): return previous
            commit = commit_tree(self.path,full_tree,[previous],'Graytower: freeze candidate')
            atomic_json(self.control/'freeze.json',{'before':previous,'after':commit,'state':'prepared'})
            git(self.path,'update-ref','refs/heads/'+self.metadata['task_branch'],commit,previous)
            git(self.path,'read-tree',commit)
            all_names = git(self.path,'ls-files','-z')
            git(self.path,'update-index','--skip-worktree','-z','--stdin',data=all_names)
            git(self.path,'update-index','--no-skip-worktree','-z','--stdin',data=b''.join(n.encode()+b'\0' for n in tree['files']))
            configure_sparse(self.path,tree['files'])
            self.metadata['candidate_commit'] = commit
            atomic_json(self.control/'project.json',self.metadata)
            atomic_json(self.control/'freeze.json',{'before':previous,'after':commit,'state':'completed'})
            return commit
