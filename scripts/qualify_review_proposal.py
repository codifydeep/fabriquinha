"""Native proposal persistence with programmed admission facts, no model/Docker.

Qualifies proposal creation, native independent plan review and preserved
delivery transfer after lost acknowledgements. Admission is programmed; this
does not qualify whole-graph succession or autonomous delivery.
"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
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
    project=Project.parse(dict(version=1,namespace='delivery-kit-review-proof',repository='https://github.com/example/product',
        branch='release/demo',validation_image='sha256:'+'a'*64,tests_dir='tests',
        reviewers={'author':'lead','lead':'cto'},coordination_roles={'product':'product','lead':'lead'},
        technical_roles={'lead':'lead','cto':'cto'},qualification=True))
    store=Store(root/'private');board=Board(project);kb,kbc,_=native()
    releases=Releases(project,store,board,None);operation=Repairs(releases);release=digest('review proposal proof')
    with kbc.connect_closing() as conn:
        anchor_id=kb.create_task(conn,title='Isolated release',body=json.dumps(dict(release=release)),initial_status='blocked')
        anchor=kb.get_task(conn,anchor_id)
        body=dict(version=1,kind='tests',release=release,release_anchor=anchor_id,inputs={})
        work=root/'work';work.mkdir();snapshot=store.capture(work)
        ident=kb.create_task(conn,title='Original source',body=json.dumps(body),assignee='author',completion_contract='local-only',workspace_kind='dir',workspace_path=str(work))
        claimed=kb.claim_task(conn,ident);assert claimed
        original=board.current(ident,claimed.current_run_id)
        handoff=store.record('red',original.binding(),dict(project=project.fingerprint(),snapshot=snapshot))
        board.review(original,'Programmed author delivery',{'red':handoff})
        claimed=kb.claim_review_task(conn,ident);assert claimed
        incident=store.record('incident',board.current(ident,claimed.current_run_id).binding(),dict(project=project.fingerprint(),snapshot=snapshot))
        assert kb.block_task(conn,ident,kind='needs_input',reason='Programmed triage setup',expected_run_id=claimed.current_run_id)
        # Isolated fixture setup, not a production transition or escalation proof.
        conn.execute("UPDATE tasks SET status='triage' WHERE id=?",(ident,))
        card=dict(id=ident,body=body,owner='author',completion_contract='local-only',workspace=str(work),parents=[])
        cards={'tests':card}
        for phase,parent,field in (('implementation',ident,'tests'),('integration',None,'delivery')):
            parent=parent or cards['implementation']['id']
            child_body=dict(version=1,kind=phase,release=release,release_anchor=anchor_id,inputs={field:'parent:'+parent+':'+field})
            child=kb.create_task(conn,title='Pending '+phase,body=json.dumps(child_body),assignee='author',parents=[parent],
                workspace_kind='dir',workspace_path=str(work),completion_contract='local-only')
            cards[phase]=dict(id=child,body=child_body,owner='author',parents=[parent],workspace=str(work),completion_contract='local-only')
        graph=dict(project=project.fingerprint(),validation_bundle='programmed-bundle',items=[dict(package=dict(id='item',title='Item'),cards=cards)])
        facts=dict(source=ident,source_run=claimed.current_run_id,source_contract=digest(body),snapshot=snapshot,
            handoff=handoff,incident=incident,reviewed_diagnosis='decision',new_evidence='evidence',
            observation_identity=digest('changed observation'),delivery_approval=False,requires_independent_plan_review=True)
        count=lambda:conn.execute('SELECT count(*) FROM tasks').fetchone()[0]
        before=count();create=kb.create_task
        with patch('fabriquinha.repairs.review_reassessment',return_value=facts),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]),patch('fabriquinha.intake.Intake.approved',return_value=({'binding':{'release':release}},None)):
            def interrupted(*args,**kwargs):
                create(*args,**kwargs)
                raise OSError('simulated lost acknowledgement after native creation')
            with patch.object(kb,'create_task',side_effect=interrupted):
                try:operation.prepare_review_proposal(conn,anchor,card,'incident','decision',handoff,'evidence',approved_brief='programmed-brief',graph=graph)
                except OSError:pass
                else:raise AssertionError('missing injected failure')
            assert count()==before+1
        conn.commit()
    # New connection and operation instance represent reconstruction, not retained IDs.
    with kbc.connect_closing() as conn:
        operation=Repairs(Releases(project,store,board,None));anchor=kb.get_task(conn,anchor_id)
        with patch('fabriquinha.repairs.review_reassessment',return_value=facts),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]),patch('fabriquinha.intake.Intake.approved',return_value=({'binding':{'release':release}},None)):
            proposal=operation.prepare_review_proposal(conn,anchor,card,'incident','decision',handoff,'evidence',approved_brief='programmed-brief',graph=graph)
            assert operation.prepare_review_proposal(conn,anchor,card,'incident','decision',handoff,'evidence',approved_brief='programmed-brief',graph=graph)==proposal
            assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0]==before+1
            assert kb.get_task(conn,ident).status=='triage'
            assert kb.get_task(conn,proposal).status=='blocked'
            assert kb.claim_task(conn,proposal) is None
            assert kb.unblock_task(conn,proposal)
            claim=kb.claim_task(conn,proposal);assert claim
            author=board.current(proposal,claim.current_run_id)
            assert author.actor=='lead' and not author.reviewing
            proposal_body=json.loads(kb.get_task(conn,proposal).body)
            plan=store.record('work_plan',author.binding(),dict(project=project.fingerprint(),
                approval='programmed-brief',repair_body=proposal_body,
                document=dict(classification='reassess',reason='Programmed review of changed observation',test_paths=[])))
            board.review(author,'Programmed technical proposal, not product approval',{'plan':plan})
            claimed_review=kb.claim_review_task(conn,proposal);assert claimed_review
            reviewer=board.current(proposal,claimed_review.current_run_id)
            assert reviewer.actor=='cto' and reviewer.reviewing and reviewer.actor!=author.actor
            decision=dict(project=project.fingerprint(),plan=plan,
                verdict=dict(decision='approve',reason='Programmed independent proposal review',findings=[]))
            forged=store.record('plan_review',{**reviewer.binding(),'actor':'lead'},decision)
            try:reviewed(project,store,forged)
            except ValueError:pass
            else:raise AssertionError('self review accepted')
            approval=store.record('plan_review',reviewer.binding(),decision)
            board.finish_review(reviewer,'Programmed proposal approved, delivery remains unapproved',{'plan_review':approval})
            authority=reviewed(project,store,approval)
            assert authority['proposal']['classification']=='reassess'
            assert authority['context']['delivery_approval'] is False
            assert kb.get_task(conn,ident).status=='triage'
            with patch('fabriquinha.executor.validation_files',return_value=('programmed-bundle',{})):
                with patch.object(operation,'publish_review_handoff',side_effect=OSError('interrupted before transfer')):
                    try:operation.materialize_submission(conn,anchor,graph,approval)
                    except OSError:pass
                    else:raise AssertionError('missing graph interruption')
                pointer=releases.folder(anchor)/('continuation-'+proposal+'.json')
                saved=store.receipt(json.loads(pointer.read_text())['receipt'])['payload']
                successor_card=saved['items'][0]['cards']['tests'];successor=successor_card['id']
                for c in saved['items'][0]['cards'].values():assert kb.get_task(conn,c['id']).status=='blocked'
            # Crash after native unblock but before request_review: runtime must
            # not dispatch this ready card as a fresh author execution.
            with patch('fabriquinha.quality.Quality.test_evidence',return_value=store.receipt(handoff)):
                with patch.object(kb,'request_review',side_effect=OSError('before handoff')):
                    try:operation.publish_review_handoff(conn,successor_card,approval)
                    except OSError:pass
                    else:raise AssertionError('missing pre-handoff interruption')
            assert board.pending_review_transfers(conn)==[successor]
            native_request=kb.request_review
            with patch('fabriquinha.quality.Quality.test_evidence',return_value=store.receipt(handoff)):
                def lost_transfer(*args,**kwargs):
                    assert native_request(*args,**kwargs)
                    raise OSError('lost native handoff acknowledgement')
                with patch.object(kb,'request_review',side_effect=lost_transfer):
                    try:operation.publish_review_handoff(conn,successor_card,approval)
                    except OSError:pass
                    else:raise AssertionError('missing handoff failure injection')
                assert kb.get_task(conn,successor).status=='review'
                assert board.pending_review_transfers(conn)==[]
                assert operation.publish_review_handoff(conn,successor_card,approval)==successor
                assert conn.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='review_requested'",(successor,)).fetchone()[0]==1
                claimed=kb.claim_review_task(conn,successor);assert claimed
                active=board.current(successor,claimed.current_run_id)
                assert active.reviewing and active.author=='author' and active.actor=='lead'
                assert board.input(active,'red',review_handoff=True)==handoff
                from fabriquinha.quality import Quality
                assert Quality(project,store,None,board).review_authorship(active,handoff,store.receipt(handoff))==approval
                assert operation.publish_review_handoff(conn,successor_card,approval)==successor
                assert kb.get_task(conn,successor).current_run_id==active.number
                assert kb.get_task(conn,ident).status=='triage'
                with patch('fabriquinha.executor.validation_files',return_value=('programmed-bundle',{})):
                    completed=operation.materialize_submission(conn,anchor,graph,approval)
                    assert completed==saved
                    assert operation.materialize_submission(conn,anchor,graph,approval)==saved
                downstream=saved['items'][0]['cards']['implementation']
                assert downstream['parents']==[successor,proposal]
                assert kb.claim_task(conn,downstream['id']) is None
    result=dict(passed=True,native_creation=True,reconstructed_after_lost_ack=True,duplicate_cards=0,
        original_triage_preserved=True,proposal_initially_not_dispatchable=True,independent_native_review=True,self_review_denied=True,programmed_admission=True,
        immutable_graph_recovered=True,dependent_work_held=True,native_delivery_transfer=True,transfer_lost_ack_recovered=True,active_review_preserved=True,
        model_calls=0,docker_calls=0,delivery_approval=False)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.root.resolve(),args.upstream.resolve()),indent=2))
