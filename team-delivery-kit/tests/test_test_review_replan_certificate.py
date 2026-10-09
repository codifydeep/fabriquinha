import copy
import json
import unittest
from broker.test_review_replan_certificate import qualify
from portable_test_revision_recovery import next_revision_depth
from pre_red_supervision import qualified


class ImmutableReplanTests(unittest.TestCase):
    def fixture(self):
        route=dict(issue_id='child',author='author',cto='cto',techlead='lead',
            test_first_files=['tests/test_new.py'],enabled=True)
        red=dict(task_id='source',red={'manifest_sha256':'a'*64})
        task=dict(id='diagnosis',status='completed',issue_id='child',agent_id='cto',wakeup_id='wake')
        decision=dict(action='request_test_revision',reason='Restore the observed assertion.',optional_files=[],
            findings=[dict(kind='semantic_regression')])
        state=dict(status='blocked',source_task='source',evidence_policy=1,terminal_contract='typed-review-v1',
            review_task='review',manifest_sha256='a'*64,rejection_diagnosis=dict(status='revision_required',
                decision_task='diagnosis',decision=decision,target='cto',wakeup_id='wake'))
        reads={f'/evidence/{tree}/tests/test_new.py':dict(lines=9,total_lines=9) for tree in ('candidate','previous')}
        return route,state,red,task,decision,reads

    def managed(self):
        route,state,red,task,decision,reads=self.fixture()
        proof=qualify(route,state,red,task,decision,reads)
        data={**state,'technical_replan_certificate':proof,'test_revision_proposal':dict(
            source_task='source',decision_task='diagnosis',output_sha256=proof['output_sha256'])}
        return dict(route=route,state=dict(stage='test_revision_required',source_task='source',data=json.dumps(data)))

    def test_new_certificate_is_not_green_or_delivery_approval(self):
        proof=qualify(*self.fixture())
        self.assertEqual(proof['version'],'immutable-test-review-replan-v1')
        self.assertFalse(proof['green_evidence']);self.assertFalse(proof['delivery_approval'])
        self.assertFalse(proof['baseline_edits_allowed'])
        self.assertEqual(len(proof['required_read_paths']),2)

    def test_certificate_requires_complete_closed_independent_bound_decision(self):
        for mutation in ('actor','status','manifest','wakeup','decision','reads','findings','review'):
            args=list(copy.deepcopy(self.fixture()))
            if mutation=='actor':args[3]['agent_id']='author'
            if mutation=='status':args[3]['status']='running'
            if mutation=='manifest':args[2]['red']['manifest_sha256']='b'*64
            if mutation=='wakeup':args[3]['wakeup_id']='old'
            if mutation=='decision':args[4]['action']='approve_test_revision'
            if mutation=='reads':args[5]['/evidence/previous/tests/test_new.py']['lines']=3
            if mutation=='findings':args[4]['findings']=[]
            if mutation=='review':args[1]['review_task']='diagnosis'
            with self.assertRaises(ValueError,msg=mutation):qualify(*args)

    def test_second_level_requires_exact_certificate_and_third_stays_blocked(self):
        managed=self.managed()
        self.assertEqual(next_revision_depth({'issue_id':'child'},managed,'1'),'2')
        with self.assertRaises(ValueError):next_revision_depth({'issue_id':'child'},managed,'2')
        for key,value in (('manifest_sha256','stale'),('green_evidence',True),('delivery_approval',True),
                ('independent_review_task','old-review'),('operation','qualified_frozen_green_cto_replan_v1')):
            changed=copy.deepcopy(managed);data=json.loads(changed['state']['data'])
            data['technical_replan_certificate'][key]=value;changed['state']['data']=json.dumps(data)
            with self.assertRaises(ValueError,msg=key):next_revision_depth({'issue_id':'child'},changed,'1')

    def test_stale_projection_resumes_observation_only_after_revalidated_proof(self):
        managed=self.managed();status=dict(stage='escalation_required',issue_id='child',
            category='test_revision_blocked:invalid_cto_test_review_diagnosis:ValueError')
        proof=dict(qualified=True,independent=True,issue_id='child',contract_sha256='contract',
            delivery_approval=False,author_retry_authorized=False,managed=managed)
        self.assertTrue(qualified(status,dict(issue_id='child',contract_sha256='contract'),query=lambda _:proof))
        proof['qualified']=False
        self.assertFalse(qualified(status,dict(issue_id='child',contract_sha256='contract'),query=lambda _:proof))
