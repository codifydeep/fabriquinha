"""Run fixed isolated CI; optional approved status publication, never a model.

Controller CLI only. Head/base are exact authenticated Git objects, not a shell
command; keep the private installation/root outside product workspaces.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.publication import GitHub,LocalCI,LocalStatus,Repository
from fabriquinha.runtime import Runtime,IntegrationRunner


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--head',required=True);parser.add_argument('--base',required=True)
    parser.add_argument('--stage',choices=('proposal','integrated'),required=True)
    parser.add_argument('--publish',action='store_true',help='Publish only the explicitly configured local CI context')
    args=parser.parse_args()
    runtime=Runtime(args.root,args.upstream)
    if not runtime.project.delivery_roles:raise ValueError('explicit reviewed integration role required')
    actor=runtime.project.delivery_roles['integration']
    repository=Repository(runtime.project,runtime.store,assignee=actor)
    runner=IntegrationRunner(runtime.project,runtime.store)
    if args.publish:
        receipt=LocalStatus(runtime.project,runtime.store,repository,GitHub(runtime.project,actor),runner).publish(
            args.head,args.base,stage=args.stage)['receipt']
    else:receipt=LocalCI(runtime.project,runtime.store,repository,runner).validate(args.head,args.base,stage=args.stage)
    result=runtime.store.receipt(receipt,kind='ci_validation')['payload']
    print(json.dumps(dict(receipt=receipt,**result),indent=2))
    raise SystemExit(0 if result['conclusion']=='success' else 1)
