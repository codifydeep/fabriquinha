"""Explicit controller GitHub identity for native Hermes acceptance.

Profiles receive only a directory pointer, never a token. The directory remains
outside the installation and is never mounted in execution/validation containers.
This is operator provisioning under maintenance, not an agent tool or approval.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .config import Project
from .effects import write_json


def profiles(project):
    actor=(project.delivery_roles or {}).get('integration')
    if project.qualification or not actor or not project.local_ci:
        raise ValueError('real delivery project with explicit CI publisher required')
    return sorted({actor,*project.reviewers_for(actor)})


def directory(root,value):
    path=Path(value)
    if (not path.is_absolute() or path.resolve()!=path or not path.is_dir()
            or path.is_relative_to(Path(root).resolve())
            or any(ord(c)<32 or ord(c)==127 or c in '$\\' for c in str(path))):
        raise ValueError('existing canonical GitHub config directory outside installation required')
    return str(path)


def binding(project,root,value):
    return dict(version=1,project=project.fingerprint(),publisher=project.local_ci['publisher'],
        hostname='github.com',config_dir=directory(root,value),profiles=profiles(project))


def read(root):
    root=Path(root);path=root/'github-auth.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>8192 or path.stat().st_mode&0o077:
        raise ValueError('private GitHub identity binding required')
    from .profile_policy import unique
    value=json.loads(path.read_bytes(),object_pairs_hook=unique)
    project=Project.parse(json.loads((root/'project.json').read_bytes(),object_pairs_hook=unique))
    if value!=binding(project,root,value['config_dir']):raise ValueError('GitHub identity binding drift')
    return value


def metadata(value):
    # JSON quoting is dotenv-compatible here, including paths containing spaces.
    return 'GH_CONFIG_DIR='+json.dumps(value['config_dir'])+'\nGH_HOST="github.com"\n'


def env_allowed(root,name,content):
    active=[line for line in content.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not active:return True
    try:
        value=read(root)
        return name in value['profiles'] and '\n'.join(active)+'\n'==metadata(value)
    except (ValueError,KeyError,TypeError,OSError,RecursionError):return False


def report(project,root):
    if project.qualification or not project.local_ci or not project.delivery_roles:return dict(ready=True,errors=[])
    try:
        value=read(root)
        if value['project']!=project.fingerprint():raise ValueError('project drift')
        for name in value['profiles']:
            path=Path(root)/'home/profiles'/name/'.env'
            if (path.is_symlink() or not path.is_file() or path.stat().st_size>16384
                    or path.stat().st_mode&0o077 or path.read_text()!=metadata(value)):
                raise ValueError('profile GitHub metadata drift')
        return dict(ready=True,errors=[],profiles=value['profiles'],publisher=value['publisher'])
    except (ValueError,KeyError,TypeError,OSError,RecursionError):
        return dict(ready=False,errors=['GitHubIdentityUnqualified'])


def configure(runtime,config_dir):
    root,project=runtime.root,runtime.project
    value=binding(project,root,config_dir)
    with runtime.control.lock():
        if not runtime.control.read()['paused'] or not runtime.status()['control']['drained']:
            raise ValueError('paused drained installation required for GitHub provisioning')
        target=root/'github-auth.json'
        if target.exists() or target.is_symlink():
            if read(root)!=value:raise ValueError('existing identity binding is preserved; explicit migration required')
        homes=[]
        for name in value['profiles']:
            home=root/'home/profiles'/name;env=home/'.env'
            if (home.resolve()!=home or not home.is_dir() or env.is_symlink()
                    or env.exists() and (not env.is_file() or env.stat().st_size>16384
                        or env.stat().st_mode&0o077 or not env_allowed(root,name,env.read_text()))):
                raise ValueError('preserve unqualified profile environment; do not overwrite credentials')
            homes.append(env)
        # Only a read-only account query. No credential file is read/copied here.
        env={key:item for key,item in os.environ.items()
             if key not in ('GH_TOKEN','GITHUB_TOKEN','GH_CONFIG_DIR','GH_HOST','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN')}
        env.update(GH_CONFIG_DIR=value['config_dir'],GH_HOST='github.com',GH_PROMPT_DISABLED='1')
        try:
            response=subprocess.run(['gh','api','--hostname','github.com','user'],env=env,
                capture_output=True,check=True,timeout=30)
            if json.loads(response.stdout).get('login','').lower()!=value['publisher'].lower():
                raise ValueError('configured GitHub account differs from CI publisher')
        except (subprocess.SubprocessError,OSError,KeyError,TypeError):
            raise ValueError('configured GitHub identity unavailable; no credential fallback') from None
        # Write the binding first. Interrupted provisioning remains unready; an
        # identical rerun finishes metadata without changing the identity.
        write_json(target,value)
        for path in homes:
            fd,name=tempfile.mkstemp(prefix='.github-env-',dir=path.parent)
            temporary=Path(name)
            try:
                with os.fdopen(fd,'w') as stream:
                    stream.write(metadata(value));stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,path)
            finally:
                if temporary.exists():temporary.unlink()
        result=report(project,root)
        if not result['ready']:raise ValueError('GitHub identity metadata not ready; keep paused')
        return {**result,'model_calls':0,'github_mutations':0,'tokens_copied':False,'delivery_approval':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--config-dir',type=Path,required=True)
    args=parser.parse_args()
    from .runtime import Runtime
    print(json.dumps(configure(Runtime(args.root,args.upstream),args.config_dir),indent=2))
