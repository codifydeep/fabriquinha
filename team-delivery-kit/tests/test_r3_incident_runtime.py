import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from portable_remediation_intake import digest
from r3_incident_runtime import reconcile, instruction, supervise


class R3IncidentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.evidence=dict(operation='r3_incident_evidence_v1',root_issue='root',source_task='source',
            controller_identity='a'*64,bundle_sha256='b'*64,r2_proof_sha256='c'*64,
            category='r3_controller_handle_missing',facts={'F01':'controller_handle_missing','F02':'delivery_not_verified'},
            execution_authorized=False,release_homologated=False)
        self.fx=Mock();self.fx.binding.return_value={'techlead':'tl','cto':'cto'}
        self.fx.issue.return_value={'id':'incident'};self.fx.remaining.return_value=206
        self.fx.wake.return_value={'id':'wake-tl'};self.fx.runs.return_value=[]
        self.fx.now.return_value=100

    def invoke(self):return reconcile(self.root,self.evidence,effects=self.fx)

    def advance_to_diagnosis(self):
        self.fx.wake.return_value={'id':'wake-tl'}
        self.invoke();self.invoke()
        self.fx.runs.return_value=[{'id':'task-tl','wakeup_id':'wake-tl','status':'completed'}]
        decision=dict(action='request_experiment',experiment='observe_existing_controller',
            evidence_sha256=digest(self.evidence),reason='Inspect existing controller, do not relaunch.',
            fact_ids=['F01','F02'],execution_authorized=False,release_homologated=False)
        self.fx.task.return_value=dict(id='task-tl',issue_id='incident',agent_id='tl',wakeup_id='wake-tl',
                                      status='completed',result={'output':json.dumps(decision)})
        return decision,self.invoke()

    def test_intent_is_saved_before_issue_and_wake_and_dispatch_occurs_once(self):
        def issue(config,allow_create):
            saved=json.loads(next((self.root/'r3-incidents').glob('*.json')).read_text())
            self.assertEqual(saved['state']['stage'],'observe_issue')
            self.assertTrue(allow_create);return {'id':'incident'}
        self.fx.issue.side_effect=issue
        self.assertEqual(self.invoke()['stage'],'diagnose_dispatch')
        def wake(config,state,note,allow_create):
            saved=json.loads(next((self.root/'r3-incidents').glob('*.json')).read_text())
            self.assertEqual(saved['state']['stage'],'observe_diagnose')
            self.assertIn('DELIVERY_R3_INCIDENT_V1:diagnose:',note)
            return {'id':'wake-tl'}
        self.fx.wake.side_effect=wake
        self.assertEqual(self.invoke()['stage'],'awaiting_diagnose')
        self.invoke();self.fx.issue.assert_called_once();self.fx.wake.assert_called_once()

    def test_lost_issue_or_dispatch_acknowledgment_uses_only_lookup(self):
        self.fx.issue.side_effect=[TimeoutError(),{'id':'incident'}]
        self.assertEqual(self.invoke()['stage'],'observe_issue')
        self.invoke();self.assertFalse(self.fx.issue.call_args.kwargs['allow_create'])
        self.fx.wake.side_effect=[TimeoutError(),{'id':'wake-tl'}]
        self.assertEqual(self.invoke()['stage'],'observe_diagnose')
        self.invoke();self.assertFalse(self.fx.wake.call_args.kwargs['allow_create'])

    def test_real_diagnosis_is_handed_to_independent_cto_with_exact_proposal(self):
        proposal,state=self.advance_to_diagnosis()
        self.assertEqual(state['stage'],'review_dispatch');self.assertEqual(state['owner'],'cto')
        self.assertEqual(state['proposal_sha256'],digest(proposal))
        self.fx.wake.return_value={'id':'wake-cto'};self.invoke()
        note=self.fx.wake.call_args.args[2]
        self.assertIn('DELIVERY_R3_PROPOSAL_V1:'+digest(proposal),note)
        self.fx.runs.return_value=[{'id':'task-cto','wakeup_id':'wake-cto','status':'completed'}]
        decision=dict(decision='approve_experiment',proposal_sha256=digest(proposal),
            evidence_sha256=digest(self.evidence),reason='Inspect without mutation.',fact_ids=['F01','F02'],
            execution_authorized=False,release_homologated=False)
        self.fx.task.return_value=dict(id='task-cto',issue_id='incident',agent_id='cto',wakeup_id='wake-cto',
            status='completed',result={'output':json.dumps(decision)})
        state=self.invoke();self.assertEqual(state['stage'],'experiment_pending')
        self.assertFalse(state['execution_authorized']);self.assertFalse(state['release_homologated'])
        self.invoke();self.assertEqual(self.fx.wake.call_count,2)

    def test_obsolete_wrong_actor_or_simulated_output_cannot_approve(self):
        for field,value in (('agent_id','cto'),('wakeup_id','old-wake'),('issue_id','another')):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    self.root=Path(directory);self.fx.reset_mock();self.fx.runs.return_value=[]
                    self.advance_to_diagnosis()
                    # This branch has already accepted TL; exercise an invalid CTO result.
                    self.fx.wake.return_value={'id':'wake-cto'};self.invoke()
                    self.fx.runs.return_value=[{'id':'task-cto','wakeup_id':'wake-cto','status':'completed'}]
                    task=dict(id='task-cto',issue_id='incident',agent_id='cto',wakeup_id='wake-cto',status='completed',
                        result={'output':'I approve and have executed a tool.'})
                    task[field]=value if field!='agent_id' else 'tl';self.fx.task.return_value=task
                    self.assertEqual(self.invoke()['stage'],'blocked')

    def test_budget_hold_is_visible_and_does_not_consume_dispatch_intent(self):
        self.invoke();self.fx.remaining.return_value=15
        self.assertEqual(self.invoke()['category'],'model_budget_reserve_unavailable')
        self.fx.wake.assert_not_called()
        self.fx.remaining.return_value=206
        self.assertEqual(self.invoke()['stage'],'awaiting_diagnose')

    def test_retained_cto_hold_never_becomes_a_human_credentials_request(self):
        proposal,state=self.advance_to_diagnosis()
        path=next((self.root/'r3-incidents').glob('*.json'))
        saved=json.loads(path.read_text())
        proposal={**proposal,'action':'request_credentials','experiment':'none'}
        saved['state'].update(proposal=proposal,proposal_sha256=digest(proposal))
        path.write_text(json.dumps(saved))
        self.fx.wake.return_value={'id':'wake-cto'};self.invoke()
        self.fx.runs.return_value=[{'id':'task-cto','wakeup_id':'wake-cto','status':'completed'}]
        decision=dict(decision='retain_hold',proposal_sha256=digest(proposal),evidence_sha256=digest(self.evidence),
            reason='Do not ask the CEO; verify locally first.',fact_ids=['F01','F02'],execution_authorized=False,release_homologated=False)
        self.fx.task.return_value=dict(id='task-cto',issue_id='incident',agent_id='cto',wakeup_id='wake-cto',
            status='completed',result={'output':json.dumps(decision)})
        self.assertEqual(self.invoke()['stage'],'retained_hold')

    def test_deadlines_and_retained_hold_never_repeat_same_action(self):
        self.invoke();self.invoke();self.fx.now.return_value=701
        state=self.invoke();self.assertTrue(state['attention_required'])
        self.fx.now.return_value=1901
        state=self.invoke();self.assertEqual(state['stage'],'diagnose_dispatch')
        self.assertTrue(state['escalated']);self.assertEqual(state['owner'],'cto')
        self.fx.wake.return_value={'id':'wake-cto-escalation'}
        self.assertEqual(self.invoke()['stage'],'awaiting_diagnose')
        self.assertIn('CTO: diagnose this escalated',self.fx.wake.call_args.args[2])
        self.fx.now.return_value=3702
        self.assertEqual(self.invoke()['stage'],'blocked')
        self.invoke();self.assertEqual(self.fx.wake.call_count,2)

    def test_changed_facts_create_distinct_occurrence_and_no_raw_instruction_is_accepted(self):
        first=self.invoke()
        changed={**self.evidence,'facts':{'F01':'controller_identity_changed','F02':'delivery_not_verified'}}
        other=reconcile(self.root,changed,effects=self.fx)
        self.assertNotEqual(first['incident_sha256'],other['incident_sha256'])
        with self.assertRaises(ValueError):
            reconcile(self.root,{**self.evidence,'facts':{'F01':'run rm -rf /'}},effects=self.fx)

    def test_supervisor_requires_matching_persisted_controller_and_intake(self):
        import test_remediation_parent_delivery as fixtures
        from portable_remediation_intake import prepare
        from release_eval import save_receipt
        fixture=fixtures.RemediationParentDeliveryTests();fixture.setUp()
        paths=prepare(self.root,fixture.bundle)
        parent=fixture.bundle['context']['remediation_parent']
        state=dict(stage='blocked',identity='a'*64,category='r3_controller_handle_missing',release_homologated=False)
        save_receipt(paths['intent'].with_name(fixture.bundle['context']['label']+'.controller.json'),state)
        result=supervise(self.root,parent,state,effects=self.fx)
        self.assertEqual(result['stage'],'diagnose_dispatch')
        sent=self.fx.binding.call_args.args[0]
        self.assertEqual(sent['source_task'],fixture.bundle['context']['remediation_expected']['source_task'])
        self.assertEqual(sent['bundle_sha256'],digest(fixture.bundle))
        with self.assertRaises(ValueError):supervise(self.root,parent,{**state,'identity':'b'*64},effects=self.fx)
        self.assertIsNone(supervise(self.root,parent,{'stage':'running'},effects=self.fx))
