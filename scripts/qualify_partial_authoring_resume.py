"""Offline copied-board proof. No dispatcher, worker, Docker or model calls."""
import argparse
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.authoring_recovery import resume_partial
from fabriquinha.effects import write_json
from fabriquinha.kanban_lane import native
from fabriquinha.runtime import Runtime
from fabriquinha.upstream_upgrade import manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args()
    source=args.backup.resolve();root=args.output.resolve()
    if root.exists() or root.is_relative_to(source):raise ValueError('fresh separate proof directory required')
    before=manifest(source)
    if not json.loads((source/'control.json').read_bytes())['paused']:raise ValueError('cold paused backup required')
    shutil.copytree(source,root)
    if manifest(root)!=before or manifest(source)!=before:raise ValueError('backup changed during copy')
    runtime=Runtime(root,args.upstream.resolve());kb,api,_=native()
    request=json.loads(args.request.read_bytes())
    with api.connect_closing() as conn:
        task=kb.get_task(conn,request['source']);work=Path(task.workspace_path)
        runs=conn.execute('SELECT count(*) FROM task_runs').fetchone()[0]
    files=manifest(work)
    graphs={p:p.read_bytes() for p in (runtime.store.root/'releases').glob('*/graph.json')}
    with patch('fabriquinha.authoring_recovery.environment',return_value={'qualification_fixture':True}):
        with patch.object(runtime,'pause_status',return_value={'drained':False}):
            try:resume_partial(runtime,request)
            except ValueError:pass
            else:raise AssertionError('active worker admitted')
        with patch.object(kb,'specify_triage_task',side_effect=RuntimeError('injected before native resume')):
            try:resume_partial(runtime,request)
            except RuntimeError as error:
                if str(error)!='injected before native resume':raise
            else:raise AssertionError('missing injected interruption')
        with patch.object(runtime.store,'capture',return_value='changed'):
            try:resume_partial(runtime,request)
            except ValueError:pass
            else:raise AssertionError('workspace drift admitted')
        result=resume_partial(runtime,request)
        assert resume_partial(runtime,request)==result
    with api.connect_closing() as conn:
        assert kb.get_task(conn,request['source']).status in ('todo','ready')
        assert conn.execute('SELECT count(*) FROM task_runs').fetchone()[0]==runs
    assert manifest(work)==files and all(p.read_bytes()==data for p,data in graphs.items())
    proof=dict(passed=True,model_calls=0,workers_started=0,same_card=True,
               workspace_unchanged=True,graph_unchanged=True,interrupted_resume=True,idempotent=True)
    write_json(root/'qualification.json',proof)
    print(json.dumps(proof,sort_keys=True))


if __name__=='__main__':main()
