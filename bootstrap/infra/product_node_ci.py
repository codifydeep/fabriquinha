"""Run from the trusted PR base. Node fixture only, no package installation."""
import hashlib,json,os,re,subprocess,tempfile,uuid
from pathlib import Path

def git(*args):return subprocess.check_output(['git',*args],timeout=30)

def validate_files(expected,actual):
    hashes={n:hashlib.sha256(v).hexdigest() for n,v in actual.items()}
    if hashes!=expected:raise PermissionError('CI files do not match approved snapshot')

def main():
    base=os.environ['BASE_SHA'];head=os.environ['HEAD_SHA']
    if not all(re.fullmatch('[a-f0-9]{40}',v) for v in (base,head)):raise ValueError('exact Git SHAs required')
    policy=json.loads(git('show',base+':adapter-control/expected.json'))
    expected=policy['files'];image=policy['image']
    if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('pinned image required')
    for name in expected:
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or not name.startswith('adapter-node/'):raise ValueError('unsafe manifest')
    changed=set(git('diff','--name-only',base,head).decode().splitlines())
    if not changed or not changed<=set(expected):raise PermissionError('unreviewed workflow or infrastructure change')
    actual={n:git('show',head+':'+n) for n in expected};validate_files(expected,actual)
    with tempfile.TemporaryDirectory(dir=os.getcwd(),prefix='.adapter-ci-') as tmp:
        root=Path(tmp);root.chmod(0o755)
        for name,raw in actual.items():
            path=root/name.removeprefix('adapter-node/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);path.chmod(0o444)
        name='truco-online-ci-node-'+uuid.uuid4().hex
        try:
            result=subprocess.run(['docker','run','--rm','--pull=never','--name',name,
                '--label','com.docker.compose.project=truco-online','--network=none','--read-only','--cap-drop=ALL',
                '--security-opt=no-new-privileges','--pids-limit=64','--memory=256m','--cpus=1','--user=10000:10000',
                '--tmpfs=/tmp:rw,nosuid,noexec,size=32m','--mount',f'type=bind,src={root},dst=/workspace,readonly',
                '--workdir=/workspace','--entrypoint=node',image,'--test'],capture_output=True,text=True,timeout=60)
            output=result.stdout
            if result.returncode or not re.search(r'^# tests [1-9][0-9]*$',output,re.M) or not re.search(r'^# fail 0$',output,re.M) or any(map(int,re.findall(r'^# (?:skipped|cancelled|todo) (\d+)$',output,re.M))):
                raise RuntimeError('Node full suite failed or ignored tests')
            print(json.dumps(dict(head=head,revision=policy['revision'],passed=True,scope='node-fixture-only')))
        finally:subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=20)

if __name__=='__main__':main()
