"""Isolated native maintenance deployed-QA-succession restart proof. No model or delivery.

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
    with api.connect_closing() as conn:
        anchor=kb.get_task(conn,request['release'])
        pointer=next(releases.folder(anchor).glob('maintenance-environment-*.json'))
        graph=store.receipt(json.loads(pointer.read_bytes())['receipt'],kind='release_graph')['payload']
        before={r['id']:dict(r) for r in conn.execute('SELECT * FROM tasks')}
        from unittest.mock import patch
        with patch('fabriquinha.qa_recovery.write_json',side_effect=OSError('programmed interruption')):
            try:reconcile(releases,conn,anchor,graph)
            except OSError:pass
            else:raise AssertionError('expected interruption')
        result=reconcile(releases,conn,anchor,graph)
        assert reconcile(releases,conn,anchor,graph)==result
        item=result['items'][-1];old=graph['items'][-1]
        assert item['cards']['tests']==old['cards']['tests'] and item['cards']['implementation']==old['cards']['implementation']
        new=item['cards']['integration'];assert new['id']!=old['cards']['integration']['id']
        assert kb.get_task(conn,new['id']).status=='review'
        task=kb.claim_review_task(conn,new['id']);assert task
        for ident,row in before.items():assert dict(conn.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone())==row
    run=board.current(task.id,task.current_run_id);prior=origin(project,store,run)
    assert prior.task==old['cards']['integration']['id'] and run.actor!=run.author
    from fabriquinha.deployment import Deployment
    from fabriquinha.quality import Quality
    recovery=store.receipt(result['qa_recovery'],kind='qa_recovery')['payload']
    artifact=store.receipt(recovery['artifact'],kind='artifact')['payload']
    deployment=Deployment(project,store,board,None)
    class ObservedPreflight(Exception):pass
    def observe(*args,**kwargs):raise ObservedPreflight()
    deployment.service=observe
    try:deployment.qa(run,recovery['rollout'],SimpleNamespace(remote_head=lambda branch:artifact['commit']))
    except ObservedPreflight:pass
    else:raise AssertionError('expected preflight before Docker or browser')
    quality=Quality(project,store,None,board)
    delivery=store.receipt(artifact['review'],kind='delivery_review')['payload']
    green=store.receipt(delivery['green'],kind='green')['payload']
    frozen=quality.frozen_plan(store.receipt(green['freeze'],kind='tests_frozen'))
    mutated=root/'unapproved';store.checkout(artifact['snapshot'],mutated)
    path=next((mutated/'tests').glob('acceptance_*.py'));path.write_text(path.read_text()+'\n# unapproved mutation\n')
    try:quality.protect(frozen['baseline'],store.capture(mutated),allow_revision=True)
    except ValueError:pass
    else:raise AssertionError('unapproved tests accepted')
    result=dict(passed=True,programmed_roles=True,model_calls=0,delivery_approval=False,
        reused_tests_and_delivery=True,independent_qa=True,crash_before_pointer=True,idempotent_restart=True,predecessors_unchanged=True,maintenance_preflight=True,unapproved_tests_rejected=True)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','source','upstream','request'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();print(json.dumps(qualify(a.root.absolute(),a.source.absolute(),a.upstream.absolute(),json.loads(a.request.read_bytes())),indent=2))
