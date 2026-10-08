import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import test_portable_remediation_intake as fixtures
from portable_remediation_intake import prepare,digest
from remediation_parent_delivery import evidence,publish,resolve,board_fields,verify_live


class RemediationParentDeliveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.PortableRemediationIntakeTests();f.setUp();self.bundle=f.build()
        self.stage={'contract':f.contract,'spec':f.spec}
        self.sha='f'*40
        self.receipt=dict(self.bundle['context'],stage='deployed_qa_passed',delivery=f.delivery,
            remediation_delivery=f.input['proof'],merge_sha=self.sha,pr_number=1,
            pr_url='https://github.com/codifydeep/descartavel2/pull/1',main_ci_run='https://example.invalid/ci',
            frozen_tests={'status':'passed'},board={'status':'done'},
            deployment={'status':'passed','source_sha':self.sha,'url':'http://127.0.0.1:19400','container':'app'},
            browser_qa={'status':'passed','cleanup':'passed','automated':True,
                'identity':{'source_sha':self.sha},'result':{'source_sha':self.sha,'status':'passed'}})
        self.items={'root':{'id':'root','status':'blocked','assignee_id':'author'},
                    'r2':{'id':'r2','status':'done','assignee_id':None}}
        self.metadata={'root':{'historical_rejection':'preserved'},'r2':{
            'delivery_receipt_sha':self.sha,'delivery_pr_url':self.receipt['pr_url']}}
        self.calls=[]
        def cli(*args):
            self.calls.append(args)
            if args[0]=='get':return dict(self.items[args[1]])
            if args[:2]==('metadata','list'):return dict(self.metadata[args[2]])
            if args[:2]==('metadata','set'):
                self.metadata[args[2]][args[4]]=args[6];return {}
            if args[0]=='assign':self.items[args[1]]['assignee_id']=None;return {}
            if args[0]=='status':self.items[args[1]]['status']=args[2];return {}
            raise AssertionError(args)
        self.cli=cli

    def test_full_receipt_keeps_real_child_identity_and_root_scope(self):
        proof=evidence(self.bundle,self.receipt)
        self.assertEqual(proof['parent_issue'],'root');self.assertEqual(proof['delivery_issue'],'r2')
        self.assertEqual(proof['original_depth'],2);self.assertFalse(proof['release_homologated'])
        self.assertEqual(proof['receipt_sha256'],digest(self.receipt))

    def test_live_verifier_rechecks_native_frozen_pr_ci_and_deployment(self):
        with patch('remediation_parent_delivery.approved_submission',return_value=self.receipt['delivery']) as native,\
             patch('remediation_parent_delivery.qualify') as frozen,\
             patch('dependent_sequence.verify_predecessor') as predecessor,\
             patch('dependent_sequence.verify_recovery_ci') as ci:
            verify_live(self.stage,self.receipt,self.bundle,instance='delivery-kit-port2')
        native.assert_called_once_with('r2',self.bundle['spec']['implementer_registry'],self.bundle['spec']['reviewer_registry'])
        frozen.assert_called_once();self.assertEqual(frozen.call_args.kwargs['previous'],self.receipt['remediation_delivery'])
        predecessor.assert_called_once();self.assertTrue(predecessor.call_args.kwargs['require_live_qa'])
        ci.assert_called_once()

    def test_live_verifier_rejects_obsolete_native_approval_before_ci(self):
        with patch('remediation_parent_delivery.approved_submission',return_value={}),\
             patch('dependent_sequence.verify_recovery_ci') as ci:
            with self.assertRaises(ValueError):verify_live(self.stage,self.receipt,self.bundle,instance='delivery-kit-port2')
        ci.assert_not_called()

    def test_missing_ci_browser_or_same_sha_never_projects_success(self):
        changes=[lambda r:r.update(stage='approved'),lambda r:r.update(main_ci_run=None),
                 lambda r:r['browser_qa'].update(automated=False),
                 lambda r:r['browser_qa']['result'].update(source_sha='0'*40),
                 lambda r:r['deployment'].update(source_sha='0'*40),
                 lambda r:r['frozen_tests'].update(status='failed'),
                 lambda r:r['remediation_delivery'].update(red_origin_issue='root'),
                 lambda r:r.update(delivery={})]
        for change in changes:
            receipt=copy.deepcopy(self.receipt);change(receipt)
            with self.assertRaises(ValueError):evidence(self.bundle,receipt)

    def publish(self,root,verify=None):
        paths=prepare(root,self.bundle)
        return publish(paths,self.receipt,self.cli,verify or Mock())

    def test_real_verification_precedes_writes_and_completion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);verify=Mock()
            result=self.publish(root,verify)
            self.assertEqual(result['stage'],'parent_projected');self.assertEqual(self.items['root']['status'],'done')
            self.assertEqual(self.metadata['root']['historical_rejection'],'preserved')
            self.assertNotIn('test_revision_child_issue',self.metadata['root'])
            writes=[c for c in self.calls if c[0] in ('assign','status') or c[:2]==('metadata','set')]
            self.publish(root,verify)
            self.assertEqual(writes,[c for c in self.calls if c[0] in ('assign','status') or c[:2]==('metadata','set')])
            self.assertEqual(verify.call_count,2)

    def test_cli_rejects_no_start_on_unassign_but_projection_recovers_idempotently(self):
        original=self.cli
        def supported_cli(*args):
            if args[0]=='assign' and '--unassign' in args and '--no-start' in args:
                raise ValueError('CLI does not accept --no-start with --unassign')
            return original(*args)
        self.cli=supported_cli
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);verify=Mock()
            first=self.publish(root,verify);self.publish(root,verify)
        self.assertEqual(first['stage'],'parent_projected');self.assertEqual(self.items['root']['status'],'done')
        self.assertEqual([c for c in self.calls if c[0]=='assign'],[('assign','root','--unassign')])
        self.assertEqual(verify.call_count,2)

    def test_cancelled_parent_or_conflicting_metadata_causes_no_writes(self):
        for cancelled in (True,False):
            self.items['root']['status']='cancelled' if cancelled else 'blocked'
            self.metadata['root']['remediation_delivery_sha']='0'*40
            self.calls=[]
            with tempfile.TemporaryDirectory() as directory,self.assertRaises(ValueError):
                self.publish(Path(directory))
            self.assertFalse(any(c[0] in ('assign','status') or c[:2]==('metadata','set') for c in self.calls))

    def test_failed_live_verification_never_changes_board(self):
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(ValueError):
            self.publish(Path(directory),Mock(side_effect=ValueError('CI unavailable')))
        self.assertEqual(self.items['root']['status'],'blocked')

    def test_cancellation_during_live_verification_is_not_overridden(self):
        def verify(*args):self.items['root']['status']='cancelled'
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(ValueError):
            self.publish(Path(directory),verify)
        self.assertFalse(any(c[0] in ('assign','status') or c[:2]==('metadata','set') for c in self.calls))

    def test_lost_completion_ack_resumes_by_observation_without_second_status_write(self):
        original=self.cli
        def lost_ack(*args):
            result=original(*args)
            if args[0]=='status':raise TimeoutError('ack lost')
            return result
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.cli=lost_ack
            with self.assertRaises(TimeoutError):self.publish(root)
            self.cli=original;result=self.publish(root)
            self.assertEqual(result['stage'],'parent_projected')
            self.assertEqual(len([c for c in self.calls if c[0]=='status']),1)

    def test_resolver_requires_projected_intent_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths=prepare(root,self.bundle)
            (root/'release-receipts').mkdir()
            child=root/'release-receipts'/(self.bundle['context']['label']+'.json')
            child.write_text(json.dumps(self.receipt))
            self.assertIsNone(resolve(root,self.bundle['context']['remediation_parent']))
            self.publish(root)
            recovered=resolve(root,self.bundle['context']['remediation_parent'])
            self.assertEqual(recovered['issue_id'],'r2');self.assertEqual(recovered['recovery_kind'],'remediation')
            self.assertEqual(recovered['recovery_parent'],self.bundle['context']['remediation_parent'])
            self.assertEqual(recovered['delivery'],self.receipt['delivery'])
            self.assertEqual(recovered['recovery_origin']['receipt_sha256'],digest(self.receipt))
            from dependent_sequence import read_stage_delivery,receipt_identity
            root_context=root/('portable-context-'+self.stage['spec']['label']+'.json')
            root_context.write_text(json.dumps(self.bundle['context']['remediation_parent']))
            self.assertEqual(read_stage_delivery(root,self.stage),recovered)
            self.assertTrue(receipt_identity(recovered,self.stage))
            from dependent_sequence import verify_predecessor
            merged=json.dumps({'state':'MERGED','mergeCommit':{'oid':self.sha}})
            with patch('prepare_issue_base.verified_main',return_value=self.sha),\
                 patch('start_eval.cli',side_effect=self.cli),\
                 patch('dependent_sequence.subprocess.check_output',return_value=merged):
                verify_predecessor(recovered,self.stage,require_live_qa=False)
                self.metadata['root']['remediation_delivery_sha']='0'*40
                with self.assertRaises(ValueError):verify_predecessor(recovered,self.stage,require_live_qa=False)
            changed=copy.deepcopy(self.receipt);changed['merge_sha']='0'*40;child.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):resolve(root,self.bundle['context']['remediation_parent'])
