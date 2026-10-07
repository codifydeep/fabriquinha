import json
import unittest
from unittest.mock import Mock
from unittest.mock import patch
from contextlib import ExitStack
from pathlib import Path
import tempfile
import portable_delivery as driver
from portable_remediation_gate import qualify


class PortableRemediationGateTests(unittest.TestCase):
    def setUp(self):
        self.context={'issue_id':'r2'}
        self.delivery=dict(source_task='task',review_task='review',author='author',reviewer='reviewer',
                           volume='snapshot',manifest_sha256='a'*64)
        self.proof=dict(operation='qualified_remediation_r2_delivery_v1',issue_id='r2',source_task='failed',
            run_id='run',execution_contract_sha256='b'*64,r1_gate_sha256='c'*64,reference_sha256='d'*64,
            delivery=self.delivery,tdd_sha256='e'*64,red_origin_issue='r1',red_origin_task='red',
            original_depth=2,release_homologated=False)

    def invoke(self,response=None,previous=None):
        command=Mock(return_value=json.dumps(self.proof if response is None else response))
        result=qualify(command,'delivery-kit-port2',self.context,self.delivery,previous=previous)
        return result,command

    def test_exact_proof_uses_fixed_query_and_separate_json_argument(self):
        proof,command=self.invoke()
        self.assertEqual(proof,self.proof)
        args=command.call_args.args
        self.assertEqual(args[:4],('docker','exec','delivery-kit-port2-execution-broker-1','python'))
        self.assertIn('remediation_delivery',args[5])
        compile(args[5],'<fixed qualification query>','exec')
        self.assertNotIn('failed',args[5])
        self.assertEqual(json.loads(args[-1]),self.delivery)

    def test_legacy_without_reference_passes_but_cannot_erase_previous_proof(self):
        command=Mock(return_value='null')
        self.assertIsNone(qualify(command,'delivery-kit-port2',self.context,self.delivery))
        with self.assertRaises(ValueError):
            qualify(command,'delivery-kit-port2',self.context,self.delivery,previous=self.proof)

    def test_wrong_issue_delivery_origin_depth_or_homologation_claim_rejected(self):
        for change in (dict(issue_id='old'),dict(operation='agent_approved'),dict(delivery={}),
                       dict(red_origin_issue='r2'),dict(red_origin_task='task'),dict(original_depth=0),
                       dict(release_homologated=True),dict(tdd_sha256='bad')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.invoke({**self.proof,**change})

    def test_revalidation_cannot_replace_revision_or_plan(self):
        self.assertEqual(self.invoke(previous=self.proof)[0],self.proof)
        with self.assertRaises(ValueError):
            self.invoke({**self.proof,'reference_sha256':'f'*64},previous=self.proof)

    def test_transport_error_propagates_without_retry(self):
        command=Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            qualify(command,'delivery-kit-port2',self.context,self.delivery)
        self.assertEqual(command.call_count,1)

    def driver_case(self, *, approval=None, qualification=None):
        stack=ExitStack();self.addCleanup(stack.close)
        directory=stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.object(driver,'RECEIPT',Path(directory)/'receipt.json'))
        context={**self.context,'base_sha':'1'*40,'contract_sha256':'2'*64}
        responses=dict(find_qa_incident=None,approved=self.delivery,
            qualify_remediation_delivery=self.proof,snapshot_files=({}, {}, {'passed':True}),
            require_access=None,ensure_branch='3'*40,verify_candidate_before_pr={'passed':True},
            ensure_pr={'number':1,'url':'https://example.invalid/pr/1'},ensure_merge='4'*40,
            wait_main_ci={'passed':True},ensure_deployed={'source_sha':'4'*40},publish_board={'status':'done'})
        mocks={name:stack.enter_context(patch.object(driver,name,return_value=value)) for name,value in responses.items()}
        if approval is not None:mocks['approved'].side_effect=approval
        if qualification is not None:mocks['qualify_remediation_delivery'].side_effect=qualification
        return context,mocks

    def test_driver_requalifies_before_merge_and_deploy_and_preserves_receipt(self):
        context,mocks=self.driver_case()
        receipt=driver.reconcile(context,{})
        self.assertEqual(receipt['remediation_delivery'],self.proof)
        self.assertEqual(receipt['stage'],'deployed_qa_passed')
        self.assertEqual(mocks['approved'].call_count,3)
        self.assertEqual(mocks['qualify_remediation_delivery'].call_count,3)
        for call in mocks['qualify_remediation_delivery'].call_args_list[1:]:
            self.assertEqual(call.kwargs['previous'],self.proof)

    def test_driver_revoked_proof_prevents_merge(self):
        context,mocks=self.driver_case(qualification=[self.proof,ValueError('revoked')])
        with self.assertRaises(ValueError):driver.reconcile(context,{})
        mocks['ensure_merge'].assert_not_called();mocks['ensure_deployed'].assert_not_called()

    def test_driver_new_author_run_prevents_merge_of_old_delivery(self):
        context,mocks=self.driver_case(approval=[self.delivery,{**self.delivery,'source_task':'new-task'}])
        with self.assertRaises(ValueError):driver.reconcile(context,{})
        mocks['ensure_merge'].assert_not_called()

    def test_driver_post_merge_revocation_prevents_deployment(self):
        context,mocks=self.driver_case(qualification=[self.proof,self.proof,ValueError('revoked')])
        with self.assertRaises(ValueError):driver.reconcile(context,{})
        mocks['ensure_merge'].assert_called_once();mocks['ensure_deployed'].assert_not_called()
