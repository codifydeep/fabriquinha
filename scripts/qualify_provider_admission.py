"""Native pre-claim provider wait, no model/Docker; spawn callback is programmed."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_delivery import create_trial
from fabriquinha.kanban_lane import native
from fabriquinha.runtime import provider_claim_guard
from fabriquinha.effects import write_json


def qualify(root,upstream,image):
    source,_=create_trial(root,upstream,image,namespace='delivery-kit-provider-admission')
    kb,kbc,dispatch=native();spawned=[]
    with kbc.connect_closing() as conn:
        fixed=kb.create_task(conn,title='Programmed fixed integration',assignee='flow-author',
            body=json.dumps(dict(version=1,kind='integration',release='native-flow',inputs={})),
            workspace_kind='dir',workspace_path=str(root/'work/implementation'),completion_contract='local-only')
        def spawn(task,workspace,**kw):spawned.append(task.id);return None
        original=dispatch.check_respawn_guard
        for _ in range(3):
            with provider_claim_guard(dispatch,conn,ready=False):
                dispatch.dispatch_once(conn,spawn_fn=spawn,max_spawn=2,max_in_progress=2,reconcile_orphans=False)
        assert spawned==[fixed],spawned
        assert conn.execute('SELECT count(*) FROM task_runs WHERE task_id=?',(source,)).fetchone()[0]==0
        assert kb.get_task(conn,source).status=='ready'
        assert dispatch.check_respawn_guard is original
        task=kb.get_task(conn,fixed)
        assert kb.complete_task(conn,fixed,summary='Programmed callback only; not deployment evidence',expected_run_id=task.current_run_id)
        with provider_claim_guard(dispatch,conn,ready=True):
            dispatch.dispatch_once(conn,spawn_fn=spawn,max_spawn=1,max_in_progress=2,reconcile_orphans=False)
        assert spawned==[fixed,source],spawned
        assert conn.execute('SELECT count(*) FROM task_runs WHERE task_id=?',(source,)).fetchone()[0]==1
    result=dict(no_model_runs_while_held=True,fixed_integration_admitted=True,
        availability_resumes_once=True,model_calls=0,delivery_approval=False,spawn_callback_programmed=True)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','upstream'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--image',required=True);a=p.parse_args()
    print(json.dumps(qualify(a.root.resolve(),a.upstream.resolve(),a.image),indent=2))
