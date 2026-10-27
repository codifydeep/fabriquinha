"""Closed Git exports for native operation. No SDK, Docker, key or network.

Hashes detect drift; read-only permissions prevent accidental writes. This is
not a security boundary against the operator who owns the files. A source pin
does not migrate validators or confer release/budget authority.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

FILES=('Dockerfile.web','LICENSE','THIRD_PARTY_NOTICES.md',
       'team-delivery-kit/docker_grouping.py','scripts/hermes_s1_worker.py',
       'scripts/prepare_hermes_project.py','scripts/prepare_hermes_networks.py',
       'scripts/bootstrap_hermes_branch.py','scripts/enable_hermes_provider.py',
       'scripts/run_hermes_runtime.py','scripts/initialize_provider_meter.py','scripts/prepare_hermes_launchagent.py',
       'scripts/requirements-hermes-agent.txt','examples/python-http/compose.provider.yml')
TREES=('src/fabriquinha/','examples/python-http/bootstrap/')
MANIFEST='source-manifest.json'
MAX_FILE=5*1024*1024
MAX_TOTAL=16*1024*1024


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
def digest(value):return hashlib.sha256(encoded(value)).hexdigest()


def selected(name):
    path=PurePosixPath(name)
    return (isinstance(name,str) and str(path)==name and not path.is_absolute()
        and not any(part in ('.','..','__pycache__') or part.startswith('.') for part in path.parts)
        and not any(ord(char)<32 or ord(char)==127 for char in name)
        and (name in FILES or any(name.startswith(prefix) for prefix in TREES)))


def inventory(names):
    if (not 1<=len(names)<=1024 or any(not selected(name) for name in names)
            or not set(FILES)<=set(names) or any(not any(name.startswith(prefix) for name in names) for prefix in TREES)):
        raise ValueError('closed runtime contents with required operator inputs expected')


def git(checkout,*args):
    try:return subprocess.check_output(['git','-C',str(checkout),*args],stderr=subprocess.DEVNULL,timeout=30)
    except (subprocess.SubprocessError,OSError):raise ValueError('Git revision or source objects unavailable') from None


def freeze(checkout,destination,revision):
    if not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{40}',revision):
        raise ValueError('explicit full Git commit required; resolve aliases before export')
    checkout=Path(checkout).resolve();destination=Path(destination)
    if destination.is_symlink() or destination.exists():raise ValueError('fresh export required; existing source is preserved')
    destination=destination.resolve()
    if git(checkout,'rev-parse','--show-toplevel').decode().strip()!=str(checkout):
        raise ValueError('source checkout root required')
    if git(checkout,'cat-file','-t',revision).strip()!=b'commit':raise ValueError('Git commit required')
    if destination.is_relative_to(checkout):
        ignored=subprocess.run(['git','-C',str(checkout),'check-ignore','--quiet',str(destination)],capture_output=True,timeout=30)
        if ignored.returncode:raise ValueError('source export inside checkout must use a Git-ignored private root')
    entries=git(checkout,'ls-tree','-rz','--full-tree',revision,'--',*FILES,*(name.rstrip('/') for name in TREES)).split(b'\0')
    blobs={};total=0
    for entry in filter(None,entries):
        metadata,raw_name=entry.split(b'\t',1);mode,kind,oid=metadata.decode().split();name=raw_name.decode()
        if not selected(name) or mode not in ('100644','100755') or kind!='blob':
            raise ValueError('regular tracked runtime files required; no symlinks or nested repositories')
        size=int(git(checkout,'cat-file','-s',oid));total+=size
        if size>MAX_FILE or total>MAX_TOTAL:raise ValueError('bounded source export required')
        blobs[name]=git(checkout,'cat-file','blob',oid)
    inventory(blobs)
    manifest=dict(version=1,commit=revision,files={name:hashlib.sha256(data).hexdigest() for name,data in sorted(blobs.items())})
    # All Git data is checked before creating anything. An interrupted export
    # stays visible and must never be mistaken for an already verified source.
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination.mkdir(mode=0o700)
    for name,data in {**blobs,MANIFEST:encoded(manifest)}.items():
        path=destination/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        path.chmod(0o400)
    for directory,_,_ in os.walk(destination,topdown=False):Path(directory).chmod(0o500)
    result=verify(destination,digest(manifest))
    return {**result,'path':str(destination),'model_calls':0,'delivery_approval':False}


def verify(root,expected):
    if not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected):raise ValueError('external source digest required')
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('regular frozen source directory required')
    path=root/MANIFEST
    if path.is_symlink() or not path.is_file() or path.stat().st_size>256*1024:
        raise ValueError('bounded regular source manifest required')
    manifest=json.loads(path.read_bytes())
    if (not isinstance(manifest,dict) or set(manifest)!={'version','commit','files'}
            or type(manifest['version']) is not int or manifest['version']!=1
            or not isinstance(manifest['commit'],str) or not re.fullmatch('[a-f0-9]{40}',manifest['commit'])
            or not isinstance(manifest['files'],dict)):
        raise ValueError('closed source manifest required')
    if digest(manifest)!=expected:raise ValueError('source manifest digest changed')
    inventory(manifest['files'])
    if any(not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value) for value in manifest['files'].values()):
        raise ValueError('source content hashes required')
    names=set();total=0
    for directory,dirs,files in os.walk(root,followlinks=False):
        folder=Path(directory)
        if folder.stat().st_mode&0o277:raise ValueError('private read-only source directories required')
        for name in dirs:
            child=folder/name
            if child.is_symlink():raise ValueError('source symlink directory refused')
            relative=child.relative_to(root).as_posix()+'/'
            if not any(item.startswith(relative) for item in manifest['files']):raise ValueError('source contents changed')
        for name in files:
            child=folder/name;info=child.lstat();relative=child.relative_to(root).as_posix()
            if not stat.S_ISREG(info.st_mode):raise ValueError('regular source files required')
            if info.st_mode&0o377:raise ValueError('private read-only source files required')
            if info.st_size>MAX_FILE:raise ValueError('bounded source content required')
            total+=info.st_size
            if total>MAX_TOTAL:raise ValueError('bounded source contents required')
            if relative==MANIFEST:continue
            names.add(relative)
            if relative not in manifest['files']:raise ValueError('source contents changed')
            if hashlib.sha256(child.read_bytes()).hexdigest()!=manifest['files'][relative]:raise ValueError('source content changed: '+relative)
    if names!=set(manifest['files']):raise ValueError('source contents changed')
    return dict(verified=True,commit=manifest['commit'],source_digest=expected,files=len(names))


def environment():
    """Optional managed-source fence; older qualification entry points remain explicit."""
    expected=os.environ.get('FABRIQUINHA_SOURCE_DIGEST')
    if expected is not None:return verify(Path(__file__).resolve().parents[2],expected)


def main():
    parser=argparse.ArgumentParser(description=__doc__);operations=parser.add_subparsers(dest='operation',required=True)
    export=operations.add_parser('freeze');export.add_argument('--checkout',type=Path,required=True)
    export.add_argument('--destination',type=Path,required=True);export.add_argument('--revision',required=True)
    check=operations.add_parser('verify');check.add_argument('--source',type=Path,required=True);check.add_argument('--expect-source',required=True)
    args=parser.parse_args()
    value=freeze(args.checkout,args.destination,args.revision) if args.operation=='freeze' else verify(args.source,args.expect_source)
    print(json.dumps(value,indent=2))


if __name__=='__main__':main()
