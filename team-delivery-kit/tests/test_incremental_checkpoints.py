"""Controller ledger qualification only; fixtures are NOT delivery evidence."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from broker import incremental_checkpoints as checkpoints


class IncrementalCheckpointTests(unittest.TestCase):
    def source_harness_receipt(self):
        first=self.repair_receipt()
        checkpoints.prepare_test_repair(self.con,'source','U1',checkpoints.digest(first),lambda _:first)
        state=self.state()
        state['units']['U1'].update(stage='awaiting_green',red='8'*64,binding={'issue_id':'revision-two'})
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(state),))
        return {**first,'operation':'cto_source_harness_revision_v1','parent_issue':'revision-two',
                'original_red':'8'*64,'decision_task':'new-source-diagnosis','harness_sha256':'7'*64}

    def test_source_harness_revision_preserves_history_and_requires_all_fresh_gates(self):
        receipt=self.source_harness_receipt();before=self.state()
        sha=checkpoints.digest(receipt)
        state=checkpoints.prepare_source_harness_revision(self.con,'source','U1',sha,lambda _:receipt)
        unit=state['units']['U1']
        self.assertEqual(unit['revision'],3)
        self.assertEqual(unit['history'][-1],{k:v for k,v in before['units']['U1'].items() if k!='history'})
        self.assertEqual(unit['baseline_test_sha256'],before['units']['U1']['baseline_test_sha256'])
        self.assertEqual(state['units']['U2'],before['units']['U2'])
        self.assertFalse(state['execution_authorized'])
        for field in ['red','test_review','green','delivery_review','binding']:
            self.assertNotIn(field,unit)
        self.assertEqual(state,checkpoints.prepare_source_harness_revision(self.con,'source','U1',sha,lambda _:receipt))

    def test_source_harness_revision_rejects_stale_sponsorship_and_fake_evidence(self):
        receipt=self.source_harness_receipt();before=self.state()
        for field,value in [('decision_task','diagnosis'),('parent_issue','other'),('original_red','0'*64),
                            ('harness_sha256','not-a-hash'),('cto','author')]:
            bad={**receipt,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):
                checkpoints.prepare_source_harness_revision(self.con,'source','U1',checkpoints.digest(bad),lambda _:bad)
        self.assertEqual(self.state(),before)
    def test_dependent_test_repair_preserves_checkpoint_base_and_unrelated_units(self):
        receipt=self.repair_receipt()
        config,state=map(json.loads,self.con.execute('SELECT config,state FROM incremental_checkpoints').fetchone())
        candidate=copy.deepcopy(state['units']['U1']);candidate['id']='U3'
        state['units']['U3']=candidate
        config['units'].append(dict(id='U3',depends_on=['U2'],criteria=['C03'],objective='Third'))
        for uid in ('U1','U2'):
            state['units'][uid].update(stage='checkpointed',green_manifest_sha256=candidate['base_manifest_sha256'])
        state['execution_units']=['U1','U2','U3']
        before=copy.deepcopy(state['units']['U2'])
        self.con.execute('UPDATE incremental_checkpoints SET config=?,state=?',(json.dumps(config),json.dumps(state)))
        receipt['unit']='U3'
        result=checkpoints.prepare_test_repair(self.con,'source','U3',checkpoints.digest(receipt),lambda _:receipt)
        self.assertEqual(result['units']['U2'],before)
        self.assertEqual(result['units']['U3']['base_manifest_sha256'],candidate['base_manifest_sha256'])
        self.assertEqual(result['units']['U3']['baseline_test_sha256'],candidate['baseline_test_sha256'])
        self.assertEqual(result['units']['U3']['revision'],2)
        self.assertNotIn('U3',result['execution_units'])
        self.assertEqual(result['units']['U3']['history'][-1]['red'],candidate['red'])

    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.addCleanup(self.con.close)
        self.units = [dict(id='U1', depends_on=[], criteria=['C01'], objective='First'),
                      dict(id='U2', depends_on=['U1'], criteria=['C02'], objective='Second')]
        checkpoints.initialize(self.con)
        config = dict(source_task='source', issue_id='issue', author='author', cto='cto',
                      criteria={'C01': 'First', 'C02': 'Second'})
        state = dict(stage='proposal_ready', task_id='cto-task', certificate=dict(
            source_task='source', decision_task='cto-task', proposal_sha256='a'*64,
            normalized_units=self.units, execution_authorized=False,
            delivery_approval=False, baseline_edits_allowed=False))
        self.con.execute('CREATE TABLE test_decompositions(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
        self.con.execute('INSERT INTO test_decompositions VALUES(?,?,?)',
                         ('source', json.dumps(config), json.dumps(state)))
        self.policy = dict(author='author', test_reviewer='lead', delivery_reviewer='cto',
                           base_manifest_sha256='b'*64, baseline_test_sha256={'tests/old.py': 'c'*64},
                           baseline_test_count=1, suite_sha256='d'*64)
        self.register()

    def test_dependent_repair_rejects_unapproved_or_different_predecessor(self):
        receipt=self.repair_receipt()
        config,state=map(json.loads,self.con.execute('SELECT config,state FROM incremental_checkpoints').fetchone())
        candidate=copy.deepcopy(state['units']['U1']);candidate['id']='U3'
        state['units']['U3']=candidate
        config['units'].append(dict(id='U3',depends_on=['U2'],criteria=['C03'],objective='Third'))
        receipt['unit']='U3'
        for stage,sha in [('awaiting_green',candidate['base_manifest_sha256']),('checkpointed','0'*64)]:
            state['units']['U2'].update(stage=stage,green_manifest_sha256=sha)
            self.con.execute('UPDATE incremental_checkpoints SET config=?,state=?',(json.dumps(config),json.dumps(state)))
            before=self.state()
            with self.assertRaisesRegex(ValueError,'exact approved predecessor'):
                checkpoints.prepare_test_repair(self.con,'source','U3',checkpoints.digest(receipt),lambda _:receipt)
            self.assertEqual(before,self.state())

    def register(self):
        return checkpoints.register(self.con, 'source', self.policy)

    def state(self):
        return checkpoints.status(self.con, 'source')

    def event(self, operation, unit='U1', **fields):
        # Trusted resolver fixture only; no worker-facing event API exists.
        record = dict(operation=operation, source_task='source', unit=unit,
                      proposal_sha256='a'*64, base_manifest_sha256='b'*64,
                      suite_sha256='d'*64)
        record.update(fields)
        ref = checkpoints.digest(record)
        return ref, record

    def apply(self, ref, record):
        return checkpoints.record(self.con, 'source', ref, lambda requested: copy.deepcopy(record))

    def red(self, unit='U1', base='b'*64):
        return self.event('red', unit, author='author', task_id='red-'+unit,
            base_manifest_sha256=base, manifest_sha256='e'*64,
            test_sha256={'tests/new_'+unit+'.py': 'f'*64},
            baseline_test_sha256={'tests/old.py': 'c'*64},
            exit_code=1, qualified_new_test_failure=True,
            previous_checkpoint_green=True, test_count=2 if unit=='U1' else 3)

    def advance_to_review(self):
        self.apply(*self.red())
        self.apply(*self.event('test_review', reviewer='lead', task_id='review-tests',
            manifest_sha256='e'*64, red_receipt_sha256=self.state()['units']['U1']['red'],
            decision='approve'))
        self.apply(*self.event('green', author='author', task_id='green-U1',
            manifest_sha256='1'*64, red_manifest_sha256='e'*64,
            test_sha256={'tests/new_U1.py':'f'*64},
            baseline_test_sha256={'tests/old.py':'c'*64},
            exit_code=0, full_suite=True, test_count=2))

    def complete_first(self):
        self.advance_to_review()
        self.apply(*self.event('delivery_review', reviewer='cto', task_id='review-delivery',
            manifest_sha256='1'*64, green_receipt_sha256=self.state()['units']['U1']['green'],
            decision='approve'))

    def test_registration_is_idempotent_but_not_execution_authority(self):
        self.assertEqual(self.register(), self.state())
        self.assertEqual(self.state()['stage'], 'awaiting_runtime_binding')
        self.assertFalse(self.state()['execution_authorized'])
        self.assertFalse(self.state()['delivery_approval'])
        self.assertEqual(self.state()['units']['U2']['stage'], 'waiting_dependency')

    def repair_receipt(self):
        self.apply(*self.red())
        self.apply(*self.event('test_review', reviewer='lead', task_id='review-tests',
            manifest_sha256='e'*64, red_receipt_sha256=self.state()['units']['U1']['red'], decision='approve'))
        state = self.state()
        state['units']['U1']['binding'] = {'issue_id':'old-unit'}
        state.update(execution_authorized=True, activation={'issue_id':'old-unit'})
        self.con.execute('UPDATE incremental_checkpoints SET state=?', (json.dumps(state),))
        return dict(operation='cto_test_repair_v1', source_task='source', unit='U1',
            parent_issue='old-unit', decision_task='diagnosis', cto='cto',
            original_red=state['units']['U1']['red'], output_sha256='9'*64,
            proposal_sha256='a'*64, reason='Repair new parser harness; preserve assertions')

    def test_cto_repair_preserves_history_but_requires_fresh_binding_red_review(self):
        receipt = self.repair_receipt()
        previous = self.state()['units']['U1']
        sha = checkpoints.digest(receipt)
        result = checkpoints.prepare_test_repair(self.con, 'source', 'U1', sha, lambda _:receipt)
        unit = result['units']['U1']
        self.assertEqual(unit['history'], [previous])
        self.assertEqual(unit['revision'], 2)
        self.assertEqual(unit['stage'], 'awaiting_red')
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(result['units']['U2']['stage'], 'waiting_dependency')
        for field in ('binding','red','test_review','green','delivery_review'):
            self.assertNotIn(field, unit)
        self.assertEqual(result, checkpoints.prepare_test_repair(self.con, 'source', 'U1', sha, lambda _:receipt))
        self.assertEqual(unit['baseline_test_sha256'], self.policy['baseline_test_sha256'])

    def test_cto_repair_rejects_stale_lineage_and_unverified_receipts(self):
        receipt = self.repair_receipt()
        before = self.state()
        for key, value in [('parent_issue','other'), ('original_red','0'*64),
                           ('cto','author'), ('proposal_sha256','0'*64),
                           ('operation','test_review'), ('decision_task','')]:
            altered = {**receipt, key:value}
            with self.assertRaises(ValueError):
                checkpoints.prepare_test_repair(self.con, 'source', 'U1', checkpoints.digest(altered), lambda _:altered)
        with self.assertRaises(ValueError):
            checkpoints.prepare_test_repair(self.con, 'source', 'U1', '0'*64, lambda _:receipt)
        self.assertEqual(before, self.state())

    def test_cto_repair_cannot_repeat_with_another_diagnosis(self):
        receipt = self.repair_receipt()
        checkpoints.prepare_test_repair(self.con, 'source', 'U1', checkpoints.digest(receipt), lambda _:receipt)
        other = {**receipt, 'decision_task':'other-diagnosis'}
        with self.assertRaises(ValueError):
            checkpoints.prepare_test_repair(self.con, 'source', 'U1', checkpoints.digest(other), lambda _:other)

    def test_conflicting_policy_and_scope_are_rejected(self):
        with self.assertRaises(ValueError):
            checkpoints.register(self.con, 'source', {**self.policy, 'test_reviewer':'author'})
        with self.assertRaises(ValueError):
            checkpoints.register(self.con, 'source', {**self.policy, 'suite_sha256':'0'*64})
        row=self.con.execute('SELECT state FROM test_decompositions').fetchone()
        state=json.loads(row[0]); state['certificate']['normalized_units'][1]['criteria']=['C01']
        self.con.execute('UPDATE test_decompositions SET state=?',(json.dumps(state),))
        with self.assertRaises(ValueError):self.register()

    def test_dependency_cannot_run_before_exact_prior_checkpoint(self):
        with self.assertRaises(ValueError):self.apply(*self.red('U2'))
        self.complete_first()
        with self.assertRaises(ValueError):self.apply(*self.red('U2'))
        ref,record=self.red('U2', '1'*64)
        record['baseline_test_sha256']['tests/new_U1.py']='f'*64
        self.apply(checkpoints.digest(record),record)
        self.assertEqual(self.state()['units']['U2']['stage'],'awaiting_test_review')

    def test_missing_real_red_and_changed_baseline_rejected(self):
        for key,value in [('exit_code',0),('qualified_new_test_failure',False),
                          ('previous_checkpoint_green',False),('baseline_test_sha256',{})]:
            _,record=self.red();record[key]=value
            with self.assertRaises(ValueError):self.apply(checkpoints.digest(record),record)
        self.assertEqual(self.state()['units']['U1']['stage'],'awaiting_red')

    def test_review_is_independent_and_snapshot_bound(self):
        self.apply(*self.red())
        for reviewer,manifest in [('author','e'*64),('lead','0'*64)]:
            with self.assertRaises(ValueError):
                self.apply(*self.event('test_review', reviewer=reviewer, task_id='review',
                    manifest_sha256=manifest, red_receipt_sha256=self.state()['units']['U1']['red'], decision='approve'))

    def test_green_cannot_change_tests_or_use_partial_suite(self):
        self.apply(*self.red())
        self.apply(*self.event('test_review', reviewer='lead',task_id='review-tests',
            manifest_sha256='e'*64,red_receipt_sha256=self.state()['units']['U1']['red'],decision='approve'))
        for fields in [dict(test_sha256={}),dict(full_suite=False),dict(test_count=1),dict(exit_code=1)]:
            record=dict(author='author', task_id='green',manifest_sha256='1'*64,
                red_manifest_sha256='e'*64,test_sha256={'tests/new_U1.py':'f'*64},
                baseline_test_sha256={'tests/old.py':'c'*64},exit_code=0,full_suite=True,test_count=2)
            record.update(fields)
            with self.assertRaises(ValueError):self.apply(*self.event('green',**record))

    def test_checkpoint_unlocks_next_not_delivery_or_release(self):
        self.complete_first()
        state=self.state()
        self.assertEqual(state['units']['U1']['stage'],'checkpointed')
        self.assertEqual(state['units']['U2']['stage'],'awaiting_red')
        self.assertEqual(state['units']['U2']['base_manifest_sha256'],'1'*64)
        self.assertFalse(state['delivery_approval'])
        self.assertFalse(state['execution_authorized'])

    def test_receipt_idempotency_survives_reload_and_requires_original_evidence(self):
        ref,record=self.red();self.apply(ref,record)
        state=self.state()
        self.assertEqual(self.apply(ref,record),state)
        bad={**record,'manifest_sha256':'0'*64}
        with self.assertRaises(ValueError):self.apply(ref,bad)
        self.assertEqual(self.state(),state)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM incremental_checkpoint_events').fetchone()[0],1)

    def test_changes_requested_blocks_without_automatic_repeat(self):
        self.apply(*self.red())
        self.apply(*self.event('test_review', reviewer='lead', task_id='request-change',
            manifest_sha256='e'*64, red_receipt_sha256=self.state()['units']['U1']['red'],
            decision='request_changes'))
        self.assertEqual(self.state()['units']['U1']['stage'],'blocked')
        self.assertEqual(self.state()['units']['U1']['owner'],'author')
        _,retry=self.red();retry['task_id']='new-red-attempt'
        with self.assertRaises(ValueError):self.apply(checkpoints.digest(retry),retry)

    def test_unsupported_operation_and_foreign_binding_rejected(self):
        for fields in [dict(operation='homologate'),dict(proposal_sha256='0'*64),dict(author='cto')]:
            _,record=self.red();record.update(fields)
            with self.assertRaises(ValueError):self.apply(checkpoints.digest(record),record)

    def test_missing_resolver_evidence_rejected_without_partial_transition(self):
        with self.assertRaises(ValueError):
            checkpoints.record(self.con,'source','0'*64,lambda ref:None)
        self.assertEqual(self.state()['units']['U1']['stage'],'awaiting_red')

    def test_transaction_failure_does_not_write_event(self):
        self.con.execute("CREATE TRIGGER fail_event BEFORE INSERT ON incremental_checkpoint_events BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.apply(*self.red())
        self.assertEqual(self.state()['units']['U1']['stage'],'awaiting_red')

    def test_file_database_restart_preserves_evidence_and_prevents_duplicate_handoff(self):
        self.complete_first()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checkpoints.sqlite'
            destination=sqlite3.connect(path)
            self.con.commit()
            self.con.backup(destination)
            destination.close()
            restarted=sqlite3.connect(path)
            self.addCleanup(restarted.close)
            self.assertEqual(checkpoints.status(restarted,'source'),self.state())
            ref,record=self.red()
            self.assertEqual(checkpoints.record(restarted,'source',ref,lambda requested:record),self.state())
            self.assertEqual(restarted.execute('SELECT COUNT(*) FROM incremental_checkpoint_events').fetchone()[0],4)
            self.assertEqual(restarted.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_one_native_execution_cannot_certify_multiple_operations(self):
        self.apply(*self.red())
        with self.assertRaises(ValueError):
            self.apply(*self.event('test_review',reviewer='lead',task_id='red-U1',
                manifest_sha256='e'*64,red_receipt_sha256=self.state()['units']['U1']['red'],decision='approve'))

    def test_new_revision_preserves_rejected_evidence_and_rejects_stale_approval(self):
        self.apply(*self.red())
        rejection,record=self.event('test_review',reviewer='lead',task_id='reject-1',
            manifest_sha256='e'*64,red_receipt_sha256=self.state()['units']['U1']['red'],decision='request_changes')
        self.apply(rejection,record)
        state=checkpoints.prepare_revision(self.con,'source','U1',rejection)
        self.assertEqual(state['units']['U1']['revision'],2)
        self.assertEqual(state['units']['U1']['history'][0]['test_review'],rejection)
        self.assertEqual(checkpoints.prepare_revision(self.con,'source','U1',rejection),state)
        _,new=self.red();new['task_id']='red-revised';new['manifest_sha256']='9'*64
        self.apply(checkpoints.digest(new),new)
        with self.assertRaises(ValueError):
            self.apply(*self.event('test_review',reviewer='lead',task_id='stale-review',
                manifest_sha256='e'*64,red_receipt_sha256=self.state()['units']['U1']['history'][0]['red'],decision='approve'))
        second,record=self.event('test_review',reviewer='lead',task_id='reject-2',
            manifest_sha256='9'*64,red_receipt_sha256=self.state()['units']['U1']['red'],decision='request_changes')
        self.apply(second,record)
        with self.assertRaises(ValueError):checkpoints.prepare_revision(self.con,'source','U1',second)

    def test_full_completion_still_requires_integration_and_qa(self):
        self.complete_first()
        _,red=self.red('U2','1'*64);red['baseline_test_sha256']['tests/new_U1.py']='f'*64
        self.apply(checkpoints.digest(red),red)
        self.apply(*self.event('test_review','U2',base_manifest_sha256='1'*64,
            reviewer='lead',task_id='review-tests-U2',manifest_sha256='e'*64,
            red_receipt_sha256=self.state()['units']['U2']['red'],decision='approve'))
        self.apply(*self.event('green','U2',base_manifest_sha256='1'*64,author='author',
            task_id='green-U2',manifest_sha256='2'*64,red_manifest_sha256='e'*64,
            test_sha256={'tests/new_U2.py':'f'*64},baseline_test_sha256=red['baseline_test_sha256'],
            exit_code=0,full_suite=True,test_count=3))
        self.apply(*self.event('delivery_review','U2',base_manifest_sha256='1'*64,
            reviewer='cto',task_id='review-delivery-U2',manifest_sha256='2'*64,
            green_receipt_sha256=self.state()['units']['U2']['green'],decision='approve'))
        self.assertEqual(self.state()['stage'],'awaiting_integration_qa')
        self.assertFalse(self.state()['delivery_approval'])
