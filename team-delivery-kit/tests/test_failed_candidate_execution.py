import copy
import hashlib
import json
import sqlite3
import unittest

from broker import failed_candidate_execution as execution
from broker.failed_candidate_plan import digest


class FailedCandidateExecutionTests(unittest.TestCase):
    def test_validator_inventory_requires_executed_fixed_image_and_exact_frozen_tests(self):
        self.con.execute('CREATE TABLE validation_jobs(identity TEXT,state TEXT)')
        red=dict(base_manifest_sha256='a'*64,baseline_test_sha256={'tests/test_old.py':'b'*64},
                 test_sha256={'tests/test_new.py':'c'*64})
        proof=dict(base_manifest_sha256=red['base_manifest_sha256'],
            baseline_test_sha256=red['baseline_test_sha256'],new_test_sha256=red['test_sha256'],
            baseline_tests_intact=True,manifest_sha256='d'*64,diagnostic_file_sha256={'app.js':'e'*64})
        output=json.dumps(proof)
        identity=dict(task='source',kind='structure',payload=dict(Image='fixed-image',
            HostConfig=dict(Mounts=[dict(Source='frozen',ReadOnly=True)])))
        state=dict(stage='complete',result=dict(exit_code=0,output=output,
            output_sha256=hashlib.sha256(output.encode()).hexdigest()))
        self.con.execute('INSERT INTO validation_jobs VALUES(?,?)',(json.dumps(identity),json.dumps(state)))
        actual=execution.validator_inventory(self.con,'source','frozen','fixed-image',red,['app.js'])
        self.assertEqual(actual['product_sha256'],{'app.js':'e'*64})
        for source,volume,image,expected in [('other','frozen','fixed-image',red),
                ('source','other','fixed-image',red),('source','frozen','untrusted',red),
                ('source','frozen','fixed-image',{**red,'test_sha256':{'tests/test_new.py':'f'*64}})]:
            with self.assertRaises(ValueError):execution.validator_inventory(self.con,source,volume,image,expected,['app.js'])
        self.con.execute('UPDATE validation_jobs SET state=?',(json.dumps({**state,'result':{**state['result'],'output_sha256':'0'*64}}),))
        with self.assertRaises(ValueError):execution.validator_inventory(self.con,'source','frozen','fixed-image',red,['app.js'])

    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        self.route=dict(issue_id='issue',author='author',cto='cto',techlead='lead',contract_sha256='c'*64)
        self.plan=dict(operation='failed_candidate_plan_v1',source_task='source',issue_id='issue',
            contract_sha256='c'*64,diagnostic_sha256=digest({'proof':'frozen'}),cto_task='cto-task',
            cto='cto',reviewer='lead',author='author',edit_files=['app.js'],
            author_execution_authorized=False,tests_may_change=False,delivery_approval=False)
        self.peer=dict(operation='failed_candidate_plan_review_v1',plan_sha256=digest(self.plan),
            diagnostic_sha256=self.plan['diagnostic_sha256'],cto_task='cto-task',techlead_task='lead-task',
            contract_sha256='c'*64,status='reviewed_replan_requires_bounded_execution_adapter',
            author_execution_authorized=False,tests_may_change=False,delivery_approval=False,retry_budget_reset=False)
        self.data=dict(source_task='source',failed_execution_diagnostic={'proof':'frozen'},
            failed_candidate_plan=self.plan,failed_candidate_plan_review=self.peer,attempts=2)
        self.facts=dict(source_task='source',issue_id='issue',contract_sha256='c'*64,
            manifest_sha256='m'*64,product_sha256={'app.js':'p'*64},
            test_sha256={'tests/test_new.py':'t'*64},baseline_test_sha256={'tests/test_old.py':'o'*64},
            previous_product_sha256=[{'app.js':'b'*64}],volume='frozen',
            source_status='failed',diagnostic_only=True,baseline_tests_intact=True,
            frozen_tests_intact=True,independent_tasks_verified=True,active_leases=0,identical_corrections=2)

    def test_once_only_grant_and_same_dispatch_reconciliation_preserve_attempt_history(self):
        grant=execution.register(self.con,self.route,self.data,self.facts)
        self.assertEqual(execution.register(self.con,self.route,self.data,self.facts),grant)
        self.assertEqual(grant['prior_attempts'],2)
        self.assertEqual(grant['prior_identical_corrections'],2)
        self.assertFalse(grant['delivery_approval']);self.assertFalse(grant['retry_budget_reset'])
        intent=execution.dispatch_intent(self.con,'issue',grant['grant_sha256'],'marker')
        self.assertEqual(execution.dispatch_intent(self.con,'issue',grant['grant_sha256'],'marker'),intent)
        with self.assertRaises(ValueError):execution.dispatch_intent(self.con,'issue',grant['grant_sha256'],'another')
        first=execution.bind_dispatch(self.con,'issue',grant['grant_sha256'],'marker','author-task')
        self.assertEqual(execution.bind_dispatch(self.con,'issue',grant['grant_sha256'],'marker','author-task'),first)
        with self.assertRaises(ValueError):execution.bind_dispatch(self.con,'issue',grant['grant_sha256'],'another','another-task')

    def test_unchanged_candidate_stale_review_or_unverified_facts_cannot_grant(self):
        mutations=[('previous_product_sha256',[self.facts['product_sha256']]),
            ('frozen_tests_intact',False),('baseline_tests_intact',False),
            ('independent_tasks_verified',False),('active_leases',1),('source_task','other'),('identical_corrections',0)]
        for key,value in mutations:
            with self.assertRaises(ValueError):execution.register(self.con,self.route,self.data,{**self.facts,key:value})
        bad=copy.deepcopy(self.data);bad['failed_candidate_plan_review']['plan_sha256']='old'
        with self.assertRaises(ValueError):execution.register(self.con,self.route,bad,self.facts)

    def test_scope_expansion_or_second_source_cannot_reopen_issue_allowance(self):
        with self.assertRaises(ValueError):execution.register(self.con,self.route,self.data,
            {**self.facts,'product_sha256':{'tests/test_new.py':'t'*64}})
        execution.register(self.con,self.route,self.data,self.facts)
        bad=copy.deepcopy(self.data);bad['source_task']='other'
        with self.assertRaises(ValueError):execution.register(self.con,self.route,bad,self.facts)

    def test_terminal_failure_is_visible_and_cannot_rearm_execution(self):
        grant=execution.register(self.con,self.route,self.data,self.facts)
        execution.dispatch_intent(self.con,'issue',grant['grant_sha256'],'marker')
        execution.bind_dispatch(self.con,'issue',grant['grant_sha256'],'marker','author-task')
        result=execution.finish(self.con,'issue','author-task','failed','new executed failure')
        self.assertEqual(result['status'],'blocked_technical_recovery')
        self.assertEqual(result['owner'],'cto');self.assertEqual(result['attempt_limit'],1)
        with self.assertRaises(ValueError):execution.bind_dispatch(self.con,'issue',grant['grant_sha256'],'new','new-task')
        self.assertEqual(execution.finish(self.con,'issue','author-task','failed','new executed failure'),result)

    def test_no_native_binding_without_preexisting_intent_and_completed_is_not_approval(self):
        grant=execution.register(self.con,self.route,self.data,self.facts)
        with self.assertRaises(ValueError):execution.bind_dispatch(self.con,'issue',grant['grant_sha256'],'marker','author-task')
        execution.dispatch_intent(self.con,'issue',grant['grant_sha256'],'marker')
        execution.bind_dispatch(self.con,'issue',grant['grant_sha256'],'marker','author-task')
        result=execution.finish(self.con,'issue','author-task','completed','snapshot pending validation')
        self.assertEqual(result['status'],'awaiting_delivery_validation')
        self.assertFalse(result['delivery_approval'])

