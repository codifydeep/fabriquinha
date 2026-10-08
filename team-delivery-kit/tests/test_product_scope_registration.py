import hashlib
import json
import unittest
from unittest.mock import patch
import test_product_scope_job as fixtures
from broker import product_scope_job as materialization
from broker import product_scope_registration as registration
from broker import product_scope_ledger as ledger


class ProductScopeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductScopeJobTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b,self.fx,self.key=self.f.b,self.f.fx,self.f.key
        with patch.object(materialization.validation_job,'run',return_value=self.f.result):
            self.state=materialization.tick(self.b,self.key,self.fx)
        self.proof=dict(operation='verified_product_scope_base_v1',base_sha=self.f.base['base_sha'],
            original_base_manifest_sha256=self.f.base['manifest_sha256'],
            manifest_sha256=self.f.receipt['manifest_sha256'],contract_sha256=self.f.receipt['contract_sha256'],
            frozen_test_sha256=self.f.context['frozen_test_sha256'],delivery_approval=False,write_grant_issued=False)
        output=json.dumps(self.proof)
        self.result=dict(exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                         validation_job_key='d'*64,approval=False)

    def test_verified_base_is_registered_atomically_without_global_base_or_tool_grant(self):
        with patch.object(registration.validation_job,'run',return_value=self.result) as run:
            state=registration.tick(self.b,self.key,self.fx)
            self.assertTrue(state['author_blocked'])
            self.assertEqual(state['registration']['stage'],'complete')
            with self.b.db() as con:
                row=json.loads(con.execute('SELECT receipt FROM product_scope_bases WHERE plan_key=?',(self.key,)).fetchone()[0])
                self.assertEqual(row['contract_sha256'],self.f.receipt['contract_sha256'])
                self.assertFalse(row['write_grant_issued'])
            self.assertEqual(registration.tick(self.b,self.key,self.fx),state)
            run.assert_called_once()
            payload=run.call_args.args[3]
            self.assertTrue(all(m['ReadOnly'] for m in payload['HostConfig']['Mounts']))
            self.assertEqual(payload['Image'],registration.IMAGE)
            self.assertEqual(self.b.issue_base('issue'),self.f.base)

    def test_pending_verification_is_the_same_job_after_restart(self):
        with patch.object(registration.validation_job,'run',side_effect=[registration.validation_job.Pending('live'),self.result]) as run:
            with self.assertRaises(registration.validation_job.Pending):registration.tick(self.b,self.key,self.fx)
            registration.tick(self.b,self.key,self.fx)
            self.assertEqual(run.call_args_list[0],run.call_args_list[1])

    def test_invalid_proof_is_persistently_blocked_and_not_registered(self):
        output=json.dumps(dict(self.proof,write_grant_issued=True))
        invalid=dict(self.result,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest())
        with patch.object(registration.validation_job,'run',return_value=invalid) as run:
            with self.assertRaises(ValueError):registration.tick(self.b,self.key,self.fx)
            held=registration.tick(self.b,self.key,self.fx)
            self.assertEqual(held['registration']['stage'],'blocked')
            self.assertTrue(held['author_blocked']);run.assert_called_once()
            with self.b.db() as con:
                self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='product_scope_bases'").fetchone())

    def test_numeric_zero_is_not_a_false_authorization_flag(self):
        output=json.dumps(dict(self.proof,write_grant_issued=0))
        invalid=dict(self.result,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest())
        with patch.object(registration.validation_job,'run',return_value=invalid),self.assertRaises(ValueError):
            registration.tick(self.b,self.key,self.fx)
