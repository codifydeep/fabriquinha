import json
import sqlite3
import unittest
from broker import prospective_capacity as p


class ProspectiveCapacityTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.addCleanup(self.c.close)
        self.inputs=dict(issue_id='issue',source_task='source',manifest_sha256='a'*64,
            target='/workspace/tests/test_new.py',files={'/workspace/tests/test_new.py':'#'+'x'*32670})
        self.probe=dict(issue_id='issue',source_task='source',
            execution_id='11111111-1111-4111-8111-111111111111',
            diagnostic_parent='22222222-2222-4222-8222-222222222222',
            status='failed',failure_category='fixture_protocol_rejected',
            fixture_kind='frozen_context_prospective_v1',input_sha256=p.digest(self.inputs),
            manifest_sha256='a'*64,tools_executed=False,candidate_files_written=False,
            native_read_evidence=False,historical_failure_cause_proven=False,product_retry=False,
            delivery_approval=False,local_rejection=dict(schema='local-proposal-rejection-v1',
                constraint='artifact_size',response_sha256='b'*64,
                tools_executed=False,candidate_files_written=False))

    def proof(self):return p.validate_proof(self.probe,self.inputs,'issue','source')

    def test_prospective_restriction_never_proves_historical_failure_or_grants_retry(self):
        proof=self.proof()
        self.assertEqual(proof['available_growth_bytes'],97)
        self.assertFalse(proof['historical_failure_cause_proven'])
        self.assertFalse(proof['author_retry_authorized'])
        self.assertFalse(proof['delivery_approval'])
        self.assertNotIn('files',proof)

    def test_changed_context_manifest_or_approving_result_is_rejected(self):
        for change in (dict(status='passed'),dict(input_sha256='wrong'),dict(manifest_sha256='b'*64),
                dict(delivery_approval=True),dict(tools_executed=True),dict(native_read_evidence=True),
                dict(historical_failure_cause_proven=True),dict(source_task='other'),
                dict(local_rejection=dict(self.probe['local_rejection'],constraint='fragment_match'))):
            with self.subTest(change=change),self.assertRaises(ValueError):
                p.validate_proof(dict(self.probe,**change),self.inputs,'issue','source')

    def test_claim_is_durable_once_per_issue_not_per_execution(self):
        proof=self.proof();self.assertEqual(p.claim(self.c,proof),proof)
        self.assertEqual(p.claim(self.c,proof),proof)
        for change in (dict(source_task='other'),dict(execution_id='different'),dict(test_bytes=32000)):
            with self.assertRaises(ValueError):p.claim(self.c,dict(proof,**change))

    def test_qualification_requires_exact_controller_record(self):
        proof=self.proof();data=dict(prospective_capacity_replay={'certificate':proof})
        self.assertFalse(p.qualified(self.c,'issue','source',data))
        p.claim(self.c,proof)
        self.assertTrue(p.qualified(self.c,'issue','source',data))
        self.assertFalse(p.qualified(self.c,'issue','other',data))
        for key in ('historical_failure_cause_proven','author_retry_authorized','delivery_approval'):
            forged=dict(prospective_capacity_replay={'certificate':dict(proof,**{key:True})})
            self.assertFalse(p.qualified(self.c,'issue','source',forged))

    def test_tiny_or_wrong_target_cannot_invoke_capacity_recovery(self):
        for changes in (dict(target='/workspace/app.py'),
                dict(files={self.inputs['target']:'small'})):
            inputs=dict(self.inputs,**changes)
            with self.assertRaises(ValueError):
                p.validate_proof(dict(self.probe,input_sha256=p.digest(inputs)),inputs,'issue','source')
