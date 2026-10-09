import copy
import json
import sqlite3
import unittest
from broker import remediation_r1_feedback as feedback
from broker import technical_remediation_plan as plans


class R1FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.previous=dict(source_task='original',run_id='old-run',original_depth=2,
            revision_lineage=['second','first'],root_issue='root',criteria={'A01':'unchanged'},
            baseline_edits_allowed=False,historical_snapshots_editable=False,
            release_homologated=False,
            contract_sha256='contract',base=dict(base_sha='base',manifest_sha256='base-manifest'),
            steps=[dict(owner='author',editable_files=['tests/test_new.py'])])
        self.execution=dict(stage='r1_base_qualified',issue_id='r1',execution_authorized=False)
        self.route=dict(issue_id='r1',enabled=True,test_first=True,author='author',
            reviewer='qa',techlead='lead',cto='cto',contract_sha256='contract',
            execution_context={'sha256':'context'})
        self.red=dict(issue_id='r1',task_id='author-task',volume='red-volume',
            red=dict(manifest_sha256='new-manifest',test_sha256={'tests/test_new.py':'test-hash'}))
        self.proof=dict(operation='qualified_immutable_test_cto_replan_v1',issue_id='r1',
            source_task='author-task',decision_task='cto-task',independent_review_task='review-task',
            manifest_sha256='new-manifest')
        self.proof.update(baseline_edits_allowed=False,delivery_approval=False,green_evidence=False)
        self.state=dict(status='blocked',candidate_volume='red-volume',manifest_sha256='new-manifest',
            review_task='review-task',decision=dict(action='reject_test_revision',reason='specific finding'),
            technical_replan_certificate=self.proof,rejection_diagnosis=dict(status='revision_required',
                decision_task='cto-task',wakeup_id='cto-wake',decision=dict(action='request_test_revision',reason='correction')))
        self.base=dict(issue_id='r1',volume='base-volume',**self.previous['base'])

    def config(self,**changes):
        values=dict(previous=self.previous,execution=self.execution,route=self.route,red=self.red,
            state=self.state,proof=self.proof,base=self.base);values.update(changes)
        return feedback.configuration(**values)

    def test_fresh_plan_preserves_depth_scope_criteria_and_rejected_delivery(self):
        before=copy.deepcopy((self.previous,self.execution,self.state,self.red))
        config=self.config()
        self.assertEqual(config['intake_kind'],'rejected_remediation_r1_v1')
        self.assertEqual(config['original_depth'],2)
        self.assertEqual(config['revision_lineage'],['second','first'])
        self.assertEqual(config['criteria'],{'A01':'unchanged'})
        self.assertEqual(config['volume'],'red-volume')
        self.assertEqual(config['r1_feedback']['round'],1)
        self.assertFalse(config['r1_feedback']['execution_authorized'])
        self.assertFalse(config['r1_feedback']['revision_depth_reset'])
        self.assertEqual(before,(self.previous,self.execution,self.state,self.red))

    def test_feedback_counter_is_persistent_bounded_and_not_a_depth_reset(self):
        for round_number in (True,-1,2,3,'1'):
            with self.subTest(round_number=round_number),self.assertRaises(ValueError):
                self.config(previous={**self.previous,'r1_feedback':{'round':round_number}})
        config=self.config(previous={**self.previous,'r1_feedback':{'round':1}})
        self.assertEqual(config['r1_feedback']['round'],2)
        self.assertEqual(config['original_depth'],2)

    def test_stale_approved_or_unqualified_review_cannot_trigger_feedback(self):
        cases=[dict(status='approved'),dict(manifest_sha256='other'),dict(candidate_volume='other'),
            dict(review_task='other'),dict(technical_replan_certificate={}),
            dict(decision={'action':'approve_test_revision'}),
            dict(rejection_diagnosis={**self.state['rejection_diagnosis'],'status':'awaiting_cto'})]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ValueError):self.config(state={**self.state,**change})

    def test_product_gate_baseline_author_and_lineage_changes_are_rejected(self):
        cases=[('execution',dict(r1_gate={'approved':True})),('execution',dict(superseded_by_feedback={})),
            ('execution',dict(superseded_by_feedback={'source_task':'other'})),
            ('route',dict(author='cto')),('route',dict(test_first=False)),('route',dict(enabled=False)),
            ('previous',dict(original_depth=0)),('previous',dict(revision_lineage=[])),
            ('previous',dict(baseline_edits_allowed=True)),('previous',dict(historical_snapshots_editable=True)),
            ('base',dict(base_sha='new')),('red',dict(issue_id='other'))]
        for name,change in cases:
            if change==dict(superseded_by_feedback={}):continue  # Empty metadata conveys no supersession.
            with self.subTest(name=name,change=change),self.assertRaises(ValueError):
                self.config(**{name:{**getattr(self,name),**change}})

    def parent_db(self,config):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.executescript('CREATE TABLE remediation_executions(source_task,contract,state);'
            'CREATE TABLE test_revision_trials(issue_id,state);CREATE TABLE test_first_red(issue_id,receipt);')
        execution={**self.execution,'superseded_by_feedback':dict(source_task=config['source_task'],config_sha256=plans.digest(config))}
        con.execute('INSERT INTO remediation_executions VALUES(?,?,?)',('original',json.dumps(self.previous),json.dumps(execution)))
        con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('r1',json.dumps(self.state)))
        con.execute('INSERT INTO test_first_red VALUES(?,?)',('r1',json.dumps(self.red)))
        return con

    def test_live_parent_binding_detects_mutation_and_never_modifies_old_receipts(self):
        config=self.config();con=self.parent_db(config)
        before=list(con.execute('SELECT * FROM test_first_red'))
        feedback.validate_parent(con,config)
        self.assertEqual(before,list(con.execute('SELECT * FROM test_first_red')))
        con.execute('UPDATE test_revision_trials SET state=?',(json.dumps({**self.state,'decision':{'action':'approve_test_revision'}}),))
        with self.assertRaises(ValueError):feedback.validate_parent(con,config)

    def test_live_parent_requires_exact_supersession_and_original_contract(self):
        config=self.config();con=self.parent_db(config)
        con.execute('UPDATE remediation_executions SET state=?',(json.dumps(self.execution),))
        with self.assertRaises(ValueError):feedback.validate_parent(con,config)

    def test_fresh_planning_prompt_contains_actual_correction_without_grant(self):
        config=self.config()
        instruction=plans.instruction(config,dict(stage='plan_dispatch'))
        self.assertIn('correction',instruction)
        self.assertIn('fresh R1/R2/R3',instruction)
        self.assertIn('no recursive revision',instruction)
        self.assertEqual(instruction.count('DELIVERY_REMEDIATION_PLAN_LENGTH_FEEDBACK_V1'),1)
        self.assertIn('reason<=600',instruction)
        self.assertIn('objective<=240',instruction)
        self.assertLess(len(instruction),3900)

    def test_fresh_intake_enables_only_prose_correction_not_authority(self):
        import remediation_plan_contract as contract
        import typed_decision_contract as typed
        from structured_response_contract import StructuredResponseRejected
        config=self.config();sha=plans.digest(config)
        body=typed.apply(dict(messages=[dict(role='user',content=plans.instruction(config,dict(stage='plan_dispatch')))],
            response_format=dict(type='json_schema',json_schema=dict(name='delivery_decision_v1',strict=True,
                schema=contract.schema('plan',sha,['A01'])))))
        value=dict(action='propose_remediation_plan',evidence_sha256=sha,reason='x'*601,
            execution_authorized=False,release_homologated=False,steps=[dict(id='R'+str(i),
                depends_on=[] if i==1 else ['R'+str(i-1)],edit_scope=scope,
                objective='Preserve gates',criteria=['A01']) for i,scope in
                enumerate(('new_tests_only','product_only','controller_only'),1)])
        def wire():
            return json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(content=None,
                tool_calls=[dict(type='function',function=dict(name=typed.REMEDIATION_NAME,
                    arguments=json.dumps(value)))]))])).encode()
        with self.assertRaises(StructuredResponseRejected) as rejected:
            typed.translate(body,wire(),'application/json')
        self.assertTrue(getattr(rejected.exception,'length_feedback',None))
        value['execution_authorized']=True
        with self.assertRaises(StructuredResponseRejected) as forbidden:
            typed.translate(body,wire(),'application/json')
        self.assertFalse(getattr(forbidden.exception,'length_feedback',None))
