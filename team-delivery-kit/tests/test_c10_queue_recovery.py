import copy
import unittest
from broker import c10_queue_recovery as recovery, c10_status_admission as status
from broker import c10_checkpoint_contract as gates, suite_failure
import test_c10_status_admission as status_tests


class QueueRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture=status_tests.C10StatusAdmissionTests();fixture.setUp()
        self.state=fixture.authorized()
        cp=self.state['c10_checkpoints'];cp['atomic_contract']='c10-status-observations-v1'
        self.state.update(stage='blocked',category='c10_checkpoint_acceptance_failed',author_task='atomic-author',
            snapshot={'volume':'atomic','task_id':'atomic-author'},
            validation=dict(self.state['validation'],test_sha256='f'*64))
        cp['scope_receipt']={'schema':gates.SCHEMA,'phase':'STATUS','scope_verified':True,
            'seed_test_sha256':cp['seed']['validation']['test_sha256'],'test_sha256':'f'*64,
            'manifest_sha256':self.state['validation']['manifest_sha256'],'delivery_approval':False}
        self.output=('FAIL: '+gates.C10+' (tests.test_incremental_u3.DriverTests)\n'
            'AssertionError: 1 != 0 : every issued request must be resolved by the harness\n'
            'Ran 259 tests in 1.0s\nFAILED (failures=1)\n')
        self.state['suite_failure']=suite_failure.evidence(1,self.output,'atomic-author','atomic')
        self.state['suite_failure']['diagnostic_read_files']=['app/static/app.js','app/static/index.html','tests/test_incremental_u3.py']
        self.state=status.prepare_queue_diagnosis(self.state,self.output)
        self.state.update(stage='blocked',category='c10_status_queue_plan_rejected',
            functional_diagnosis_receipt={'certificate':{'decision_sha256':'d'*64},'decision':{'reason':'wrong order'}})
        self.state['c10_status_queue_intake']['plan_verification']={
            'status':'rejected','cto_decision_sha256':'d'*64,
            'diagnostic_program_sha256':'e'*64}
        self.trace={'schema':'c10-queue-diagnostic-v1','test_sha256':'f'*64,
            'instrumented_program_sha256':'e'*64,'snapshot_modified':False,'functional_green':False,
            'delivery_approval':False,'pending_left':1,'remaining_urls':['/feedback?q=gamma'],
            'trace':[{'op':'oldest','urls':['/feedback?q=beta','/feedback?q=gamma','/feedback?q=delta']},
                {'op':'newest','urls':['/feedback?q=gamma','/feedback?q=delta']},
                {'op':'newest','urls':['/feedback?q=gamma','/feedback?status=open?q=delta','/feedback?status=completed?q=delta']},
                {'op':'newest','urls':['/feedback?q=gamma','/feedback?status=open?q=delta']}]}

    def test_trace_feedback_preserves_failed_attempt_and_has_no_authority(self):
        original=copy.deepcopy(self.state)
        revised=recovery.prepare(self.state,self.output,self.trace)
        self.assertEqual(self.state,original)
        self.assertEqual(revised['c10_checkpoints'],original['c10_checkpoints'])
        intake=revised['c10_queue_trace_feedback']
        self.assertEqual(intake['prior_receipt'],original['functional_diagnosis_receipt'])
        self.assertEqual(intake['attempt_limit'],1)
        self.assertFalse(intake['author_scope_authorized'])
        self.assertFalse(revised['delivery_approval'])
        self.assertNotIn('functional_diagnosis_receipt',revised)
        note=revised['functional_diagnosis']['note']
        self.assertIn('beta,gamma,delta',note)
        self.assertIn('no line526',note)
        self.assertIn('before manual resolution',note)
        self.assertEqual(revised['stage'],'maintenance_functional_diagnosis_dispatch')

    def test_repeated_intake_or_stale_receipt_is_rejected(self):
        revised=recovery.prepare(self.state,self.output,self.trace)
        with self.assertRaises(ValueError):recovery.prepare(revised,self.output,self.trace)
        for mutation in ('category','decision','green','task'):
            state=copy.deepcopy(self.state)
            if mutation=='category':state['category']='other'
            if mutation=='decision':state['functional_diagnosis_receipt']['certificate']['decision_sha256']='old'
            if mutation=='green':state['delivery_approval']=True
            if mutation=='task':state['author_task']='old'
            with self.assertRaises(ValueError):recovery.prepare(state,self.output,self.trace)

    def test_trace_drift_fabricated_green_or_wrong_order_is_rejected(self):
        for mutation in ('test','program','pending','green','write','order','missing','tail'):
            trace=copy.deepcopy(self.trace)
            if mutation=='test':trace['test_sha256']='other'
            if mutation=='program':trace['instrumented_program_sha256']='other'
            if mutation=='pending':trace['pending_left']=0
            if mutation=='green':trace['functional_green']=True
            if mutation=='write':trace['snapshot_modified']=True
            if mutation=='order':trace['trace'][0]['urls'].reverse()
            if mutation=='missing':trace['trace']=[]
            if mutation=='tail':trace['trace'].reverse()
            with self.assertRaises(ValueError):recovery.prepare(self.state,self.output,trace)

    def test_full_suite_failure_is_reparsed_not_trusted_as_text(self):
        for output in (self.output.replace('259','258'),self.output.replace('1 != 0','2 != 0')):
            with self.assertRaises(ValueError):recovery.prepare(self.state,output,self.trace)

    def feedback(self):
        state=recovery.prepare(self.state,self.output,self.trace)
        report={'classification':'DRIVER_OBSERVATION','decision':{'action':'request_test_revision','reason':'open GET unresolved'},
            'certificate':{'decision_sha256':'a'*64,'task_id':'new-cto','snapshot':'atomic','test_sha256':'f'*64}}
        state.update(stage='blocked',category='maintenance_diagnosis_driver_observation',functional_diagnosis_receipt=report)
        return state

    def test_rejection_is_exact_evidence_bound_and_cannot_approve_or_replay(self):
        state=self.feedback()
        revised=recovery.reject(state,'a'*64,'Current plan calls the remaining request open; observed remaining request is gamma.')
        self.assertEqual(revised['category'],'c10_queue_trace_plan_rejected')
        self.assertEqual(revised['functional_diagnosis_receipt'],state['functional_diagnosis_receipt'])
        self.assertFalse(revised['c10_queue_trace_feedback']['plan_verification']['author_authorized'])
        self.assertFalse(revised['delivery_approval'])
        with self.assertRaises(ValueError):recovery.reject(revised,'a'*64,'replay')
        with self.assertRaises(ValueError):recovery.reject(state,'b'*64,'stale decision')
        with self.assertRaises(ValueError):recovery.reject(state,'a'*64,'')

    def test_rejection_cannot_apply_to_changed_snapshot_or_pending_analysis(self):
        for field,value in (('stage','awaiting_cto_diagnosis'),('snapshot',{'volume':'other'}),
                ('validation',{'test_sha256':'other'})):
            state=self.feedback();state[field]=value
            with self.assertRaises(ValueError):recovery.reject(state,'a'*64,'observed contradiction')
