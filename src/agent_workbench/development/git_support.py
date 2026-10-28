"""Local Git primitives. No hooks, implicit identity, signing or shell commands."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from functools import lru_cache
import json


class FileLock:
    """Nonblocking process lock, reentrant only in the owning Python thread."""
    _registry = {}
    _guard = threading.Lock()

    def __init__(self, path):
        self.path = Path(path).resolve()
        with self._guard:
            self.state = self._registry.setdefault(str(self.path), {'lock':threading.RLock(), 'depth':0})

    def __enter__(self):
        state = self.state
        if not state['lock'].acquire(blocking=False):
            raise ValueError('已有操作正在进行，请稍后再试。')
        try:
            if not state['depth']:
                stream = self.path.open('a+b')
                try:
                    if stream.tell() == 0:
                        stream.write(b'0'); stream.flush()
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    stream.close()
                    raise ValueError('已有另一个进程正在操作此任务或仓库。') from None
                state['stream'] = stream
            state['depth'] += 1
            return self
        except BaseException:
            state['lock'].release()
            raise

    def __exit__(self, *_):
        state = self.state
        state['depth'] -= 1
        try:
            if not state['depth']:
                stream = state.pop('stream'); stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                stream.close()
        finally:
            state['lock'].release()


def run(project, *args, data=None, env=None, sparse=False, allowed=(0,)):
    path = Path(project).resolve()
    process_env = {k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_')}
    process_env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    if env: process_env.update(env)
    command = ['git', '-c', 'safe.directory='+path.as_posix(), '-c', 'core.autocrlf=false',
               '-c', 'core.hooksPath='+os.devnull, '-c', 'core.fsmonitor=false',
               '-c', 'commit.gpgsign=false', '-c', 'core.attributesFile='+os.devnull,
               '-c', 'core.quotePath=false']
    # Repository-configured filters/drivers must not run executable code.
    keys = subprocess.run(command+['-C',str(path),'config','--name-only','--get-regexp',
        r'^(filter\..*\.(clean|smudge|process|required)|merge\..*\.driver)$'],
        capture_output=True, env=process_env, timeout=40)
    if keys.returncode not in (0,1):
        raise ValueError('无法读取 Git 配置。')
    for key in keys.stdout.decode().splitlines():
        command += ['-c', key+('=false' if key.endswith('.required') else '=')]
    if sparse: command += ['-c','core.sparseCheckout=true','-c','core.sparseCheckoutCone=false']
    result = subprocess.run(command+['-C',str(path),*map(str,args)], input=data,
                            capture_output=True, env=process_env, timeout=60)
    if result.returncode not in allowed:
        raise ValueError('Git 操作失败：'+result.stderr.decode('utf-8',errors='replace')[-700:])
    return result


def git(project, *args, **kwargs):
    return run(project, *args, **kwargs).stdout


def oid(project, ref='HEAD'):
    return git(project,'rev-parse','--verify','--end-of-options',ref+'^{commit}').decode().strip()


def atomic_json(path, value):
    from .workspace import encoded
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='record-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def common_dir(project):
    return Path(git(project,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()).resolve()


def repository_lock(project):
    return FileLock(common_dir(project)/'graytower.lock')


def read_tree(project, commit):
    return json.loads(_read_tree(str(Path(project).resolve()),commit))


@lru_cache(maxsize=32)
def _read_tree(project, commit):
    from .workspace import readable, editable, clean_name, item, MAX_FILE, MAX_TREE
    files, total, selected = {}, 0, []
    for entry in git(project,'ls-tree','-rzl',commit).split(b'\0'):
        if not entry: continue
        header, raw_name = entry.split(b'\t',1)
        name = raw_name.decode('utf-8')
        if not readable(name): continue
        clean_name(name)
        mode, kind, blob, size = header.decode().split()
        if kind != 'blob' or mode not in ('100644','100755'):
            raise ValueError('linked source entries are unsupported')
        size = int(size)
        total += size
        if size > MAX_FILE or total > MAX_TREE or len(files) >= 2000:
            raise ValueError('project exceeds supported candidate limits')
        selected.append((name,blob,size))
    if not selected or not any(editable(n) for n,_,_ in selected):
        raise ValueError('project has no supported game rule source')
    output = git(project,'cat-file','--batch',data=''.join(blob+'\n' for _,blob,_ in selected).encode())
    offset = 0
    for name,blob,size in selected:
        end = output.index(b'\n',offset)
        if output[offset:end].decode()!=f'{blob} blob {size}': raise ValueError('Git blob identity changed')
        files[name] = item(output[end+1:end+1+size])
        offset = end+size+2
    return json.dumps({'schema':'development-tree-v1','files':files})


def configure_sparse(path, names):
    directory = Path(git(path,'rev-parse','--absolute-git-dir').decode().strip())
    (directory/'info').mkdir(exist_ok=True)
    def escape(name):
        return ''.join('\\'+c if c in '*?[]\\' else c for c in name)
    (directory/'info/sparse-checkout').write_text(''.join('/'+escape(n)+'\n' for n in sorted(names)),encoding='utf-8')


def create_worktree(project, path, commit, tree, branch=None):
    """No checkout filters: populate allowed blobs, keep Git's own full index."""
    import base64
    path = Path(path)
    if path.exists(): raise ValueError('工作树路径已存在，拒绝覆盖。')
    args = ['worktree','add','--no-checkout']
    args += ['-b',branch] if branch else ['--detach']
    git(project,*args,str(path),commit)
    git(path,'read-tree',commit)
    names = git(path,'ls-files','-z')
    git(path,'update-index','--skip-worktree','-z','--stdin',data=names)
    configure_sparse(path,tree['files'])
    for name, value in tree['files'].items():
        target = path/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(base64.b64decode(value['content']))
    git(path,'update-index','--no-skip-worktree','-z','--stdin',
        data=b''.join(n.encode()+b'\0' for n in tree['files']))
    return {'git_dir':str(Path(git(path,'rev-parse','--absolute-git-dir').decode().strip()).resolve()),
            'git_pointer':(path/'.git').read_text(encoding='utf-8')}


