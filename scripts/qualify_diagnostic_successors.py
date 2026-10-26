"""Native Kanban handoff identity proof; programmed decisions, no model/Docker."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_s1 import prepare
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Run,Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.kanban_lane import native
from fabriquinha.recovery import Recovery


def qualify(root,upstream):
    if root.exists():raise ValueError('fresh private root required')
    root.mkdir(parents=True,mode=0o700);prepare(root,upstream);kb,api,_=native()
    from hermes_cli.profiles import create_profile
    for name in ('succ-lead','succ-cto'):create_profile(name,no_skills=True,description='Offline native handoff fixture')
    project=Project.parse(dict(version=1,namespace='delivery-kit-hermes-succession',repository='https://github.com/example/qualification',
        branch='release/fixture',validation_image='sha256:'+'a'*64,tests_dir='tests',qualification=True,
        reviewers={'succ-lead':'succ-cto','succ-cto':'succ-lead'},technical_roles={'lead':'succ-lead','cto':'succ-cto'}))
    store=Store(root/'private');work=root/'work';work.mkdir();(work/'app.py').write_text('VALUE = 1\n');snapshot=store.capture(work)
    recovery=Recovery(project,store,Board(project))
    def complete(conn,task,incident,action):
        claim=kb.claim_task(conn,task);assert claim
        current=kb.get_task(conn,task);body=json.loads(current.body)
        run=Run(task,claim.current_run_id,current.assignee,'diagnostic',False,current.assignee,body['release'],digest(body))
        receipt=store.record('diagnostic_decision',run.binding(),dict(project=project.fingerprint(),incident=incident,action=action,
            experiment=None,verdict=dict(decision='changes',reason='Programmed diagnostic identity fixture',findings=[dict(path='app.py',line=1,detail='Fixture technical input')])))
        assert kb.complete_task(conn,task,summary='Programmed '+action,metadata={'diagnosis':receipt},expected_run_id=claim.current_run_id)
        return receipt
    def incident(conn,label):
        body=dict(version=1,kind='tests',release=label,inputs={})
        source=kb.create_task(conn,title='Offline source '+label,assignee='succ-lead',body=json.dumps(body),workspace_kind='dir',
            workspace_path=str(work),completion_contract='local-only')
        claim=kb.claim_task(conn,source);assert claim
        assert kb.block_task(conn,source,reason='Programmed source failure',expected_run_id=claim.current_run_id)
        event=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(source,)).fetchone()['id']
        scope=Run(source,claim.current_run_id,'succ-lead','tests',False,'succ-lead',label,digest(body))
        return store.record('incident',scope.binding(),dict(project=project.fingerprint(),source=source,source_run=claim.current_run_id,
            block_event=event,snapshot=snapshot,cause=digest([source,event]),failure='fixture',category='worker_activity',resume_allowed=True))
    with api.connect_closing() as conn:
        key=incident(conn,'held-then-new-input')
        old=recovery.create(conn,key,'cto');held=complete(conn,old,key,'hold')
        lead=recovery.create(conn,key,'lead',previous=old);complete(conn,lead,key,'escalate')
        recovery.apply(conn,kb.get_task(conn,lead))
        successors=[task for task in recovery.cards(conn) if json.loads(task.body).get('escalated_from')==lead]
        assert len(successors)==1 and successors[0].id!=old and successors[0].status=='ready'
        fresh=Recovery(project,store,Board(project));fresh.apply(conn,kb.get_task(conn,lead));fresh.apply(conn,kb.get_task(conn,lead))
        assert len([task for task in fresh.cards(conn) if json.loads(task.body).get('escalated_from')==lead])==1
        assert kb.latest_run(conn,old).metadata['diagnosis']==held
        assert next(i for i in fresh.status(conn) if i['source']==store.receipt(key)['payload']['source'])['diagnostic']==successors[0].id
        complete(conn,successors[0].id,key,'hold')
        # A pre-upgrade key with the SAME predecessor must still be reused.
        legacy_incident=incident(conn,'legacy-predecessor');prior=recovery.create(conn,legacy_incident,'lead');complete(conn,prior,legacy_incident,'escalate')
        record=store.receipt(legacy_incident);data=record['payload']
        body=dict(version=1,kind='diagnostic',release=record['binding']['release'],stage='cto',source=data['source'],source_run=data['source_run'],
            block_event=data['block_event'],cause=data['cause'],inputs={'incident':legacy_incident},escalated_from=prior)
        legacy=kb.create_task(conn,title='Legacy key fixture',assignee='succ-cto',body=json.dumps(body),workspace_kind='dir',
            workspace_path=str(store.tree(snapshot)),completion_contract='local-only',
            idempotency_key=digest([project.fingerprint(),data['source'],data['source_run'],data['block_event'],'diagnostic','cto']))
        assert legacy==fresh.create(conn,legacy_incident,'cto',previous=prior)
        complete(conn,legacy,legacy_incident,'hold')
        assert fresh.reconcile(conn,lambda *args,**kwargs:None)=={}
        assert len([t for t in fresh.cards(conn) if json.loads(t.body).get('escalated_from')==lead])==1
        assert not conn.execute('SELECT 1 FROM task_runs WHERE ended_at IS NULL').fetchone()
    result=dict(native_kanban=True,held_cto_receipt_preserved=True,new_predecessor_created_new_cto=True,
        restart_reused_same_successor=True,legacy_same_predecessor_reused=True,status_selects_current_successor=True,open_claims=0,model_calls=0,docker_jobs=0,
        programmed_decisions=True,delivery_approval=False,autonomous_delivery=False)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args();qualify(args.root.resolve(),args.upstream.resolve())
