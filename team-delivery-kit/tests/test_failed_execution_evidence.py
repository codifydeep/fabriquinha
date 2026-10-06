import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_failed_execution_diagnosis as fixtures
from broker import handoffs, native
from broker.failed_execution_evidence import register, register_trace


class FailedExecutionEvidenceTests(unittest.TestCase):
    db = fixtures.FailedExecutionDiagnosisTests.db
    run_register = fixtures.FailedExecutionDiagnosisTests.run_register

    def setUp(self):
        fixtures.FailedExecutionDiagnosisTests.setUp(self)
        self.run_register()
        self.output = 'saved output'
        self.digest = hashlib.sha256(self.output.encode()).hexdigest()
        self.decision = '01a0fd74-5396-77d9-bfaa-250baab8cd6a'
        self.evidence_payload = {'source_task': self.source, 'decision_task': self.decision,
                                 'output_sha256': self.digest}
        self.runs.append({'id': self.decision, 'agent_id': 'cto', 'status': 'completed'})
        self.broker.PREFIX = 'delivery-kit-test'
        self.broker.OWNER = 'owner'
        self.broker.docker = lambda *_: {'Labels': {'delivery-kit.owner': 'owner',
            'delivery-kit.source-task': self.source, 'delivery-kit.diagnostic-only': 'true'}}
        with self.db() as con:
            row = handoffs.load(con, self.source)
            data = json.loads(row['data'])
            data['validation_failure']['output_sha256'] = self.digest
            data['failed_execution_diagnostic']['failure']['output_sha256'] = self.digest
            con.execute('UPDATE failed_execution_diagnoses SET receipt=?',
                        (json.dumps(data['failed_execution_diagnostic']),))
            data.update(target='cto', recipient_task=self.decision,
                        decision={'action': 'escalate_cto', 'reason': 'need assertions', 'optional_files': []})
            handoffs.save(con, self.source, 'issue', 'technical_decision_required', 'cto', data, 200)
            con.execute('CREATE TABLE frozen_suite_failures(task_id TEXT,output_sha256 TEXT,output TEXT)')
            con.execute('INSERT INTO frozen_suite_failures VALUES (?,?,?)', (self.source, self.digest, self.output))
            con.execute('CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)')
            con.execute('INSERT INTO test_first_red VALUES (?,?)', ('issue', json.dumps({'red': {'test_sha256': {}}})))
            con.execute('CREATE TABLE failed_execution_snapshots(task_id TEXT,volume TEXT,status TEXT)')
            con.execute('INSERT INTO failed_execution_snapshots VALUES (?,?,?)', (self.source, 'diagnostic', 'complete'))
        self.proof = {'output_sha256': self.digest, 'manifest_sha256': 'b' * 64,
                      'witnesses': [{'qualified_name': 'tests.test_new.C.test_new',
                                     'observed': ['fixture'], 'expected': []}], 'fixture_literals_only': True}

    def enrich(self):
        with patch.object(native, 'issue_task_runs', return_value=self.runs), \
             patch('broker.failed_execution_evidence.capture', return_value=self.proof) as capture:
            result = register(self.broker, self.evidence_payload)
            return result, capture

    def test_enrichment_is_idempotent_and_preserves_prior_decision(self):
        receipt, capture = self.enrich()
        capture.assert_called_once()
        second, capture = self.enrich()
        capture.assert_not_called()
        self.assertEqual(receipt, second)
        self.assertEqual(receipt['prior_decision']['action'], 'escalate_cto')
        self.assertEqual(receipt['status'], 'evidence_only_not_approved')
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'diagnose_cto')
            self.assertEqual(con.execute('SELECT count(*) FROM snapshots').fetchone()[0], 0)

    def test_tampered_saved_output_rejected(self):
        with self.db() as con:
            con.execute("UPDATE frozen_suite_failures SET output='tampered'")
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.enrich()

    def test_running_worker_blocks_enrichment(self):
        with self.db() as con:
            con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.enrich()

    def test_wrong_decision_cannot_enrich(self):
        self.evidence_payload['decision_task'] = '01a0fd74-5396-77d9-bfaa-250baab8cd6b'
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.enrich()

    def test_empty_witnesses_do_not_trigger_retry(self):
        self.proof['witnesses'] = []
        with self.assertRaisesRegex(ValueError, 'no new'):
            self.enrich()

    def trace_fixture(self):
        with self.db() as con:
            con.execute('ALTER TABLE leases ADD COLUMN request_id TEXT')
            con.execute("INSERT INTO leases VALUES('closed','execution')")
            con.execute('CREATE TABLE native_bindings(task_id TEXT,request_id TEXT)')
            con.execute('INSERT INTO native_bindings VALUES(?,?)',(self.source,'execution'))
            con.execute('INSERT INTO snapshots VALUES(?,?,?)',(self.source,'diagnostic','complete'))
            row=handoffs.load(con,self.source);d=json.loads(row['data']);d['wakeup_id']='wake';d['artifact_diagnosis']=True
            d['validation_failure'].update(source_task=self.source,volume='diagnostic',category='executed_test_failure')
            handoffs.save(con,self.source,'issue','technical_decision_required','cto',d,200)
        self.broker.docker=lambda method,path:dict(Image='sha256:'+'c'*64,Labels={'delivery-kit.owner':'owner','delivery-kit.source-task':self.source})
        return {**self.proof,'anchors':[dict(file='tests/test_new.py',line=4,assertion='assertTrue')],'operation':'frozen_assertion_trace_anchors_v1','approval':False}

    def trace(self,proof):
        def task(settings,tid,agent):return dict(id=tid,status='completed',issue_id='issue',wakeup_id='wake')
        with patch.object(native,'task_record',side_effect=task),patch.object(native,'issue_task_runs',return_value=[]),patch.dict('os.environ',{'HOSTNAME':'controller'}),patch('broker.failed_execution_evidence.capture',return_value=proof) as capture:
            return register_trace(self.broker,self.source),capture

    def test_completed_failure_trace_preserves_prior_diagnosis_not_green(self):
        proof=self.trace_fixture();receipt,capture=self.trace(proof);capture.assert_called_once()
        self.assertFalse(receipt['delivery_approval']);self.assertEqual(receipt['prior_cto_task'],self.decision)
        second,capture=self.trace(proof);capture.assert_not_called();self.assertEqual(receipt,second)
        with self.db() as con:
            d=json.loads(handoffs.load(con,self.source)['data']);self.assertEqual(handoffs.load(con,self.source)['stage'],'diagnose_cto')
            self.assertNotIn('green_validation',d)

    def test_completed_failure_trace_rejects_tampered_output(self):
        proof=self.trace_fixture()
        with self.db() as con:con.execute("UPDATE frozen_suite_failures SET output='tampered'")
        with self.assertRaisesRegex(ValueError,'saved failure output'):self.trace(proof)
