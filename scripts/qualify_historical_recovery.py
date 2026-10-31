"""Isolated accepted history and same-card integration recovery proof. No model or delivery.

Clones a private accepted board and copies immutable artifacts.
Never dispatches a worker or changes the source installation.
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from qualify_hermes_s1 import prepare
from fabriquinha.artifacts import Store
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.intake import Intake,DraftActivity,DraftTools
from fabriquinha.kanban_lane import native
from fabriquinha.releases import Releases


def qualify(root,source,upstream,request):
    if root.exists():raise ValueError('fresh private qualification root required')
    root.mkdir(parents=True,mode=0o700);(root/'home').mkdir()
    for name in ('project.json','installation.json'):shutil.copyfile(source/name,root/name)
    with sqlite3.connect('file:'+str(source/'home/kanban.db')+'?mode=ro',uri=True) as old, sqlite3.connect(root/'home/kanban.db') as new:
        old.backup(new)
    store=Store(root/'private')
    for category in ('objects','receipts'):
        for entry in (source/'private'/category).iterdir():
            if not entry.name.startswith('.'):
                target=store.root/category/entry.name
                if entry.is_dir():shutil.copytree(entry,target)
                else:shutil.copy2(entry,target)
    prepare(root,upstream);project=Project.parse(json.loads((root/'project.json').read_bytes()))
    from hermes_cli.profiles import create_profile
    for role in set(project.reviewers)|set(project.coordination_roles.values()):
        create_profile(role,no_skills=True,description='Scripted isolated maintenance proof')
    board=Board(project);intake=Intake(project,store,board);kb,api,_=native()
    from fabriquinha.qa_recovery import reconcile,origin
    shutil.copytree(source/'private/releases',store.root/'releases',dirs_exist_ok=True)
    releases=Releases(project,store,board,intake)
    runtime=SimpleNamespace(releases=releases,intake=intake,root=root,control=SimpleNamespace(read=lambda:{'paused':True}))
    from fabriquinha.historical import recover,AcceptedHistory
    from fabriquinha.quality import Quality,preview_evidence
    from fabriquinha.executor import validation_files
    with api.connect_closing() as conn:
        task=kb.get_task(conn,request['task']);body=json.loads(task.body)
        before=dict(conn.execute('SELECT * FROM tasks WHERE id=?',(task.id,)).fetchone())
    previous=intake.previous(body['release'])
    accepted=store.receipt(previous['acceptance'],kind='release_acceptance')['payload']
    # Validate the nested maintenance provenance and exact rollback under the live installation.
    anchor_id=body['release_anchor']
    with api.connect_closing() as conn:
        anchor=kb.get_task(conn,anchor_id)
        graph=store.receipt(json.loads(releases.graph_path(anchor,body).read_bytes())['receipt'],kind='release_graph')['payload']
    seed=store.receipt(graph['seed'],kind='release_seed')['payload']
    rollback=releases.accepted_rollback(body['release'],seed);assert rollback
    historical=AcceptedHistory(project,store,previous['acceptance'])
    assert validation_files(project,historical)[0]!=validation_files(project,store)[0]
    for method,args in [('capture',('anything',)),('record',('x',{},{})),('checkout',('x','y'))]:
        try:getattr(historical,method)(*args)
        except ValueError:pass
        else:raise AssertionError('historical view writable')
    # Current evidence remains current-only; an old report may not satisfy a new gate.
    final=accepted['packages'][-1];qa=store.receipt(final['qa'],kind='release_evidence')['payload']
    artifact=store.receipt(qa['artifact'],kind='artifact')['payload'];review=store.receipt(artifact['review'],kind='delivery_review')['payload']
    green=store.receipt(review['green'],kind='green')['payload'];job=store.receipt(green['job'],kind='suite_job')['payload']
    try:preview_evidence(project,store,job,green['snapshot'],'green')
    except ValueError:pass
    else:raise AssertionError('old validation accepted for new execution')
    result1=recover(runtime,request);assert recover(runtime,request)==result1
    with api.connect_closing() as conn:
        after=dict(conn.execute('SELECT * FROM tasks WHERE id=?',(task.id,)).fetchone())
    assert after['status']=='ready'
    for k in before:
        if k!='status':assert after[k]==before[k],k
    result=dict(passed=True,model_calls=0,delivery_approval=False,assisted=True,
        historical_provenance=True,rollback_selection=True,current_gate_rejects_old_bundle=True,
        read_only_history=True,native_resume_once=True,counters_and_delivery_unchanged=True)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','source','upstream','request'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();print(json.dumps(qualify(a.root.absolute(),a.source.absolute(),a.upstream.absolute(),json.loads(a.request.read_bytes())),indent=2))
