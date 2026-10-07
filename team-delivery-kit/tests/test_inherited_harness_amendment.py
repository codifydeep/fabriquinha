import copy,unittest
from broker.inherited_harness_amendment import config
from broker.technical_remediation_plan import digest,instruction


class InheritedHarnessAmendmentTests(unittest.TestCase):
    def fixture(self):
        base=dict(base_sha='b'*40,manifest_sha256='c'*64)
        previous=dict(source_task='previous',criteria={'A01':'entire scope','A02':'other scope'},original_depth=2,
            revision_lineage=['old2','old1'],steps=[{},dict(owner='author')],base=base,root_issue='root',contract_sha256='a'*64)
        reference=dict(source_task='previous',issue_id='r2',execution_contract_sha256=digest(previous),
            criteria=previous['criteria'],red=dict(task_id='red',red=dict(test_sha256={'test_new.py':'d'*64})))
        proposal=dict(source_task='failed-author',issue_id='r2',reference_sha256=digest(reference),
            criteria=previous['criteria'],original_depth=2,reviewer='lead',cto_task='cto-task',cto_wakeup='cto-wake',
            required_paths=['/evidence/candidate/test_new.py'])
        peer=dict(stage='peer_reviewed',decision=dict(action='request_test_revision'),execution_authorized=False,task_id='peer')
        result=dict(operation='immutable_embedded_harness_syntax_experiment_v1',test_sha256='d'*64,test_file='test_new.py',
            product_file='app.js',product_sha256='e'*64,manifest_sha256='f'*64,
            harness=dict(category='syntax_error',exit_code=1),product=dict(category='valid',exit_code=0),
            control=dict(category='valid',exit_code=0),test_edits_authorized=False,delivery_approval=False,product_executed=False)
        experiment=dict(stage='experiment_recorded',volume='diagnostic',result=result,result_sha256=digest(result),
            proof=dict(proposal_sha256=digest(proposal),peer_task=peer['task_id'],peer_decision_sha256=digest(peer['decision']),
                test_sha256=reference['red']['red']['test_sha256']))
        route=dict(issue_id='r2',author='author',reviewer='reviewer',techlead='lead',cto='cto',contract_sha256='a'*64,
            execution_context=dict(sha256='f'*64))
        return proposal,peer,experiment,reference,previous,route,base

    def test_amendment_keeps_full_scope_depth_and_seed_without_permission(self):
        value=config(*self.fixture())
        self.assertEqual(value['criteria'],{'A01':'entire scope','A02':'other scope'})
        self.assertEqual(value['original_depth'],2);self.assertEqual(value['revision_lineage'],['old2','old1'])
        self.assertFalse(value['amendment']['execution_authorized']);self.assertFalse(value['amendment']['revision_depth_reset'])
        self.assertIn('behavioral_negative_controls',value['amendment']['required_gates'])
        note=instruction(value,dict(stage='plan_dispatch'))
        self.assertIn('NEW submission',note);self.assertIn('A01',note);self.assertIn('A02',note)

    def test_stale_review_false_probe_and_recursive_amendment_rejected(self):
        for slot,key,new in ((1,'execution_authorized',True),(1,'task_id','stale'),(2,'result_sha256','0'*64),
                             (0,'original_depth',0),(4,'amendment',{'previous':'already-amended'})):
            args=list(copy.deepcopy(self.fixture()));args[slot][key]=new
            with self.subTest(key=key),self.assertRaises(ValueError):config(*args)
        args=list(copy.deepcopy(self.fixture()));args[2]['result']['harness']['exit_code']=0
        args[2]['result_sha256']=digest(args[2]['result'])
        with self.assertRaises(ValueError):config(*args)

    def test_cannot_change_baseline_criteria_or_test_hash(self):
        for mutate in (lambda a:a[0].update(criteria={'A01':'partial'}),
                       lambda a:a[6].update(base_sha='new'),lambda a:a[2]['result'].update(test_sha256='0'*64)):
            args=list(copy.deepcopy(self.fixture()));mutate(args)
            with self.assertRaises(ValueError):config(*args)
