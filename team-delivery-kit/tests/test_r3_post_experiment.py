import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from portable_remediation_intake import digest
from release_eval import save_receipt
from r3_post_experiment import next_evidence,reconcile_post,drive
from r3_fixed_experiments import experiment_identity
from r3_incident_runtime import reconcile,validate_evidence


class R3PostExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bundle={'context':{'label':'REMEDIATION'+'A'*16+'-1'}}
        self.evidence=dict(operation='r3_incident_evidence_v1',root_issue='root',source_task='source',
            controller_identity='a'*64,bundle_sha256=digest(self.bundle),r2_proof_sha256='b'*64,
            category='r3_controller_handle_missing',facts={'F01':'controller_handle_missing','F02':'delivery_not_verified'},
            execution_authorized=False,release_homologated=False)
        self.proposal=dict(action='request_experiment',experiment='observe_existing_controller',evidence_sha256=digest(self.evidence),
            reason='Observe only.',fact_ids=['F01','F02'],execution_authorized=False,release_homologated=False)
        self.state=dict(stage='experiment_pending',incident_sha256=digest(self.evidence),proposal=self.proposal,
            proposal_sha256=digest(self.proposal),review_task='review',review={'decision':'approve_experiment'},
            execution_authorized=False,release_homologated=False)
        result={'status':'passed','observation':'controller_absent','process_count':0}
        self.journal=dict(operation='r3_fixed_experiment_v1',identity=experiment_identity(self.evidence,self.state,self.bundle),
            incident_sha256=digest(self.evidence),experiment='observe_existing_controller',stage='experiment_recorded',
            result=result,result_sha256=digest(result),execution_authorized=False,release_homologated=False)
        save_receipt(self.root/'r3-experiments'/(self.journal['identity']+'.json'),self.journal)
        self.fx=Mock();self.fx.binding.return_value={'techlead':'tl','cto':'cto'}
        self.fx.issue.return_value={'id':'post-issue'};self.fx.remaining.return_value=206
        self.fx.wake.return_value={'id':'cto-wake'};self.fx.runs.return_value=[];self.fx.now.return_value=100

    def test_new_occurrence_binds_entire_receipt_and_preserves_original_lineage(self):
        value=next_evidence(self.evidence,self.state,self.bundle,self.journal)
        self.assertNotEqual(digest(value),digest(self.evidence))
        self.assertEqual(value['previous_incident_sha256'],digest(self.evidence))
        self.assertEqual(value['experiment_receipt_sha256'],digest(self.journal))
        self.assertEqual(value['experiment_result_sha256'],self.journal['result_sha256'])
        self.assertEqual(value['experiment_history'],['observe_existing_controller'])
        for key in ('source_task','root_issue','controller_identity','bundle_sha256','r2_proof_sha256'):
            self.assertEqual(value[key],self.evidence[key])
        self.assertEqual(value['facts']['F03'],'experiment_controller_absent')
        self.assertFalse(value['execution_authorized']);validate_evidence(value)

    def test_changed_result_obsolete_identity_raw_output_or_unknown_receipt_is_rejected(self):
        mutations=[lambda j:j['result'].update(process_count=1),lambda j:j.update(identity='c'*64),
            lambda j:j['result'].update(stdout='not public'),lambda j:j.update(stage='observation_pending'),
            lambda j:j.update(execution_authorized=True)]
        for mutate in mutations:
            journal=copy.deepcopy(self.journal);mutate(journal)
            with self.assertRaises(ValueError):next_evidence(self.evidence,self.state,self.bundle,journal)

    def test_noncontiguous_fact_ids_cannot_overwrite_a_previous_observation(self):
        evidence={**self.evidence,'facts':{'F01':'controller_handle_missing','F03':'delivery_not_verified'}}
        with self.assertRaises(ValueError):validate_evidence(evidence)

    def test_persisted_result_dispatches_cto_once_then_independent_techlead_review(self):
        self.assertEqual(reconcile_post(self.root,self.evidence,self.state,self.bundle,self.journal,effects=self.fx)['owner'],'cto')
        self.assertEqual(reconcile_post(self.root,self.evidence,self.state,self.bundle,self.journal,effects=self.fx)['stage'],'awaiting_diagnose')
        note=self.fx.wake.call_args.args[2]
        self.assertIn('CTO: decide from the fixed experiment',note)
        self.fx.runs.return_value=[{'id':'cto-task','wakeup_id':'cto-wake','status':'completed'}]
        value=next_evidence(self.evidence,self.state,self.bundle,self.journal)
        proposal={**self.proposal,'action':'propose_resume','experiment':'none','evidence_sha256':digest(value),'fact_ids':sorted(value['facts'])}
        self.fx.task.return_value=dict(id='cto-task',issue_id='post-issue',agent_id='cto',wakeup_id='cto-wake',
            status='completed',result={'output':json.dumps(proposal)})
        post=reconcile_post(self.root,self.evidence,self.state,self.bundle,self.journal,effects=self.fx)
        self.assertEqual(post['stage'],'review_dispatch');self.assertEqual(post['owner'],'techlead')
        self.fx.wake.return_value={'id':'tl-review-wake'}
        reconcile_post(self.root,self.evidence,self.state,self.bundle,self.journal,effects=self.fx)
        self.fx.runs.return_value=[{'id':'tl-task','wakeup_id':'tl-review-wake','status':'completed'}]
        review=dict(decision='approve_resume',proposal_sha256=digest(proposal),evidence_sha256=digest(value),
            reason='Subject to fixed current-state verification.',fact_ids=sorted(value['facts']),execution_authorized=False,release_homologated=False)
        self.fx.task.return_value=dict(id='tl-task',issue_id='post-issue',agent_id='tl',wakeup_id='tl-review-wake',
            status='completed',result={'output':json.dumps(review)})
        post=reconcile_post(self.root,self.evidence,self.state,self.bundle,self.journal,effects=self.fx)
        self.assertEqual(post['stage'],'resume_verification_pending');self.assertFalse(post['execution_authorized'])
        reconcile_post(self.root,self.evidence,self.state,self.bundle,self.journal,effects=self.fx)
        self.assertEqual(self.fx.wake.call_count,2)

    def test_repeated_experiment_without_new_inputs_retains_visible_hold(self):
        value=next_evidence(self.evidence,self.state,self.bundle,self.journal)
        reconcile(self.root,value,effects=self.fx);reconcile(self.root,value,effects=self.fx)
        proposal={**self.proposal,'evidence_sha256':digest(value),'fact_ids':sorted(value['facts'])}
        self.fx.runs.return_value=[{'id':'cto-task','wakeup_id':'cto-wake','status':'completed'}]
        self.fx.task.return_value=dict(id='cto-task',issue_id='post-issue',agent_id='cto',wakeup_id='cto-wake',
            status='completed',result={'output':json.dumps(proposal)})
        post=reconcile(self.root,value,effects=self.fx)
        self.assertEqual(post['stage'],'blocked');self.assertEqual(post['category'],'experiment_repeated_without_new_inputs')
        self.assertFalse(post['release_homologated'])

    def test_unpersisted_or_drifted_receipt_never_creates_post_handoff(self):
        other={**self.journal,'owner':'different'}
        with self.assertRaises(ValueError):reconcile_post(self.root,self.evidence,self.state,self.bundle,other,effects=self.fx)
        self.fx.issue.assert_not_called()

    def test_resume_cannot_smuggle_a_second_operation_into_one_decision(self):
        value=next_evidence(self.evidence,self.state,self.bundle,self.journal)
        reconcile(self.root,value,effects=self.fx);reconcile(self.root,value,effects=self.fx)
        proposal={**self.proposal,'action':'propose_resume','experiment':'verify_github_ci',
                  'evidence_sha256':digest(value),'fact_ids':sorted(value['facts'])}
        self.fx.runs.return_value=[{'id':'cto-task','wakeup_id':'cto-wake','status':'completed'}]
        self.fx.task.return_value=dict(id='cto-task',issue_id='post-issue',agent_id='cto',wakeup_id='cto-wake',
            status='completed',result={'output':json.dumps(proposal)})
        result=reconcile(self.root,value,effects=self.fx)
        self.assertEqual(result['stage'],'blocked');self.assertEqual(result['category'],'inconsistent_incident_operation')
        self.assertFalse(result['execution_authorized'])

    def test_supervisor_drives_real_persisted_evidence_into_one_cto_dispatch(self):
        with patch('r3_fixed_experiments.execute',return_value=self.journal) as experiment:
            result=drive(self.root,self.evidence,self.state,self.bundle,effects=self.fx)
            self.assertEqual(result['stage'],'diagnose_dispatch');self.assertEqual(result['owner'],'cto')
            self.assertEqual(result['experiment']['stage'],'experiment_recorded')
            drive(self.root,self.evidence,self.state,self.bundle,effects=self.fx)
            drive(self.root,self.evidence,self.state,self.bundle,effects=self.fx)
        self.fx.issue.assert_called_once();self.fx.wake.assert_called_once()
        self.assertFalse(result['release_homologated'])

    def test_next_experiment_receives_exact_persisted_state_not_display_metadata(self):
        value=next_evidence(self.evidence,self.state,self.bundle,self.journal)
        reconcile(self.root,value,effects=self.fx);reconcile(self.root,value,effects=self.fx)
        proposal={**self.proposal,'experiment':'verify_frozen_delivery','evidence_sha256':digest(value),'fact_ids':sorted(value['facts'])}
        self.fx.runs.return_value=[{'id':'cto-task','wakeup_id':'cto-wake','status':'completed'}]
        self.fx.task.return_value=dict(id='cto-task',issue_id='post-issue',agent_id='cto',wakeup_id='cto-wake',
            status='completed',result={'output':json.dumps(proposal)})
        reconcile(self.root,value,effects=self.fx)
        self.fx.wake.return_value={'id':'tl-wake'};reconcile(self.root,value,effects=self.fx)
        review=dict(decision='approve_experiment',proposal_sha256=digest(proposal),evidence_sha256=digest(value),reason='Inspect frozen delivery.',
            fact_ids=sorted(value['facts']),execution_authorized=False,release_homologated=False)
        self.fx.runs.return_value=[{'id':'tl-task','wakeup_id':'tl-wake','status':'completed'}]
        self.fx.task.return_value=dict(id='tl-task',issue_id='post-issue',agent_id='tl',wakeup_id='tl-wake',
            status='completed',result={'output':json.dumps(review)})
        reconcile(self.root,value,effects=self.fx)
        def experiment(private,selected,state,bundle,**kwargs):
            if digest(selected)==digest(self.evidence):return self.journal
            saved=json.loads((self.root/'r3-incidents'/(digest(selected)+'.json')).read_text())
            self.assertEqual(state,saved['state']);self.assertNotIn('experiment',state)
            return {'stage':'observation_pending'}
        with patch('r3_fixed_experiments.execute',side_effect=experiment):
            result=drive(self.root,self.evidence,self.state,self.bundle,effects=self.fx)
        self.assertEqual(result['stage'],'experiment_pending')
        self.assertEqual(result['experiment']['stage'],'observation_pending')
