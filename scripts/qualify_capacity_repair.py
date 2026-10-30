"""Isolated additive capacity repair and native succession proof. No model or delivery.

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
    from fabriquinha.capacity_repair import admit
    with api.connect_closing() as conn:
        before={row['id']:dict(row) for row in conn.execute('SELECT * FROM tasks')}
    from unittest.mock import patch
    from fabriquinha.effects import write_json as real_write
    def interrupted(path,value):
        if path==root/'installation.json':raise OSError('programmed crash after durable admission')
        return real_write(path,value)
    with patch('fabriquinha.capacity_repair.write_json',side_effect=interrupted):
        try:admit(runtime,request)
        except OSError:pass
        else:raise AssertionError('expected installation interruption')
    admitted=admit(runtime,request);assert admit(runtime,request)==admitted
    try:admit(runtime,{**request,'source_run':0})
    except ValueError:pass
    else:raise AssertionError('changed admission accepted')
    with api.connect_closing() as conn:
        anchor=kb.get_task(conn,request['release']);spec=releases.specification(conn,anchor)
        key,graph=releases.materialize(conn,anchor,spec,None)
        assert releases.materialize(conn,anchor,spec,None)==(key,graph)
        assert len(graph['items'])==2 and graph['assisted'] is True
        for ident,row in before.items():assert dict(conn.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone())==row
        first=graph['items'][0]['cards']['tests'];second=graph['items'][1]['cards']['tests']
        assert graph['items'][0]['cards']['integration']['id'] in second['parents']
        assert kb.get_task(conn,first['id']).status=='ready'
        assert kb.latest_run(conn,first['id']) is None
        assert releases.graph_path(anchor,first['body']).exists()
        assert first['id'] not in before
    result=dict(passed=True,model_calls=0,delivery_approval=False,predecessors_unchanged=True,
        same_approved_plan=True,dependent_increments=True,idempotent_successors=True,assisted=True)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('root','source','upstream','request'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();print(json.dumps(qualify(a.root.absolute(),a.source.absolute(),a.upstream.absolute(),json.loads(a.request.read_bytes())),indent=2))
