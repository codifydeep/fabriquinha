"""Prototype fixed Node test operation; NOT wired to workers or production gates."""
import hashlib,re,subprocess,selectors,time
from pathlib import Path

def manifest(directory):
    root=Path(directory)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():raise ValueError('absolute controller-owned snapshot directory required')
    result={};total=0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('snapshot symlinks forbidden')
        if path.is_dir():continue
        if not path.is_file():raise ValueError('regular files only')
        relative=path.relative_to(root).as_posix()
        if any(p in ('.git','.ssh','.aws','.config') or p.startswith('.env') for p in path.relative_to(root).parts):raise ValueError('private metadata forbidden')
        raw=path.read_bytes();total+=len(raw)
        if total>16*1024*1024 or len(result)>=1000:raise ValueError('snapshot budget exceeded')
        result[relative]=hashlib.sha256(raw).hexdigest()
    if not result:raise ValueError('empty snapshot')
    return result

def command(directory,image,identity,kind='node'):
    root=Path(directory)
    manifest(root)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise ValueError('pinned local image ID required')
    if not re.fullmatch(r'[a-z0-9-]{1,40}',identity):raise ValueError('invalid sandbox identity')
    if kind not in ('node','lobby-ts','governance'):raise ValueError('unregistered runner')
    return ['docker','run','--rm','--pull=never','--name','truco-online-ci-adapter-'+identity,
        '--label','com.docker.compose.project=truco-online',
        '--label','com.codifydeep.project=truco-online','--label','com.codifydeep.environment=ci',
        '--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
        '--user=10000:10000','--pids-limit=128','--memory='+('1024m' if kind=='lobby-ts' else '256m'),'--cpus=1',
        '--tmpfs=/tmp:rw,nosuid,noexec,size=128m','--mount',f'type=bind,source={root},target=/workspace,readonly',
        '--workdir=/workspace','--entrypoint='+('python' if kind=='governance' else 'node'),image,*(['--test'] if kind=='node' else ['/opt/hermes/product_governance_probe.py'] if kind=='governance' else ['/opt/toolchain/run.mjs'])]

def run(directory,image,identity,kind='node'):
    before=manifest(directory);cmd=command(directory,image,identity,kind)
    if kind in ('lobby-ts','governance'):
        # Bound output while reading, not after an unbounded capture_output.
        process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        output=bytearray();start=time.monotonic();selector=selectors.DefaultSelector()
        selector.register(process.stdout,selectors.EVENT_READ)
        try:
            while selector.get_map():
                if time.monotonic()-start>100:raise TimeoutError('validation timeout')
                for key,_ in selector.select(.2):
                    chunk=__import__('os').read(key.fileobj.fileno(),8192)
                    if not chunk:selector.unregister(key.fileobj);continue
                    output.extend(chunk)
                    if len(output)>512*1024:raise ValueError('validation output limit')
            code=process.wait(timeout=5)
        except BaseException:
            subprocess.run(['docker','rm','-f','truco-online-ci-adapter-'+identity],capture_output=True,timeout=15)
            process.kill();process.wait(timeout=5);raise
        finally:selector.close();process.stdout.close()
        if before!=manifest(directory):raise PermissionError('snapshot mutated during validation')
        raw=output.decode('utf8','replace')
        return dict(passed=code==0,exit_code=code,snapshot=before,image=image,
                    log_sha256=hashlib.sha256(output).hexdigest(),output=raw,
                    scope='governance_integrity_probe' if kind=='governance' else 'lobby_typescript_unit_validation',product_released=False)
    try:
        result=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
    except subprocess.TimeoutExpired:
        # Exact per-run name only; never broad Docker cleanup.
        subprocess.run(['docker','rm','-f','truco-online-ci-adapter-'+identity],capture_output=True,timeout=15)
        raise
    after=manifest(directory)
    if before!=after:raise PermissionError('snapshot mutated during validation')
    return dict(passed=result.returncode==0,exit_code=result.returncode,snapshot=before,image=image,
        log_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),output=result.stdout[-12000:],
        scope='isolated_node_test_prototype',agent_e2e_validated=False,product_released=False)
