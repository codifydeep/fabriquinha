"""Real native Kanban transition; programmed evidence, zero model/Docker calls.

This qualifies idempotent graph construction and native dependencies/review, not
product quality or autonomous diagnosis. Only a fresh isolated root is accepted.
"""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_s1 import prepare
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.kanban_lane import native
from fabriquinha.releases import Releases
from fabriquinha.repairs import Repairs,reviewed


def qualify(root,upstream):
    if root.exists():raise ValueError('fresh isolated root required')
    root.mkdir(mode=0o700,parents=True);prepare(root,upstream)
    project=Project.parse(dict(version=1,namespace='delivery-kit-fixture-proof',repository='https://github.com/example/product',
        branch='release/demo',validation_image='sha256:'+'a'*64,tests_dir='tests',
        reviewers={'backend':'lead','lead':'cto'},coordination_roles={'product':'product','lead':'lead'},
        technical_roles={'lead':'lead','cto':'cto'},qualification=True))
    store=Store(root/'private');board=Board(project);release=digest('isolated fixture transition')
    kb,kbc,_=native();releases=Releases(project,store,board,None);operation=Repairs(releases)
    work=root/'source';(work/'tests').mkdir(parents=True)
    (work/'app.py').write_text('preserved product\n');(work/'tests/acceptance_example.py').write_text('fixture source\n')
    snapshot=store.capture(work)
    with kbc.connect_closing() as conn:
        anchor_id=kb.create_task(conn,title='Isolated release',body=json.dumps(dict(release=release)),initial_status='blocked')
        anchor=kb.get_task(conn,anchor_id)
        prior_plan=kb.create_task(conn,title='Programmed original plan',body='{}',completion_contract='local-only')
        assert kb.complete_task(conn,prior_plan,summary='Programmed fixture setup; not product approval')
        def card(phase,parents,inputs):
            body=dict(version=1,kind=phase,release=release,release_anchor=anchor_id,inputs=inputs)
            ident=kb.create_task(conn,title='Original '+phase,body=json.dumps(body),assignee='backend',
                parents=parents,workspace_kind='dir',workspace_path=str(work),completion_contract='local-only')
            return dict(id=ident,body=body,parents=parents,workspace=str(work),owner='backend',completion_contract='local-only')
        tests=card('tests',[prior_plan],{'baseline':snapshot})
        assert kb.complete_task(conn,tests['id'],summary='Programmed frozen fixture')
        implementation=card('implementation',[tests['id']],{'tests':'parent:'+tests['id']+':tests'})
        claimed=kb.claim_task(conn,implementation['id']);assert claimed
        assert kb.block_task(conn,claimed.id,kind='needs_input',reason='Programmed incomplete implementation',expected_run_id=claimed.current_run_id)
        # Only fixture setup: do not claim to qualify failure escalation here.
        conn.execute("UPDATE tasks SET status='triage' WHERE id=?",(claimed.id,))
        integration=card('integration',[implementation['id']],{'delivery':'parent:'+implementation['id']+':delivery'})
        item=dict(package=dict(id='second',title='Second'),cards=dict(tests=tests,implementation=implementation,integration=integration))
        graph=dict(project=project.fingerprint(),items=[item],validation_bundle='programmed-bundle',submission_depth=2)
        original={c['id']:kb.get_task(conn,c['id']).status for c in item['cards'].values()}
        facts=dict(source=claimed.id,source_run=claimed.current_run_id,source_contract=digest(implementation['body']),
            snapshot=snapshot,implementation_snapshot=snapshot,tests='programmed-freeze',incident='programmed-incident',
            reviewed_diagnosis='programmed-diagnosis',red_baseline=snapshot,
            qa_paths=['tests/acceptance_example.py'],delivery_approval=False)
        spec=dict(task=prior_plan,approval='programmed-brief',document=dict(architecture='HTTP',observability='local'))
        closed=releases.closed
        releases.closed=lambda task,key,kind:('programmed-freeze',None,None) if task==tests['id'] else closed(task,key,kind)
        with patch('fabriquinha.repairs.fixture_failure',return_value=facts),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]):
            proposal=operation.propose_fixture(conn,anchor,spec,item,'programmed-incident','programmed-diagnosis',graph)
            assert operation.propose_fixture(conn,anchor,spec,item,'programmed-incident','programmed-diagnosis',graph)==proposal
            plan=kb.claim_task(conn,proposal);assert plan
            author=board.current(plan.id,plan.current_run_id);assert author.actor=='lead' and not author.reviewing
            body=json.loads(plan.body)
            proposed=store.record('work_plan',author.binding(),dict(project=project.fingerprint(),repair_body=body,
                document=dict(classification='test_contract',reason='Programmed fixture setup correction.',test_paths=facts['qa_paths'])))
            board.review(author,'Programmed independent proposal handoff',{'plan':proposed})
            reviewing=kb.claim_review_task(conn,proposal);assert reviewing
            reviewer=board.current(proposal,reviewing.current_run_id);assert reviewer.actor=='cto' and reviewer.reviewing
            approval=store.record('plan_review',reviewer.binding(),dict(project=project.fingerprint(),plan=proposed,
                verdict=dict(decision='approve',reason='Programmed independent fixture review.',findings=[])))
            board.finish_review(reviewer,'Programmed reviewed proposal',{'plan_review':approval})
            assert reviewed(project,store,approval)['task']==proposal
            path=releases.folder(anchor)/('continuation-'+proposal+'.json')
            def crash_after(path_arg,value):
                write_json(path_arg,value)
                if path_arg==path:raise OSError('injected after graph persistence')
            def count():return conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
            count_before=count()
            with patch('fabriquinha.executor.validation_files',return_value=('programmed-bundle',{})):
                for effect in (OSError('injected before graph persistence'),crash_after):
                    with patch('fabriquinha.repairs.write_json',side_effect=effect):
                        try:operation.materialize_submission(conn,anchor,graph,approval)
                        except OSError:pass
                        else:raise AssertionError('injected failure absent')
                    assert count()==count_before+3
                    # Native dependencies must prevent a replacement implementation from claiming early.
                    if path.exists():
                        saved=store.receipt(json.loads(path.read_text())['receipt'])['payload']
                        for value in saved['items'][0]['cards'].values():assert kb.get_task(conn,value['id']).status=='blocked'
                result=operation.materialize_submission(conn,anchor,graph,approval)
                assert operation.materialize_submission(conn,anchor,graph,approval)==result
                assert count()==count_before+3
                assert result['submission_depth']==2 and result['fixture_depth']==1
                assert {key:kb.get_task(conn,key).status for key in original}==original
                replacement=result['items'][0]['cards']
                assert kb.claim_task(conn,replacement['implementation']['id']) is None
                test_claim=kb.claim_task(conn,replacement['tests']['id']);assert test_claim
                assert kb.block_task(conn,test_claim.id,kind='needs_input',reason='Qualification complete; no worker started',expected_run_id=test_claim.current_run_id)
    result=dict(native_proposal_review=True,idempotent_creation=True,crash_before_after_graph=True,
        native_dependencies_enforced=True,history_preserved=True,programmed_quality_evidence=True,
        model_calls=0,docker_calls=0,delivery_approval=False)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.root.resolve(),args.upstream.resolve()),indent=2))
