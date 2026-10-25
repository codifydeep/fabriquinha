"""Run fixed isolated CI, never publish a GitHub status or enable a model.

Controller CLI only. Head/base are exact authenticated Git objects, not a shell
command; keep the private installation/root outside product workspaces.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.executor import Runner
from fabriquinha.publication import LocalCI,Repository
from fabriquinha.runtime import Runtime


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--head',required=True);parser.add_argument('--base',required=True)
    parser.add_argument('--stage',choices=('proposal','integrated'),required=True);args=parser.parse_args()
    runtime=Runtime(args.root,args.upstream)
    if not runtime.project.delivery_roles:raise ValueError('explicit reviewed integration role required')
    actor=runtime.project.delivery_roles['integration']
    repository=Repository(runtime.project,runtime.store,assignee=actor)
    ci=LocalCI(runtime.project,runtime.store,repository,Runner(runtime.project,runtime.store))
    receipt=ci.validate(args.head,args.base,stage=args.stage)
    result=runtime.store.receipt(receipt,kind='ci_validation')['payload']
    print(json.dumps(dict(receipt=receipt,**result),indent=2))
    raise SystemExit(0 if result['conclusion']=='success' else 1)
