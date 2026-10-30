"""Isolated native maintenance admission/review restart proof. No model or delivery.

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
    first=intake.start_maintenance(request)
    assert Intake(project,store,board).start_maintenance(request)==first
    with api.connect_closing() as conn:
        anchor=kb.get_task(conn,first['release'])
        plans=[r['id'] for r in conn.execute('SELECT id,body FROM tasks') if json.loads(r['body'] or '{}').get('anchor')==anchor.id]
        assert len(plans)==1
        task=kb.claim_task(conn,plans[0]);assert task
    run=board.current(task.id,task.current_run_id);tools=DraftTools(DraftActivity(project,store,board,run))
    evidence=tools.evidence();assert evidence['brief_authority']['status']=='maintenance_authorized'
    assert evidence['maintenance']['business_change'] is False
    doc=dict(architecture='Preserve deployed architecture. Only authorized shared browser observer helpers change.',
        observability='Preserve central browser errors; require a late-error negative control.',
        tasks=[dict(id='observer-maintenance',title='Repair delivered observer fixtures',owner='backend_data',depends_on=[],
            criteria=[c['id'] for c in evidence['approved_brief']['criteria']],acceptance='Keep every delivered behavior and case; replace only duplicate observer helpers and validate late errors.')])
    tools.submit(doc)
    with api.connect_closing() as conn:task=kb.claim_review_task(conn,task.id);assert task
    review=board.current(task.id,task.current_run_id);assert review.actor==project.technical_roles['cto'] and review.actor!=run.actor
    DraftTools(DraftActivity(project,store,board,review)).review(dict(decision='approve',reason='Scripted independent protocol test, not model judgment.',findings=[]))
    releases=Releases(project,store,board,intake)
    with api.connect_closing() as conn:
        spec=releases.specification(conn,anchor);assert spec
        facts=evidence['maintenance']
        repo=SimpleNamespace(base=lambda:facts['commit'],snapshot=lambda c:facts['snapshot'])
        services=lambda *args,**kwargs:(repo,None)
        graph_id,graph=releases.materialize(conn,anchor,spec,services)
        again=Releases(project,store,board,Intake(project,store,board)).materialize(conn,anchor,spec,services)
        assert again[0]==graph_id and len(graph['items'])==1
        cards=graph['items'][0]['cards'];assert all(c['body']['inputs']['maintenance_review']==spec['review'] for c in cards.values())
        assert len({c['id'] for c in cards.values()})==3
        assert kb.get_task(conn,anchor.id).status=='blocked'
    result=dict(passed=True,programmed_roles=True,model_calls=0,delivery_approval=False,
        native_independent_cto_review=True,idempotent_restart=True,one_graph=True,source_unchanged=True)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','source','upstream','request'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();print(json.dumps(qualify(a.root.absolute(),a.source.absolute(),a.upstream.absolute(),json.loads(a.request.read_bytes())),indent=2))
