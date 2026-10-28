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


def qualify(root,upstream,*,direct=False):
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
        incident=store.record('incident',board.current(ident,claimed.current_run_id).binding(),dict(project=project.fingerprint(),snapshot=snapshot,block_event=1,cause='programmed-review'))
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
        held_body=dict(version=1,kind='diagnostic',release=release,stage='cto',source=ident,source_run=claimed.current_run_id,inputs={'incident':incident})
        held_id=kb.create_task(conn,title='Programmed previous hold',body=json.dumps(held_body),assignee='cto',completion_contract='local-only')
        held_claim=kb.claim_task(conn,held_id);assert held_claim
        held_run=board.current(held_id,held_claim.current_run_id)
        hold=store.record('diagnostic_decision',held_run.binding(),dict(project=project.fingerprint(),incident=incident,action='hold',delivery_approval=False))
        facts['reviewed_diagnosis']=hold
        assert kb.complete_task(conn,held_id,summary='Programmed prior hold',metadata={'diagnosis':hold},expected_run_id=held_run.number)
        with patch('fabriquinha.repairs.review_failure',return_value=facts),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]):
            legacy_body=dict(version=1,kind='diagnostic',release=release,stage='cto',
                source=ident,source_run=claimed.current_run_id,inputs={'incident':incident,'held_review':hold},
                review_experiment={'handoff':handoff})
            legacy=kb.create_task(conn,title='Legacy feedback fixture',body=json.dumps(legacy_body),assignee='cto',
                completion_contract='local-only',idempotency_key=digest([project.fingerprint(),ident,claimed.current_run_id,'review-experiment']))
            legacy_claim=kb.claim_task(conn,legacy);assert legacy_claim
            assert operation.prepare_review_probe(conn,anchor,card,incident,hold,handoff)==legacy
            legacy_run=board.current(legacy,legacy_claim.current_run_id)
            legacy_receipt=store.record('diagnostic_decision',legacy_run.binding(),dict(project=project.fingerprint(),
                incident=incident,action='hold',experiment='unchanged-evidence',delivery_approval=False))
            assert kb.complete_task(conn,legacy,summary='Programmed unchanged observation',metadata={'diagnosis':legacy_receipt},expected_run_id=legacy_run.number)
            with patch('fabriquinha.repairs.review_reassessment',return_value=facts):
                assert operation.prepare_review_probe(conn,anchor,card,incident,hold,handoff)==legacy
            with patch('fabriquinha.repairs.review_reassessment',side_effect=ValueError('new observed outcome required; changed wording is insufficient')):
                probe=operation.prepare_review_probe(conn,anchor,card,incident,hold,handoff)
            assert probe!=legacy and kb.get_task(conn,legacy).status=='done'
            assert json.loads(kb.get_task(conn,probe).body)['escalated_from']==legacy
            assert operation.prepare_review_probe(conn,anchor,card,incident,hold,handoff)==probe
            assert kb.get_task(conn,probe).max_retries==0
            probe_claim=kb.claim_task(conn,probe);assert probe_claim
            probe_run=board.current(probe,probe_claim.current_run_id)
            assert probe_run.actor=='cto' and probe_run.kind=='diagnostic'
            evidence=store.record('diagnostic_experiment',probe_run.binding(),dict(project=project.fingerprint(),incident=incident))
            facts['new_evidence']=evidence
            probe_result=store.record('diagnostic_decision',probe_run.binding(),dict(project=project.fingerprint(),incident=incident,action='hold',experiment=evidence,delivery_approval=False))
            assert kb.complete_task(conn,probe,summary='Programmed experiment result',metadata={'diagnosis':probe_result},expected_run_id=probe_run.number)
            assert operation.prepare_review_probe(conn,anchor,card,incident,hold,handoff)==probe
            assert kb.claim_task(conn,probe) is None
            assert kb.get_task(conn,ident).status=='triage'
        count=lambda:conn.execute('SELECT count(*) FROM tasks').fetchone()[0]
        before=count();create=kb.create_task
        with patch('fabriquinha.repairs.review_failure',return_value=facts),patch('fabriquinha.repairs.review_reassessment',return_value=facts),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]),patch('fabriquinha.intake.Intake.approved',return_value=({'binding':{'release':release}},None)):
            def interrupted(*args,**kwargs):
                create(*args,**kwargs)
                raise OSError('simulated lost acknowledgement after native creation')
            with patch.object(kb,'create_task',side_effect=interrupted):
                try:operation.prepare_review_proposal(conn,anchor,card,incident,hold,handoff,evidence,approved_brief='programmed-brief',graph=graph)
                except OSError:pass
                else:raise AssertionError('missing injected failure')
            assert count()==before+1
        conn.commit()
    # New connection and operation instance represent reconstruction, not retained IDs.
    with kbc.connect_closing() as conn:
        operation=Repairs(Releases(project,store,board,None));anchor=kb.get_task(conn,anchor_id)
        with patch('fabriquinha.repairs.review_failure',return_value=facts),patch('fabriquinha.repairs.review_reassessment',return_value=facts),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]),patch('fabriquinha.intake.Intake.approved',return_value=({'binding':{'release':release}},None)):
            proposal=operation.prepare_review_proposal(conn,anchor,card,incident,hold,handoff,evidence,approved_brief='programmed-brief',graph=graph)
            assert operation.prepare_review_proposal(conn,anchor,card,incident,hold,handoff,evidence,approved_brief='programmed-brief',graph=graph)==proposal
            assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0]==before+1
            assert kb.get_task(conn,ident).status=='triage'
            assert kb.get_task(conn,proposal).status=='blocked'
            assert kb.claim_task(conn,proposal) is None
            if direct:
                assert kb.unblock_task(conn,proposal)
                old_claim=kb.claim_task(conn,proposal);assert old_claim
                old_author=board.current(proposal,old_claim.current_run_id)
                old_plan=store.record('work_plan',old_author.binding(),dict(project=project.fingerprint(),
                    document=dict(classification='infrastructure',reason='Historical unapproved proposal',test_paths=[])))
                board.review(old_author,'Historical pending review',{'plan':old_plan})
                assert kb.get_task(conn,proposal).status=='review'
                with patch.object(kb,'block_task',side_effect=OSError('interrupted after legacy reopen')):
                    try:operation.advance_review_probes(conn,anchor,{'approval':'programmed-brief'},graph)
                    except OSError:pass
                    else:raise AssertionError('missing legacy retirement interruption')
                assert kb.get_task(conn,proposal).status=='ready'
                assert not (releases.folder(anchor)/('review-admission-'+ident+'.json')).exists()
                operation.advance_review_probes(conn,anchor,{'approval':'programmed-brief'},graph)
                assert kb.get_task(conn,proposal).status=='blocked'
                pointer=releases.folder(anchor)/('review-admission-'+ident+'.json')
                approval=json.loads(pointer.read_text())['receipt']
                assert store.receipt(approval)['kind']=='review_admission'
                operation.advance_review_probes(conn,anchor,{'approval':'programmed-brief'},graph)
                assert json.loads(pointer.read_text())['receipt']==approval
                assert kb.latest_run(conn,proposal).outcome=='blocked'
                assert store.receipt(old_plan)['payload']['document']['classification']=='infrastructure'
                assert not any(json.loads(p.read_text())['kind']=='plan_review' for p in (store.root/'receipts').glob('*.json'))
            else:
                assert kb.unblock_task(conn,proposal)  # Historical proposal fixture.
                assert kb.get_task(conn,proposal).status=='ready'
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
            parent=authority['task']
            assert authority.get('controller_admission',False)==direct
            assert authority['proposal']['classification']=='reassess'
            assert authority['context']['delivery_approval'] is False
            assert kb.get_task(conn,ident).status=='triage'
            with patch('fabriquinha.executor.validation_files',return_value=('programmed-bundle',{})):
                with patch.object(operation,'publish_review_handoff',side_effect=OSError('interrupted before transfer')):
                    try:operation.materialize_submission(conn,anchor,graph,approval)
                    except OSError:pass
                    else:raise AssertionError('missing graph interruption')
                pointer=releases.folder(anchor)/('continuation-'+parent+'.json')
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
                from dataclasses import replace
                try:Quality(project,store,None,board).review_authorship(replace(active,actor=active.author),handoff,store.receipt(handoff))
                except ValueError:pass
                else:raise AssertionError('delivery self-review accepted')
                from fabriquinha.recovery import Recovery
                diagnostic_snapshot=Recovery(project,store,board).snapshot(conn,kb.get_task(conn,successor),active,{'red':handoff})
                assert diagnostic_snapshot==snapshot
                assert operation.publish_review_handoff(conn,successor_card,approval)==successor
                assert kb.get_task(conn,successor).current_run_id==active.number
                assert kb.get_task(conn,ident).status=='triage'
                with patch('fabriquinha.executor.validation_files',return_value=('programmed-bundle',{})):
                    completed=operation.materialize_submission(conn,anchor,graph,approval)
                    assert completed==saved
                    assert operation.materialize_submission(conn,anchor,graph,approval)==saved
                    assert operation.continue_review(conn,anchor,graph)==saved
                downstream=saved['items'][0]['cards']['implementation']
                assert downstream['parents']==[successor,parent]
                assert kb.claim_task(conn,downstream['id']) is None
                verdict=dict(decision='changes',reason='Programmed independent request for correction',
                    findings=[dict(path='tests/example.py',reason='Programmed finding')])
                review=store.record('test_review',active.binding(),dict(project=project.fingerprint(),red=handoff,snapshot=snapshot,verdict=verdict))
                board.finish_review(active,'Correct the observed issue',{'review':review},changes=True)
                assert kb.get_task(conn,successor).assignee=='author'
                assert board.pending_review_transfers(conn)==[]
                correction=kb.claim_task(conn,successor);assert correction
                correcting=board.current(successor,correction.current_run_id)
                assert correcting.actor=='author' and not correcting.reviewing
                feedback=board.review_feedback(correcting,store)
                assert len(feedback)==1 and feedback[0]['receipt']==review
                corrected=store.record('red',correcting.binding(),dict(project=project.fingerprint(),snapshot=snapshot))
                board.review(correcting,'Programmed corrected delivery',{'red':corrected})
                rereview=kb.claim_review_task(conn,successor);assert rereview
                checking=board.current(successor,rereview.current_run_id)
                assert checking.actor=='lead' and checking.reviewing
                assert board.input(checking,'red',review_handoff=True)==corrected
                assert corrected!=handoff
                try:Quality(project,store,None,board).tests_review(checking,handoff,dict(decision='approve',reason='Obsolete',findings=[]))
                except ValueError as error:assert 'obsolete' in str(error)
                else:raise AssertionError('obsolete author delivery accepted')
                assert Quality(project,store,None,board).review_authorship(checking,corrected,store.receipt(corrected)) is None
                frozen=store.record('tests_frozen',checking.binding(),dict(project=project.fingerprint(),red=corrected,snapshot=snapshot,programmed=True))
                board.finish_review(checking,'Programmed independent completion',{'tests':frozen})
                dependent=kb.claim_task(conn,downstream['id']);assert dependent
                dependent_run=board.current(downstream['id'],dependent.current_run_id)
                assert board.input(dependent_run,'tests')==frozen
                assert kb.block_task(conn,dependent.id,kind='needs_input',reason='Qualification finished; no model worker',expected_run_id=dependent.current_run_id)
    result=dict(passed=True,successor_failure_snapshot_resolved=True,direct_controller_admission=direct,legacy_proposal_path=not direct,bounded_native_cto_probe=True,no_probe_retry_after_completion=True,native_creation=True,reconstructed_after_lost_ack=True,duplicate_cards=0,
        original_triage_preserved=True,proposal_initially_not_dispatchable=True,independent_native_review=True,self_review_denied=True,programmed_admission=True,
        changes_return_to_original_author=True,corrected_handoff_independently_reviewed=True,dependent_released_after_review=True,immutable_graph_recovered=True,dependent_work_held=True,native_delivery_transfer=True,transfer_lost_ack_recovered=True,active_review_preserved=True,
        model_calls=0,docker_calls=0,delivery_approval=False)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--direct',action='store_true')
    args=parser.parse_args();print(json.dumps(qualify(args.root.resolve(),args.upstream.resolve(),direct=args.direct),indent=2))