def commit_tree(project, tree, parents, message):
    args = ['commit-tree',tree]
    for parent in parents: args += ['-p',parent]
    return git(project,*args,data=(message+'\n').encode(),env={
        'GIT_AUTHOR_NAME':'Graytower Agent','GIT_AUTHOR_EMAIL':'graytower@localhost',
        'GIT_COMMITTER_NAME':'Graytower Agent','GIT_COMMITTER_EMAIL':'graytower@localhost'}).decode().strip()


@contextmanager
def temporary_index(project, commit):
    fd, name = tempfile.mkstemp(prefix='graytower-index-')
    os.close(fd); os.unlink(name)
    env = {'GIT_INDEX_FILE':name}
    try:
        git(project,'read-tree',commit,env=env)
        yield env
    finally:
        for file in (name,name+'.lock'):
            if os.path.exists(file): os.unlink(file)


def snapshot_tree(project, parent, tree):
    """Write only changed allowed blobs without invoking clean/smudge filters."""
    import base64
    from .workspace import editable
    original = read_tree(project,parent)['files']
    with temporary_index(project,parent) as env:
        for name in sorted(set(original)|set(tree['files'])):
            before, after = original.get(name), tree['files'].get(name)
            if before == after: continue
            if not editable(name): raise ValueError('只读文件不能进入候选提交。')
            if after is None:
                git(project,'update-index','--force-remove','--',name,env=env)
            else:
                blob = git(project,'hash-object','-w','--stdin',data=base64.b64decode(after['content'])).decode().strip()
                prior = git(project,'ls-tree',parent,'--',name).decode()
                mode = prior.split()[0] if prior else '100644'
                git(project,'update-index','--add','--cacheinfo',mode,blob,name,env=env)
        return git(project,'write-tree',env=env).decode().strip()
