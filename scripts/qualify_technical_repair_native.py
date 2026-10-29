"""Real Kanban successor/restart proof with programmed suite reports, no model.

Pair with qualify_technical_repair_jobs.py for actual isolated executor evidence.
Neither fixture qualifies autonomous agent judgment or a product delivery.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from qualify_hermes_s1 import prepare
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.kanban_lane import native
from fabriquinha.quality import Quality
from fabriquinha.repairs import Repairs
from fabriquinha.releases import Releases
from fabriquinha.technical_repair import validate_scope


def qualify(root,upstream):
    if root.exists():raise ValueError('fresh isolated root required')
    root.mkdir(parents=True,mode=0o700);prepare(root,upstream);kb,api,_=native()
    from hermes_cli.profiles import create_profile
    for name in ('author','lead','cto'):create_profile(name,no_skills=True,description='Programmed native repair qualification')
    project=Project.parse(dict(version=1,namespace='delivery-kit-test-repair-native',repository='https://github.com/example/qualification',
        branch='release/proof',validation_image='sha256:'+'a'*64,tests_dir='tests',reviewers={'author':'lead','lead':'cto'},
        technical_roles={'lead':'lead','cto':'cto'},qualification=True))
    store=Store(root/'private');work=root/'work';(work/'tests').mkdir(parents=True)
    (work/'app.py').write_text('VALUE = 0\n')
    (work/'tests/test_existing.py').write_text('import unittest\nclass Existing(unittest.TestCase):\n def test_existing(self):\n  self.assertTrue(True)\n')
    baseline=store.capture(work)
    path='tests/acceptance_sample.py';(work/path).write_text('import unittest\nclass Sample(unittest.TestCase):\n def test_value(self):\n  self.assertEqual(value(), 1)\n')
    frozen_snapshot=store.capture(work);case='acceptance_sample.Sample.test_value';release=digest('native-test-repair')
    board=Board(project)
    def execute(run,snapshot,phase):
        cases=['test_existing.Existing.test_existing']+([] if snapshot==baseline else [case])
        failing=[case] if phase in ('red','diagnostic') else []
        return store.record('suite_job',run.binding(),dict(exit_code=int(bool(failing)),
            report=dict(version=1,tests_run=len(cases),cases=cases,failures=[dict(case=c,assertion=True,frames=[dict(file=path,function='test_value')]) for c in failing],errors=[],skips=[],expected_failures=[],unexpected_successes=[]),
            identity=dict(binding=run.binding(),snapshot=snapshot,phase=phase,project=project.fingerprint(),image=project.validation_image),
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))
    q=Quality(project,store,SimpleNamespace(run=execute),board)
    def create(kind,owner,inputs,parents=(),extra=None):
        body=dict(version=1,kind=kind,release=release,inputs=inputs,**(extra or {}))
        with api.connect_closing() as conn:
            ident=kb.create_task(conn,title='Native repair '+kind,assignee=owner,body=json.dumps(body),parents=list(parents),
                workspace_kind='dir',workspace_path=str(work),completion_contract='local-only')
        return ident,body
    def claim(ident,review=False):
        with api.connect_closing() as conn:claimed=(kb.claim_review_task if review else kb.claim_task)(conn,ident)
        assert claimed;return board.current(ident,claimed.current_run_id)
    anchor_id,_=create('release','lead',{})
    test_id,test_body=create('tests','author',{'baseline':baseline})
    author=claim(test_id);red=q.red(author,baseline,frozen_snapshot)
    q.handoff(author,'Programmed Red handoff',{'red':red});reviewer=claim(test_id,True)
    freeze=q.tests_review(reviewer,red,dict(decision='approve',reason='Programmed independent fixture review.',findings=[]))
    board.finish_review(reviewer,'Frozen fixture',{'tests':freeze})
    source_id,source_body=create('implementation','author',{'tests':'parent:'+test_id+':tests'},[test_id],{'release_anchor':anchor_id})
    source=claim(source_id)
    with api.connect_closing() as conn:
        assert kb.block_task(conn,source_id,reason='Programmed fixture defect',expected_run_id=source.number)
        event=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(source_id,)).fetchone()['id']
    incident=store.record('incident',source.binding(),dict(project=project.fingerprint(),source=source_id,source_run=source.number,
        source_state='blocked',snapshot=frozen_snapshot,controller_effects=[],resume_allowed=True,block_event=event,cause=digest([source_id,event])))
    diag_id,_=create('diagnostic','cto',{'incident':incident},extra=dict(stage='cto',source=source_id,source_run=source.number))
    cto=claim(diag_id);job,report=q.observe(cto,frozen_snapshot,'diagnostic')
    experiment=q.record(cto,'diagnostic_experiment',dict(incident=incident,snapshot=frozen_snapshot,job=job,report=report))
    scope=validate_scope(project,store,incident,cto.binding(),experiment,dict(tests=freeze,test_paths=[path],cases=[case]))
    decision=q.record(cto,'diagnostic_decision',dict(incident=incident,action='repair_tests',experiment=experiment,test_repair=scope,delivery_approval=False))
    with api.connect_closing() as conn:assert kb.complete_task(conn,diag_id,summary='Programmed scoped repair',metadata={'diagnosis':decision},expected_run_id=cto.number)
    integration_id,_=create('integration','author',{'delivery':'parent:'+source_id+':delivery'},[source_id])
    releases=Releases(project,store,board,None)
    with api.connect_closing() as conn:
        anchor=kb.get_task(conn,anchor_id)
        def card(ident):
            task=kb.get_task(conn,ident)
            parents=[r['parent_id'] for r in conn.execute('SELECT parent_id FROM task_links WHERE child_id=?',(ident,))]
            return dict(id=ident,body=json.loads(task.body),parents=parents,workspace=task.workspace_path,owner=task.assignee,completion_contract=task.completion_contract)
        graph=dict(project=project.fingerprint(),validation_bundle=None,items=[dict(package=dict(id='one',title='One'),cards=dict(tests=card(test_id),implementation=card(source_id),integration=card(integration_id)))])
        prior=store.record('release_graph',releases.binding(anchor),graph)
        admission=store.record('test_repair_admission',releases.binding(anchor),dict(**scope,project=project.fingerprint(),repair_kind='fixture',
            incident=incident,source=source_id,source_run=source.number,source_contract=source.contract,
            prior_graph=prior,current_diagnosis=decision,reviewed_diagnosis=decision,qa_paths=scope['test_paths']))
        operation=Repairs(releases);target=releases.folder(anchor)/('continuation-'+diag_id+'.json')
        def crash(path,value):
            write_json(path,value)
            if path==target:raise OSError('injected after durable graph, before activation')
        with patch('fabriquinha.repairs.write_json',side_effect=crash):
            try:operation.materialize_submission(conn,anchor,graph,admission)
            except OSError:pass
            else:raise AssertionError('fault injection not reached')
        assert target.exists()
        restored=Repairs(Releases(project,store,Board(project),None))
        result=restored.materialize_submission(conn,anchor,graph,admission)
        assert restored.materialize_submission(conn,anchor,graph,admission)==result
        cards=result['items'][0]['cards'];assert len({c['id'] for c in cards.values()})==3
        assert kb.get_task(conn,source_id).status=='blocked'
        assert kb.get_task(conn,test_id).status=='done'
        tests=cards['tests'];implementation=cards['implementation']
        assert kb.get_task(conn,tests['id']).status=='ready'
        assert kb.get_task(conn,implementation['id']).status=='todo'
        assert implementation['body']['inputs']['tests']=='parent:'+tests['id']+':tests'
        assert kb.latest_run(conn,source_id).id==source.number
    result=dict(passed=True,model_calls=0,native_kanban=True,roles_programmed=True,suite_reports_programmed=True,
                independent_original_review=True,restart_idempotent=True,original_block_preserved=True,
                dependent_waits_for_new_freeze=True,delivery_approval=False)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--upstream',type=Path,required=True)
    a=p.parse_args();print(json.dumps(qualify(a.root.resolve(),a.upstream.resolve()),indent=2))
