import copy
import json
import unittest
from broker.harness_prerequisite import instruction,qualify


class HarnessPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(source_task='source',cto='cto',author='author',issue_id='issue',
            required_files=['app/static/app.js','tests/test_incremental_u3.py'],
            syntax=dict(python_syntax_valid=True,node_syntax_valid=False,category='driver_syntax_error',
                functional_red=False,delivery_approval=False))
        self.state={'wakeup_id':'wake'}
        self.task=dict(id='decision',agent_id='cto',issue_id='issue',wakeup_id='wake',status='completed')
        self.reads={'/evidence/candidate/'+p:dict(lines=10,total_lines=10) for p in self.config['required_files']}
        self.decision=dict(action='request_test_revision',reason='Repair the driver only; verify syntax and executed observations.',optional_files=[])

    def test_sponsorship_is_not_execution_red_or_approval(self):
        receipt=qualify(self.config,self.state,self.task,self.decision,self.reads)
        self.assertFalse(receipt['execution_authorized'])
        self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(receipt['owner'],'cto')
        self.assertIn('syntax_sha256',receipt)

    def test_exact_identity_and_all_reads_required(self):
        for patch in ({'wakeup_id':'old'},{'issue_id':'other'},{'agent_id':'author'},{'status':'failed'}):
            with self.assertRaises(ValueError):qualify(self.config,self.state,{**self.task,**patch},self.decision,self.reads)
        partial=copy.deepcopy(self.reads)
        partial['/evidence/candidate/app/static/app.js']['lines']=9
        with self.assertRaises(ValueError):qualify(self.config,self.state,self.task,self.decision,partial)

    def test_no_product_permission_or_extra_fields(self):
        for patch in ({'action':'retry_author'},{'action':'approve_test_revision'},
                {'optional_files':['app/static/app.js']},{'units':[]},{'reason':'x'*1201}):
            with self.assertRaises(ValueError):qualify(self.config,self.state,self.task,{**self.decision,**patch},self.reads)

    def test_typed_bounded_prerequisite_note_keeps_controls_and_assertions(self):
        note=instruction(self.config)
        self.assertLess(len(note),3900)
        self.assertIn('DELIVERY_TYPED_DECISION_V1',note)
        self.assertIn('never functional TDD Red',note)
        self.assertIn('Preserve every existing test method',note)
        self.assertIn('Missing negative controls remain a later obligation',note)
        from decision_schema import apply
        from typed_decision_contract import apply as typed_apply
        # Actual inspection remains forced; no terminal decision before reads.
        body=typed_apply(apply({'messages':[{'role':'user','content':note}],
            'tools':[{'type':'function','function':{'name':'read_file'}}]}))
        self.assertEqual(body['tool_choice']['function']['name'],'read_file')
