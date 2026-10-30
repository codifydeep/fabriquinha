"""Isolated native maintenance replan/review restart proof. No model or delivery.

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
    from fabriquinha.maintenance_replan import admit
    shutil.copytree(source/'private/releases',store.root/'releases',dirs_exist_ok=True)
    releases=Releases(project,store,board,intake)
    runtime=SimpleNamespace(releases=releases,intake=intake)
    with api.connect_closing() as conn:
        anchor=kb.get_task(conn,request['release'])
        before={r['id']:dict(r) for r in conn.execute('SELECT * FROM tasks')}
    from unittest.mock import patch
    with patch('fabriquinha.maintenance_replan.write_json',side_effect=OSError('programmed crash before pointer')):
        try:admit(runtime,request)
        except OSError:pass
        else:raise AssertionError('crash injection did not execute')
    first=admit(runtime,request)
    assert admit(runtime,request)==first
    with api.connect_closing() as conn:
        assert releases.specification(conn,anchor) is None
        task=kb.claim_task(conn,first['plan']);assert task
    try:admit(runtime,request)
    except ValueError as error:assert 'settle all workers' in str(error)
    else:raise AssertionError('active worker was not fenced')
    run=board.current(task.id,task.current_run_id);tools=DraftTools(DraftActivity(project,store,board,run))
    evidence=tools.evidence();assert evidence['replan']
    paths=evidence['maintenance']['paths']
    doc=dict(architecture='Preserve application and framework; replace only duplicated observer setup in authorized tests.',
        observability='Preserve shared live error list; require late browser-error negative control.',
        tasks=[dict(id='observer-maintenance',title='Repair observer fixtures',owner='backend_data',depends_on=[],
            criteria=[c['id'] for c in evidence['approved_brief']['criteria']],acceptance='Edit only '+', '.join(paths)+'; preserve assertions, manifests and product. Fresh full suites, independent freeze and negative controls.')])
    tools.submit(doc)
    with api.connect_closing() as conn:task=kb.claim_review_task(conn,task.id);assert task
    review=board.current(task.id,task.current_run_id)
    assert review.actor==project.technical_roles['cto'] and review.actor!=run.actor
    DraftTools(DraftActivity(project,store,board,review)).review(dict(decision='approve',reason='Scripted isolated protocol validation only.',findings=[]))
    with api.connect_closing() as conn:
        spec=releases.specification(conn,anchor);assert spec['maintenance_replan']==first
        facts=evidence['maintenance'];repo=SimpleNamespace(base=lambda:facts['commit'],snapshot=lambda c:facts['snapshot'])
        graph_id,graph=releases.materialize(conn,anchor,spec,lambda *a:(repo,None))
        assert releases.materialize(conn,anchor,spec,lambda *a:(repo,None))[0]==graph_id
        for item in graph['items']:
            for card in item['cards'].values():
                assert card['id'] not in before
                assert str(root/'work') in card['workspace']
                assert releases.graph_path(anchor,card['body']).name=='maintenance-graph-'+first['plan']+'.json'
        for task_id,original in before.items():
            assert dict(conn.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone())==original
    result=dict(passed=True,programmed_roles=True,model_calls=0,delivery_approval=False,
        native_independent_cto_review=True,idempotent_restart=True,predecessors_unchanged=True,separate_workspaces=True,crash_before_pointer=True,active_worker_rejected=True)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','source','upstream','request'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();print(json.dumps(qualify(a.root.absolute(),a.source.absolute(),a.upstream.absolute(),json.loads(a.request.read_bytes())),indent=2))
