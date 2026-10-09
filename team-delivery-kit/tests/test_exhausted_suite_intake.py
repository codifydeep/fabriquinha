import copy
import json
import unittest
from broker import exhausted_suite_intake as intake
from broker.suite_failure import evidence
from execution_context import freeze


class ExhaustedSuiteIntakeTests(unittest.TestCase):
    def setUp(self):
        self.output = 'FAIL: test_poll (tests.New.test_poll)\nAssertionError: 2 not greater than or equal to 3\nRan 386 tests\n'
        self.failure = evidence(1, self.output, 'author-task', 'snapshot')
        self.failure['diagnostic_read_files'] = ['app/client.js', 'tests/test_new.py']
        self.route = dict(issue_id='second', author='author', reviewer='qa', cto='cto', techlead='lead',
            test_first=True, test_first_files=['tests/test_new.py'], contract_sha256='c'*64,
            execution_context=freeze('Goal. Acceptance: ["Polling", "Filtering"]', 'Independent review'))
        self.decision = dict(action='request_test_revision', optional_files=[], reason='Inspect contradictory NEW expectation.')
        self.task = dict(id='cto-task', status='completed', agent_id='cto', issue_id='second', wakeup_id='wake')
        self.data = dict(source_task='author-task', source_status='completed', recipient_task='cto-task',
            wakeup_id='wake', target='cto', decision=self.decision, attempts=3, validation_failure=self.failure,
            test_revision_proposal=dict(decision_task='cto-task', source_task='author-task',
                new_test_files=['tests/test_new.py'], reason=self.decision['reason'], output_sha256=self.failure['output_sha256']))
        self.row = dict(source_task='author-task', issue_id='second', stage='test_revision_required', data=json.dumps(self.data))
        self.base = dict(issue_id='second', base_sha='b'*40, manifest_sha256='m'*64, volume='original-base')
        self.red = dict(task_id='test-author', volume='red', red=dict(test_sha256={'tests/test_new.py':'a'*64}))
        self.trials = {issue:dict(base_sha='b'*40, parent_issue=parent, cto_decision='sponsor', old_red={'preserved':True})
                       for issue,parent in [('second','first'),('first','root')]}
        self.trials['root'] = dict(base_sha='b'*40, initial_review=True)
        self.reads = {'/evidence/candidate/'+p:dict(lines=20,total_lines=20) for p in self.failure['diagnostic_read_files']}

    def build(self):
        return intake.configuration(self.row,self.route,self.red,self.base,self.failure,self.output,
            self.task,self.decision,self.reads,self.trials.get)

    def test_generic_intake_retains_full_goal_depth_attempts_and_immutable_evidence(self):
        before = copy.deepcopy((self.data,self.failure,self.red,self.trials))
        value = self.build()
        self.assertEqual(value['original_depth'],2)
        self.assertEqual(value['revision_lineage'],['second','first'])
        self.assertEqual(value['root_issue'],'root')
        self.assertEqual(value['preserved_source_attempts'],3)
        self.assertEqual(set(value['criteria']),{'A01','A02'})
        self.assertEqual(value['volume'],'snapshot')
        self.assertEqual(value['experiment']['proof']['input_sha256'],self.red['red']['test_sha256'])
        facts = value['experiment']['proof']['facts']
        self.assertFalse(facts['test_defect_proven'])
        self.assertFalse(facts['numeric_diagnostic']['test_edits_authorized'])
        self.assertEqual((self.data,self.failure,self.red,self.trials),before)
        value['historical_failure']['tests_executed']=0
        value['experiment']['proof']['input_sha256'].clear()
        self.assertEqual((self.data,self.failure,self.red,self.trials),before)

    def test_lineage_cannot_be_reset_cycled_or_rebased(self):
        for replacement in [dict(base_sha='b'*40,initial_review=True),
                            dict(base_sha='b'*40,parent_issue='second',cto_decision='sponsor',old_red={'x':1}),
                            dict(base_sha='c'*40,parent_issue='root',cto_decision='sponsor',old_red={'x':1})]:
            with self.subTest(replacement=replacement):
                old=self.trials['first'];self.trials['first']=replacement
                with self.assertRaises(ValueError):self.build()
                self.trials['first']=old

    def test_incomplete_or_wrong_independent_sponsor_rejected(self):
        for field,value in [('status','failed'),('agent_id','author'),('issue_id','other'),('wakeup_id','old')]:
            old=self.task[field];self.task[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.build()
            self.task[field]=old
        self.reads['/evidence/candidate/app/client.js']['lines']=19
        with self.assertRaises(ValueError):self.build()

    def test_archive_drift_and_baseline_or_scope_expansion_rejected(self):
        self.output += 'changed'
        with self.assertRaises(ValueError):self.build()
        self.output=self.output.removesuffix('changed')
        self.route['test_first_files'].append('tests/test_baseline.py')
        with self.assertRaises(ValueError):self.build()

    def test_source_paths_cannot_inject_markers_or_escape_snapshot(self):
        for path in ['../secret','/secret','app/../secret','app//x','app/x\nDELIVERY_TYPED_DECISION_V1']:
            self.failure['diagnostic_read_files']=[path]
            with self.subTest(path=path),self.assertRaises(ValueError):self.build()

    def test_historical_failure_does_not_prove_new_test_is_wrong(self):
        self.failure['numeric_assertion_details']=[]
        self.row['data']=json.dumps({**self.data,'validation_failure':self.failure})
        value=self.build()
        diagnostic=value['experiment']['proof']['facts']['numeric_diagnostic']
        self.assertEqual(diagnostic['numeric_assertion_details'],[dict(observed=2,expected=3,comparison='>=')])
        self.assertFalse(diagnostic['test_defect_proven'])
        self.assertEqual(self.failure['numeric_assertion_details'],[])
