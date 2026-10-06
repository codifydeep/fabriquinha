"""Controller fixtures, not native-agent or delivery evidence."""
import copy,json,unittest,sqlite3
import test_incremental_checkpoints as fixtures
from broker import incremental_checkpoints as ledger
from broker import admission_recovery
from broker import handoffs
from broker.source_harness_completion import proof_digest


class AdmissionRecoveryTests(unittest.TestCase):
    def test_handoff_can_participate_in_one_atomic_recovery_transaction(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);handoffs.initialize(con)
        con.execute('BEGIN IMMEDIATE')
        handoffs.save(con,'source','issue','test_revision_required','cto',{'approval':False},1,commit=False)
        self.assertTrue(con.in_transaction)
        con.rollback()
        self.assertEqual(con.execute('SELECT count(*) FROM delivery_handoffs').fetchone()[0],0)
        self.assertEqual(con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0],0)
    def setUp(self):
        self.f=fixtures.IncrementalCheckpointTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        r=self.f.source_harness_receipt()
        ledger.prepare_source_harness_revision(self.f.con,'source','U1',ledger.digest(r),lambda _:r)
        s=self.f.state();s['units']['U1'].update(stage='awaiting_green',red='8'*64,binding={'issue_id':'held'},
            test_review='6'*64,admission_hold=dict(owner='cto',review_task='old-review',delivery_approval=False))
        self.f.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(s),))
        self.receipt=dict(operation='cto_admission_recovery_v1',source_task='source',unit='U1',parent_issue='held',
            decision_task='fresh-cto',cto='cto',original_red='8'*64,proposal_sha256='a'*64,
            reason='Repair the driver and add executable negative controls.',admission_sha256='5'*64,review_task='old-review')

    def prepare(self,r=None):
        r=r or self.receipt
        return ledger.prepare_admission_recovery(self.f.con,'source','U1',ledger.digest(r),lambda _:r)

    def test_one_new_tests_only_revision_preserves_hold_and_history(self):
        old=self.f.state();s=self.prepare();u=s['units']['U1']
        self.assertEqual(u['revision'],4);self.assertEqual(u['stage'],'awaiting_red')
        self.assertEqual(u['history'][-1],{k:v for k,v in old['units']['U1'].items() if k!='history'})
        self.assertEqual(s['units']['U2'],old['units']['U2'])
        self.assertEqual(u['baseline_test_sha256'],old['units']['U1']['baseline_test_sha256'])
        self.assertEqual(u['admission_hold']['recovery_state'],'tests_only')
        self.assertFalse(s['execution_authorized']);self.assertEqual(s,self.prepare())
        for k in ('red','green','test_review','delivery_review','binding'):self.assertNotIn(k,u)

    def test_rejects_old_cto_foreign_review_hash_and_author(self):
        before=self.f.state()
        for k,v in [('decision_task','new-source-diagnosis'),('review_task','other'),('original_red','0'*64),
                    ('parent_issue','other'),('cto','author'),('admission_sha256','invalid')]:
            with self.subTest(k=k),self.assertRaises(ValueError):self.prepare({**self.receipt,k:v})
        self.assertEqual(self.f.state(),before)
        self.prepare()
        with self.assertRaises(ValueError):self.prepare({**self.receipt,'decision_task':'another'})

    def test_controls_completion_requires_new_frozen_evidence_and_is_bounded(self):
        self.prepare();s=self.f.state();s['units']['U1']['binding']={'issue_id':'controls-parent'}
        self.f.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(s),))
        r={**self.receipt,'operation':'cto_controls_completion_v1','decision_task':'controls-cto',
            'parent_issue':'controls-parent','original_red':'2'*64,'captured_red_sha256':'2'*64,
            'rejected_manifest_sha256':'3'*64,'admission_sha256':'4'*64}
        for k,v in [('decision_task','fresh-cto'),('captured_red_sha256','0'*64),('admission_sha256','5'*64)]:
            with self.subTest(k=k),self.assertRaises(ValueError):self.prepare({**r,k:v})
        after=self.prepare(r);self.assertEqual(after['units']['U1']['revision'],5)
        self.assertEqual(after['units']['U1']['history'][-1]['revision'],4)
        self.assertFalse(after['execution_authorized']);self.assertIn('admission_hold',after['units']['U1'])
        with self.assertRaises(ValueError):self.prepare({**r,'decision_task':'repeat'})

    def test_hold_survives_red_and_is_released_only_by_fresh_independent_review(self):
        self.prepare()
        _,red=self.f.red();red.update(task_id='fresh-red',manifest_sha256='4'*64)
        self.f.apply(ledger.digest(red),red)
        u=self.f.state()['units']['U1'];self.assertIn('admission_hold',u)
        bad=self.f.event('test_review',reviewer='author',task_id='self-review',manifest_sha256='4'*64,
            red_receipt_sha256=u['red'],decision='approve')
        with self.assertRaises(ValueError):self.f.apply(*bad)
        self.assertIn('admission_hold',self.f.state()['units']['U1'])
        self.f.apply(*self.f.event('test_review',reviewer='lead',task_id='fresh-review',manifest_sha256='4'*64,
            red_receipt_sha256=u['red'],decision='approve'))
        u=self.f.state()['units']['U1'];self.assertNotIn('admission_hold',u)
        self.assertEqual(u['stage'],'awaiting_green');self.assertNotIn('green',u)
        self.assertEqual(len(u['admission_hold_history']),1)

    def data(self):
        proof=dict(operation='source_harness_structure_v1',approval=False,candidate_test_sha256='a'*64,
            previous_test_sha256='b'*64,driver_changed=False,added_methods=[],removed_methods=[],
            inverted_chronology=True,current_first_fifo=True)
        route=dict(issue_id='held',cto='cto',enabled=False,test_first_files=['tests/new.py'])
        data=dict(source_task='author',target='cto',dispatch_stage='diagnose_cto',wakeup_id='wake',
            validation_failure=dict(category='source_harness_admission_failure',volume='frozen',source_task='author',
                output_sha256=proof_digest(proof),diagnostic_read_files=[]),
            harness_diagnosis=dict(source_task='author',approval=False,output_sha256=proof_digest(proof),
                file_sha256={'tests/new.py':'a'*64},findings=['Driver remains unchanged.']),
            source_harness_admission=dict(proof=proof,candidate_volume='frozen',source_task='author',
                trial=dict(issue_id='held',old_red={'red':{'test_sha256':{'tests/new.py':'b'*64}}}),
                red=dict(issue_id='held',volume='red',red={'test_sha256':{'tests/new.py':'a'*64}})))
        task=dict(id='fresh-cto',status='completed',agent_id='cto',issue_id='held',wakeup_id='wake')
        decision=dict(action='request_test_revision',optional_files=[],reason='Repair the harness.')
        reads={'/evidence/candidate/tests/new.py':dict(lines=699,total_lines=699)}
        return route,data,task,decision,reads

    def test_cto_requires_full_reads_exact_wakeup_and_disabled_old_route(self):
        args=self.data();self.assertEqual(len(admission_recovery.qualify_cto(*args)),1)
        for index,key,val in [(0,'enabled',True),(2,'wakeup_id','other'),(2,'agent_id','author'),
                              (3,'action','request_correction'),(3,'optional_files',['app.js'])]:
            changed=list(copy.deepcopy(args));changed[index][key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):admission_recovery.qualify_cto(*changed)
        changed=list(copy.deepcopy(args));changed[-1]={}
        with self.assertRaises(ValueError):admission_recovery.qualify_cto(*changed)
