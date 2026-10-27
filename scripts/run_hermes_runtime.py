"""Run the existing native CLI from a verified export; no extra service manager.

serve stays in the foreground and respects the durable pause. Use the host's
normal service manager if desired. Starting the relay, enabling inference,
resuming dispatch and approving business scope remain separate operations.
"""
import argparse
import math
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.source import verify

OPERATIONS=('serve','status','doctor','pause','resume','costs','configure-acceptance')


def command(source,expected,python,root,upstream,operation,*,episode=None,interval=15,validation=None):
    if (operation not in OPERATIONS or type(interval) not in (int,float) or not math.isfinite(interval)
            or not 0.1<=interval<=60 or interval!=15 and operation!='serve'
            or operation=='resume' and (not isinstance(episode,str) or not re.fullmatch('[a-f0-9]{32}',episode))
            or operation=='configure-acceptance' and (not isinstance(validation,str) or not re.fullmatch('[a-f0-9]{64}',validation))
            or operation!='configure-acceptance' and validation is not None
            or operation!='resume' and episode is not None):
        raise ValueError('fixed operation, bounded interval and explicit resume episode required')
    source=Path(source).absolute();verify(source,expected)
    python=Path(python).absolute();root=Path(root).resolve();upstream=Path(upstream).resolve()
    if not python.is_file() or not os.access(python,os.X_OK) or not root.is_dir() or not upstream.is_dir():
        raise ValueError('existing SDK Python, installation and pinned upstream required')
    args=[str(python),'-B','-m','fabriquinha.runtime',operation,'--root',str(root),'--upstream',str(upstream)]
    if operation=='serve':args+=['--interval',str(interval)]
    if operation=='resume':args+=['--expect-pause',episode]
    if operation=='configure-acceptance':args+=['--expect-validation',validation]
    env={**os.environ,'PYTHONPATH':str(source/'src'),'PYTHONDONTWRITEBYTECODE':'1',
        'PYTHONSAFEPATH':'1','PYTHONNOUSERSITE':'1','FABRIQUINHA_SOURCE_DIGEST':expected}
    return args,env


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=OPERATIONS)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--expect-source',required=True)
    parser.add_argument('--python',type=Path,required=True);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True);parser.add_argument('--expect-pause')
    parser.add_argument('--expect-validation')
    parser.add_argument('--interval',type=float,default=15)
    args=parser.parse_args()
    command_args,env=command(args.source,args.expect_source,args.python,args.root,args.upstream,args.operation,
        episode=args.expect_pause,interval=args.interval,validation=args.expect_validation)
    # exec retains the PID and native Owner lock semantics; no PID file or
    # detached launcher can report a dead process as a healthy controller.
    os.execve(command_args[0],command_args,env)


if __name__=='__main__':main()
