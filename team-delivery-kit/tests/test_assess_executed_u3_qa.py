import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import assess_executed_u3_qa as qa


class ExecutedEvidenceTests(unittest.TestCase):
    def evidence(self):
        state = {'stage': 'blocked', 'reason': qa.CLEANUP_REASON,
                 'request': {'source_sha': qa.SHA, 'task_id': 'task', 'assessor': qa.ASSESSOR}}
        proof = {'status': 'failed', 'cleanup': 'failed', 'automated': True,
                 'identity': {'source_sha': qa.SHA, 'application_image': 'image'},
                 'result': {'status': 'passed', 'source_sha': qa.SHA,
                            'contexts': 2, 'checks': list(range(40))}, 'screenshot_sha256': 'screenshot'}
        raw = [json.dumps(v).encode() for v in (state, proof)]
        certificate = dict(schema='u3-independent-qa-cleanup-recovery-v1',
            failed_execution_receipt_sha256=hashlib.sha256(raw[0]).hexdigest(),
            failed_browser_receipt_sha256=hashlib.sha256(raw[1]).hexdigest(),
            source_sha=qa.SHA, image='image', request_task='task', contexts=2,
            browser_checks=list(range(40)), screenshot_sha256='screenshot',
            http_checks=qa.HTTP, resources_absent=[['container', 'owned']],
            assertions_passed=True, cleanup_recovered=True, tests_reexecuted=False,
            historical_tdd_red=False, release_homologated=False,
            product_admission_authorized=False, independent_agent_qa_approval=False)
        return raw, certificate, {'source_sha': qa.SHA, 'image': 'image', 'browser_checks': list(range(40))}

    def test_reconciles_without_rewriting_failures_or_granting_approval(self):
        raw, cert, deployment = self.evidence(); before = copy.deepcopy(raw)
        result = qa.reconcile(raw[0], raw[1], cert, deployment, [['container', 'owned']])
        self.assertEqual(result['stage'], 'validation_evidence_reconciled')
        self.assertEqual(raw, before)
        self.assertFalse(result['release_homologated'])
        self.assertFalse(result['independent_agent_qa_approval'])
        self.assertFalse(result['tests_reexecuted'])

    def test_modified_receipt_stale_certificate_or_authority_is_rejected(self):
        for key, value in [('request_task', 'stale'), ('image', 'changed'),
                           ('contexts', 1), ('tests_reexecuted', True),
                           ('release_homologated', True), ('browser_checks', list(range(39))),
                           ('failed_execution_receipt_sha256', 'wrong')]:
            raw, cert, deployment = self.evidence(); cert[key] = value
            with self.assertRaises(ValueError): qa.reconcile(*raw, cert, deployment, [['container', 'owned']])
        raw, cert, deployment = self.evidence()
        with self.assertRaises(ValueError): qa.reconcile(raw[0]+b' ', raw[1], cert, deployment, [['container', 'owned']])
        with self.assertRaises(ValueError): qa.reconcile(*raw, cert, deployment, [])

    def test_functional_failure_cannot_be_resolved_as_cleanup(self):
        raw, cert, deployment = self.evidence()
        proof = json.loads(raw[1]); proof['result']['status'] = 'failed'
        raw[1] = json.dumps(proof).encode()
        cert['failed_browser_receipt_sha256'] = hashlib.sha256(raw[1]).hexdigest()
        with self.assertRaises(ValueError): qa.reconcile(*raw, cert, deployment, [['container', 'owned']])

    def test_durable_reconciliation_is_idempotent_and_rechecks_native_identity(self):
        import contextlib
        import sqlite3
        import tempfile
        import threading
        from pathlib import Path
        from types import SimpleNamespace
        import execute_u3_qa as execution
        raw, cert, deployment = self.evidence()
        receipt = qa.reconcile(*raw, cert, deployment, [['container', 'owned']])
        config = dict(assessor=execution.ASSESSOR, author=execution.AUTHOR,
                      source_sha=execution.SHA, evidence_sha256='a'*64)
        state = dict(issue_id='issue', wakeup_id='wake', stage='validation_requested')
        decision = dict(operation='run_fixed_deployment_qa', evidence_sha256='a'*64,
                        reason='Fixed checks only', release_homologated=False,
                        product_admission_authorized=False)
        task = dict(id='task', agent_id=execution.ASSESSOR, issue_id='issue',
                    wakeup_id='wake', status='completed', result={'output': json.dumps(decision)})
        request = execution.request_receipt(config, state, task, decision)
        request['request_id'] = 'capability'; state['request'] = request
        connection = sqlite3.connect(':memory:'); connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE u3_qa_executions(evidence_sha256 TEXT,config TEXT,state TEXT)')
        connection.execute('INSERT INTO u3_qa_executions VALUES(?,?,?)',
                           ('a'*64, json.dumps(config), json.dumps(state)))
        @contextlib.contextmanager
        def db():
            with connection: yield connection
        try:
            with tempfile.TemporaryDirectory() as folder:
                Path(folder, 'native.json').write_text('{}')
                broker = SimpleNamespace(LOCK=threading.RLock(), STATE=Path(folder), db=db)
                native = SimpleNamespace(task_record=lambda *args: task)
                packet = dict(receipt=receipt, request=request, verifier_source=Path(execution.__file__).read_text())
                with patch.dict('sys.modules', broker=broker, native=native), patch('builtins.print'):
                    qa.persist(packet); qa.persist(packet)
                    self.assertEqual(connection.execute('SELECT count(*) FROM u3_qa_reconciliations').fetchone()[0], 1)
                    with self.assertRaises(ValueError):
                        qa.persist(dict(packet, receipt=dict(receipt, cleanup='changed')))
                    task['status'] = 'failed'
                    with self.assertRaises(ValueError): qa.persist(packet)
        finally: connection.close()
