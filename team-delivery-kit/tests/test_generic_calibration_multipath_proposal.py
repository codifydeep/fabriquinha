import copy
import json
from pathlib import Path
import tempfile
import unittest

from broker import generic_calibration_proposal as proposal
from generic_calibration_bundle_writer import write
from generic_harness_calibration import digest
import test_generic_harness_calibration_v2 as samples


class MultiPathProposalTests(unittest.TestCase):
    def setUp(self):
        sample=samples.MultiPathCalibrationTests();sample.setUp();self.addCleanup(sample.doCleanups)
        p=sample.policy
        self.value=dict(source_task=p['source_task'],plan_sha256=p['plan_sha256'],
            criteria={c:'unchanged criterion' for c in p['criteria']},
            steps=[dict(editable_files=list(p['test_sha256']))],
            previous_new_test_delivery=dict(test_sha256=p['test_sha256']))
        self.route=dict(test_first_files=list(p['test_sha256']),author='author',cto='cto',techlead='lead',issue_id='issue')
        self.prepared=dict(manifest_sha256=p['candidate_manifest_sha256'],test_sha256=p['test_sha256'])
        self.body=dict(action='propose_calibration_bundle',engine=p['engine'],modules=p['modules'],
            negatives=p['negatives'],previous_methods=p['previous_methods'],controls=sample.control_files,
            execution_authorized=False,delivery_approval=False)

    def bundle(self,body=None):
        return proposal.bundle(body or self.body,self.value,self.route,self.prepared,
            expected_engine='unittest_path_fixtures_v2')

    def test_agent_cannot_select_v2_in_legacy_controller_context(self):
        with self.assertRaises(ValueError):proposal.bundle(self.body,self.value,self.route,self.prepared)
        body=copy.deepcopy(self.body);body['engine']='unittest_path_fixture_v1'
        with self.assertRaises(ValueError):self.bundle(body)

    def test_bound_bundle_and_materialization_preserve_every_fixture(self):
        record=self.bundle()
        self.assertEqual(record['policy']['version'],'generic_harness_calibration_v2')
        self.assertEqual(record['policy']['execution_sha256'],digest(self.value))
        with tempfile.TemporaryDirectory() as directory:
            controls=Path(directory)/'controls';policy=Path(directory)/'policy'
            controls.mkdir();policy.mkdir()
            receipt=write(controls,policy,record,digest(record))
            self.assertEqual(json.loads((policy/'policy.json').read_text()),record['policy'])
            for name,content in self.body['controls'].items():
                self.assertEqual((controls/name).read_text(),content)
            self.assertIs(receipt['tests_executed'],False)
            self.assertIs(receipt['delivery_approval'],False)

    def test_completed_cto_must_read_both_product_files(self):
        task=dict(id='cto-task',agent_id='cto',issue_id='issue',wakeup_id='wake',status='completed',
            result=dict(output=json.dumps(self.body)))
        paths=proposal.source_paths(self.body)
        self.assertIn('/evidence/candidate/app/app.js',paths)
        self.assertIn('/evidence/candidate/app/index.html',paths)
        reads={p:dict(lines=3,total_lines=3) for p in paths}
        record=proposal.from_task(task,'wake',self.value,self.route,self.prepared,reads,
            expected_engine='unittest_path_fixtures_v2')
        self.assertEqual(record['producer']['actor'],'cto')
        del reads['/evidence/candidate/app/index.html']
        with self.assertRaises(ValueError):proposal.from_task(task,'wake',self.value,self.route,self.prepared,reads,
            expected_engine='unittest_path_fixtures_v2')

    def test_missing_or_extra_controls_remain_rejected(self):
        for change in ('missing','extra'):
            body=copy.deepcopy(self.body)
            if change=='missing':del body['controls']['html-positive.html']
            else:body['controls']['undeclared.txt']='extra'
            with self.assertRaises(ValueError):self.bundle(body)
