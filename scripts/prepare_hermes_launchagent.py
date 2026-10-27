"""Render a macOS launchd job for the existing foreground runtime, without loading it.

No custom supervisor, model enablement or resume. A configuration error exits
visibly; only a crash is restarted, with launchd throttling. Stop after draining.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_hermes_runtime import command


def prepare(source,expected,python,root,upstream):
    command(source,expected,python,root,upstream,'serve')
    source=Path(source).absolute();python=Path(python).absolute();root=Path(root).resolve();upstream=Path(upstream).resolve()
    project=json.loads((root/'project.json').read_bytes())
    namespace=project['namespace']
    if not re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace):raise ValueError('owned delivery namespace required')
    control=json.loads((root/'control.json').read_bytes())
    if control.get('paused') is not True or control.get('error'):raise ValueError('prepare supervision while paused')
    policy=root/'provider-policy.json'
    if not project.get('qualification') and (not policy.is_file() or json.loads(policy.read_bytes()).get('enabled') is not False):
        raise ValueError('disabled provider required during installation')
    folder=root/'private/operations';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if folder.is_symlink() or folder.stat().st_mode&0o077:raise ValueError('private operations directory required')
    target=folder/'dispatcher.plist'
    value=dict(Label='ai.fabriquinha.'+namespace,ProgramArguments=[str(python),'-B',str(source/'scripts/run_hermes_runtime.py'),
        'serve','--source',str(source),'--expect-source',expected,'--python',str(python),
        '--root',str(root),'--upstream',str(upstream)],WorkingDirectory=str(root),
        EnvironmentVariables=dict(PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
            HOME=str(Path.home()),PYTHONNOUSERSITE='1',PYTHONSAFEPATH='1'),
        RunAtLoad=True,KeepAlive=dict(Crashed=True),ThrottleInterval=60,
        SoftResourceLimits=dict(Core=0),HardResourceLimits=dict(Core=0),
        ProcessType='Background',AbandonProcessGroup=True,ExitTimeOut=30,Umask=0o077,
        StandardOutPath=str(folder/'dispatcher.stdout.log'),StandardErrorPath=str(folder/'dispatcher.stderr.log'))
    # Exclusive creation: a new source revision requires an explicit reviewed
    # service replacement, never silent rewriting of a loaded launchd job.
    with target.open('xb') as stream:
        target.chmod(0o600);plistlib.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    return dict(prepared=True,label=value['Label'],plist=str(target),loaded=False,model_calls=0,dispatch_resumed=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--expect-source',required=True)
    parser.add_argument('--python',type=Path,required=True);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.source,args.expect_source,args.python,args.root,args.upstream),indent=2))
