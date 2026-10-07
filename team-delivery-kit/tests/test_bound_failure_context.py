import json
import unittest
from broker.bound_failure_context import project, expand


class BoundFailureContextTests(unittest.TestCase):
    def test_projection_preserves_full_failure_by_verified_reference(self):
        failure={'category':'executed_test_failure','failures':[{'qualified_name':'test_'+str(i)} for i in range(60)],'output_sha256':'a'*64}
        summary={'source_task':'source','error':'portable frozen suite failed','validation_failure':failure}
        projected,marker=project(summary,'source',failure)
        self.assertLess(len(json.dumps(projected)),700)
        self.assertEqual(projected['validation_failure']['failure_count'],60)
        note='Diagnose '+json.dumps(projected)
        row={'issue_id':'issue','data':json.dumps(dict(validation_failure=failure,target='cto',wakeup_id='wake',artifact_diagnosis=True))}
        task=dict(agent_id='cto',wakeup_id='wake')
        full=expand(note,'issue',task,lambda source:row)
        self.assertIn(json.dumps(failure,sort_keys=True,separators=(',',':')),full)
        for changed in (dict(task,agent_id='author'),dict(task,wakeup_id='old')):
            with self.assertRaises(ValueError):expand(note,'issue',changed,lambda source:row)
        failure['failures'].pop()
        with self.assertRaises(ValueError):expand(note,'issue',task,lambda source:{**row,'data':json.dumps(dict(validation_failure=failure,target='cto',wakeup_id='wake',artifact_diagnosis=True))})

    def test_marker_does_not_grant_authority_or_duplicate_expansion(self):
        failure=dict(category='executed_test_failure',failures=[])
        _,marker=project({'validation_failure':failure},'source',failure)
        with self.assertRaises(ValueError):expand(marker+'\n'+marker,'issue',{},lambda source:None)
        with self.assertRaises(ValueError):expand(marker,'issue',{},lambda source:None)
        self.assertEqual(expand('ordinary','issue',{},lambda source:self.fail()),'ordinary')
