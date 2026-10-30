"""Isolated native maintenance environment-succession restart proof. No model or delivery.

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
    from fabriquinha.maintenance_environment import admit
    shutil.copytree(source/'private/releases',store.root/'releases',dirs_exist_ok=True)
    for f in (source/'private/agents').glob('*/sandbox.json'):
        target=store.root/'agents'/f.parent.name/'sandbox.json';target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
    releases=Releases(project,store,board,intake);runtime=SimpleNamespace(releases=releases,intake=intake)
    with api.connect_closing() as conn:
        anchor=kb.get_task(conn,request['release']);old_spec=releases.specification(conn,anchor)
        before={r['id']:dict(r) for r in conn.execute('SELECT * FROM tasks')}
    from unittest.mock import patch
    with patch('fabriquinha.maintenance_environment.write_json',side_effect=OSError('programmed crash')):
        try:admit(runtime,request)
        except OSError:pass
        else:raise AssertionError('crash injection did not execute')
    first=admit(runtime,request);assert admit(runtime,request)==first
    try:admit(runtime,{**request,'diagnosis':'0'*64})
    except ValueError:pass
    else:raise AssertionError('different diagnosis silently admitted')
    with api.connect_closing() as conn:
        spec=releases.specification(conn,anchor);assert spec['review']==old_spec['review']
        from fabriquinha.maintenance import reviewed
        facts=reviewed(project,store,spec['review']);repo=SimpleNamespace(base=lambda:facts['commit'],snapshot=lambda c:facts['snapshot'])
        services=lambda *a:(repo,None)
        key,graph=releases.materialize(conn,anchor,spec,services)
        assert releases.materialize(conn,anchor,spec,services)[0]==key
        for card in graph['items'][0]['cards'].values():
            assert card['id'] not in before and str(root/'work') in card['workspace']
            assert releases.graph_path(anchor,card['body']).name=='maintenance-environment-'+first['receipt']+'.json'
        for ident,row in before.items():assert dict(conn.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone())==row
    result=dict(passed=True,programmed_roles=True,model_calls=0,delivery_approval=False,
        same_independent_plan=True,idempotent_restart=True,predecessors_unchanged=True,separate_workspaces=True,crash_before_pointer=True,changed_diagnosis_rejected=True)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','source','upstream','request'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();print(json.dumps(qualify(a.root.absolute(),a.source.absolute(),a.upstream.absolute(),json.loads(a.request.read_bytes())),indent=2))
