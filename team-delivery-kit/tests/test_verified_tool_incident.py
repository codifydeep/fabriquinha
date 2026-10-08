import json
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from broker import verified_tool_incident as incident


class VerifiedToolIncidentTests(unittest.TestCase):
    def test_measured_constraint_is_explicit_and_never_exposes_payload(self):
        self.assertIsNone(incident.measured_fact(self.d))
        diagnostic=dict(self.d,structure=dict(schema='forced-argument-constraint-v1',field='new_string',constraint='no_change'))
        fact=incident.measured_fact(diagnostic)
        self.assertTrue(fact['constraint_known'])
        self.assertEqual(fact['constraint'],'no_change')
        self.assertIn('changes no bytes',fact['meaning'])
        self.assertEqual(fact['scope'],'this exact rejected response only')
        self.assertFalse(fact['write_executed'])
        self.assertFalse(fact['delivery_approval'])
        with self.assertRaises(ValueError):
            incident.measured_fact(dict(diagnostic,structure=dict(diagnostic['structure'],payload='PRIVATE')))

    def test_changed_presentation_is_once_per_issue_and_requires_exact_proof(self):
        self.c.row_factory=sqlite3.Row;c=self.c
        c.executescript('''CREATE TABLE delivery_handoffs(issue_id TEXT,source_task TEXT,stage TEXT,data TEXT,updated REAL);
CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);
CREATE TABLE failed_execution_snapshots(task_id TEXT,status TEXT);
CREATE TABLE leases(status TEXT);
CREATE TABLE test_first_red(issue_id TEXT);''')
        diagnostic=dict(self.d,structure=dict(schema='forced-argument-constraint-v1',field='new_string',constraint='no_change'))
        receipt=incident.claim(c,'issue','source',diagnostic)
        data=dict(error='test_first_cto_requires_replanning',decision={'action':'escalate_cto'},
            cto_task='completed-cto',diagnostic=diagnostic,verified_tool_incident=receipt)
        c.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?)',('issue','source','test_first_blocked',json.dumps(data),1))
        c.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(dict(enabled=True,test_first=True,author='a',cto='c'))))
        c.execute('INSERT INTO failed_execution_snapshots VALUES(?,?)',('source','complete'))
        class B:
            @contextmanager
            def db(inner):
                with c:yield c
        c.execute('INSERT INTO leases VALUES(?)',('running',))
        self.assertIsNone(incident.presentation_capture(B(),'issue','source'))
        c.execute('DELETE FROM leases')
        proof=incident.presentation_capture(B(),'issue','source')
        self.assertFalse(proof['author_retry_authorized'])
        self.assertEqual(proof,incident.presentation_capture(B(),'issue','source'))
        data['constraint_presentation_replay']={'certificate':proof}
        self.assertTrue(incident.presentation_qualified(c,'issue','source',data))
        data['diagnostic']=dict(diagnostic,call_number=7777)
        self.assertFalse(incident.presentation_qualified(c,'issue','source',data))
        c.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(data),))
        self.assertIsNone(incident.presentation_capture(B(),'issue','source'))

    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.d=dict(kind='rejected_forced_tool_response',issue_id='issue',task_id='source',
            operation='rejected_forced_tool_response_v1',category='invalid_forced_argument',tool='patch',
            provenance='owned_proxy_validator_log',proxy_image='sha256:'+'a'*64,
            execution_id='eb720780-398c-4809-aa34-8c4848b279bf',call_number=5208,
            write_executed=False,tests_executed=False,red_verified=False,delivery_approval=False)

    def test_same_failure_on_new_task_or_call_does_not_reset_diagnosis(self):
        receipt=incident.claim(self.c,'issue','source',self.d)
        self.assertFalse(receipt['author_retry_authorized'])
        self.assertFalse(receipt['cause_known'])
        self.assertEqual(incident.claim(self.c,'issue','source',self.d),receipt)
        self.assertIsNone(incident.claim(self.c,'issue','other',dict(self.d,task_id='other',call_number=5209)))

    def test_changed_constraint_is_new_evidence_but_counts_are_not(self):
        incident.claim(self.c,'issue','source',self.d)
        shape=dict(schema='forced-argument-constraint-v1',field='new_string',constraint='no_change')
        d=dict(self.d,task_id='known',structure=shape)
        receipt=incident.claim(self.c,'issue','known',d)
        self.assertTrue(receipt['cause_known'])
        self.assertIsNone(incident.claim(self.c,'issue','third',dict(d,task_id='third',call_number=5210)))
        self.assertIsNone(incident.claim(self.c,'issue','fourth',dict(d,task_id='fourth',
            structure=dict(shape,constraint='length',characters=5000,utf8_bytes=5000))))

    def test_forged_or_approving_diagnostic_and_changed_receipt_are_rejected(self):
        for changes in (dict(provenance='worker_claim'),dict(write_executed=True),dict(task_id='other'),
                        dict(structure=dict(schema='forced-argument-constraint-v1',field='path',constraint='enum',source='SECRET'))):
            with self.assertRaises(ValueError):incident.claim(self.c,'issue','source',dict(self.d,**changes))
        receipt=incident.claim(self.c,'issue','source',self.d)
        data=dict(diagnostic=self.d,verified_tool_incident=receipt)
        self.assertTrue(incident.qualified(self.c,'issue','source',data))
        data['diagnostic']=dict(self.d,call_number=7777)
        self.assertFalse(incident.qualified(self.c,'issue','source',data))

    def test_capture_requires_idle_frozen_current_source_and_independent_cto(self):
        self.c.row_factory=sqlite3.Row
        c=self.c
        c.executescript('''CREATE TABLE delivery_handoffs(issue_id TEXT,source_task TEXT,stage TEXT,data TEXT,updated REAL);
CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);
CREATE TABLE failed_execution_snapshots(task_id TEXT,status TEXT);
CREATE TABLE native_bindings(task_id TEXT,issue_id TEXT,request_id TEXT);
CREATE TABLE leases(request_id TEXT,status TEXT);
CREATE TABLE test_first_red(issue_id TEXT);''')
        c.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?)',('issue','source','test_first_blocked',
            json.dumps(dict(error='test_first_correction_failed_after_cto_diagnosis',diagnostic=self.d)),1))
        route=dict(enabled=True,test_first=True,author='author',cto='cto')
        c.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(route)))
        c.execute('INSERT INTO failed_execution_snapshots VALUES(?,?)',('source','complete'))
        c.execute('INSERT INTO native_bindings VALUES(?,?,?)',('source','issue',self.d['execution_id']))
        c.execute('INSERT INTO leases VALUES(?,?)',(self.d['execution_id'],'closed'))
        class B:
            @contextmanager
            def db(inner):
                with c:yield c
        with patch('broker.artifact_rejection_evidence.fetch',return_value=self.d):
            c.execute('INSERT INTO leases VALUES(?,?)',('busy','active'))
            self.assertIsNone(incident.capture(B(),'issue','source'))
            c.execute('DELETE FROM leases WHERE request_id=?',('busy',))
            c.execute('UPDATE failed_execution_snapshots SET status=?',('pending',))
            self.assertIsNone(incident.capture(B(),'issue','source'))
            c.execute('UPDATE failed_execution_snapshots SET status=?',('complete',))
            c.execute('UPDATE delivery_routes SET config=?',(json.dumps(dict(route,cto='author')),))
            self.assertIsNone(incident.capture(B(),'issue','source'))
            c.execute('UPDATE delivery_routes SET config=?',(json.dumps(route),))
            self.assertIsNotNone(incident.capture(B(),'issue','source'))
