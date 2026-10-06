import copy
import json
from types import SimpleNamespace
import unittest
from jsonschema import ValidationError
from broker.technical_remediation_plan import advance, validate_result, instruction, digest, criteria, DispatchObservationRequired
from execution_context import freeze
from remediation_plan_contract import schema
from decision_schema import apply


class TechnicalRemediationPlanTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(source_task='source',cto='cto',reviewer='lead',criteria={'A01':'criterion','A02':'other'},
                         required_paths=['/evidence/candidate/tests/test_new.py'],original_depth=2)
        self.reads={self.config['required_paths'][0]:dict(lines=20,total_lines=20)}
        self.plan=dict(action='propose_remediation_plan',evidence_sha256=digest(self.config),
            reason='Repair fixture timing and filtered counters without dropping coverage.',
            execution_authorized=False,release_homologated=False,steps=[dict(id='R'+str(i),
                depends_on=[] if i==1 else ['R'+str(i-1)],edit_scope=scope,objective='Verified step',
                criteria=['A01','A02']) for i,scope in enumerate(('new_tests_only','product_only','controller_only'),1)])
        self.task=dict(id='plan-task',agent_id='cto',issue_id='plan-issue',wakeup_id='wake-plan',status='completed')
        self.state=dict(stage='awaiting_plan',issue_id='plan-issue',owner='cto',wakeup_id='wake-plan',
                        execution_authorized=False,release_homologated=False,dispatched_at=100)

    def test_plan_then_exact_independent_review_never_authorizes_execution(self):
        fx=SimpleNamespace(task=lambda *args:self.task,result=lambda _:self.plan,reads=lambda _:self.reads)
        s=advance(self.config,self.state,[self.task],fx,now=120)
        self.assertEqual(s['stage'],'review_dispatch')
        self.assertEqual(s['owner'],'lead')
        self.assertEqual(self.config['original_depth'],2)
        fx.wake=lambda *args:dict(id='wake-review')
        s=advance(self.config,s,[],fx,now=130)
        reviewer=dict(id='review-task',agent_id='lead',issue_id='plan-issue',wakeup_id='wake-review',status='completed')
        value=dict(decision='approve_plan',evidence_sha256=digest(self.plan),plan_sha256=digest(self.plan),
                   reason='Complete scope and preserved gates.',execution_authorized=False,release_homologated=False)
        fx.task=lambda *args:reviewer;fx.result=lambda _:value
        s=advance(self.config,s,[reviewer],fx,now=140)
        self.assertEqual(s['stage'],'plan_approved')
        self.assertFalse(s['execution_authorized'])
        self.assertFalse(s['release_homologated'])
        self.assertNotEqual(s['plan_task'],s['review_task'])

    def test_omitted_criterion_and_wrong_dependencies_rejected(self):
        for mutate in (lambda p:p['steps'][0].update(criteria=['A01']),
                       lambda p:p['steps'][1].update(depends_on=[]),
                       lambda p:p['steps'][0].update(edit_scope='product_only')):
            p=copy.deepcopy(self.plan);mutate(p)
            with self.assertRaises(ValueError):
                validate_result(self.config,self.state,self.task,p,self.reads)

    def test_incomplete_reads_or_other_task_cannot_create_contract(self):
        for field,value in [('agent_id','lead'),('wakeup_id','old'),('issue_id','other'),('status','failed')]:
            task={**self.task,field:value}
            with self.assertRaises(ValueError):
                validate_result(self.config,self.state,task,self.plan,self.reads)
        with self.assertRaises(ValueError):
            validate_result(self.config,self.state,self.task,self.plan,{})

    def test_stale_or_self_review_rejected(self):
        state={**self.state,'stage':'awaiting_review','plan_sha256':digest(self.plan)}
        value=dict(decision='approve_plan',plan_sha256='0'*64,evidence_sha256='0'*64,reason='bad',
                   execution_authorized=False,release_homologated=False)
        task={**self.task,'agent_id':'lead'}
        with self.assertRaises(ValidationError):validate_result(self.config,state,task,value,self.reads)
        value.update(plan_sha256=digest(self.plan),evidence_sha256=digest(self.plan))
        with self.assertRaises(ValueError):validate_result(self.config,state,self.task,value,self.reads)

    def test_terminal_plan_is_not_dispatched_again(self):
        s={**self.state,'stage':'plan_approved'}
        self.assertEqual(advance(self.config,s,[],SimpleNamespace()),s)

    def test_uncertain_wakeup_is_observed_not_recreated(self):
        def failed(*args):raise DispatchObservationRequired()
        fx=SimpleNamespace(wake=failed)
        s=advance(self.config,{**self.state,'stage':'plan_dispatch'},[],fx,now=120)
        self.assertEqual(s['stage'],'observe_dispatch')
        fx.observe_wake=lambda *args:dict(id='accepted-wake')
        fx.wake=lambda *args:self.fail('must not create another wakeup')
        s=advance(self.config,s,[],fx,now=125)
        self.assertEqual(s['stage'],'awaiting_plan')
        self.assertEqual(s['wakeup_id'],'accepted-wake')

    def test_absent_uncertain_wakeup_remains_a_visible_hold(self):
        s={**self.state,'stage':'observe_dispatch','dispatch_phase':'plan_dispatch','observation_started':100}
        fx=SimpleNamespace(observe_wake=lambda *args:None)
        result=advance(self.config,s,[],fx,now=120)
        self.assertEqual(result['stage'],'blocked')
        self.assertIn('no repeated POST',result['required_action'])

    def test_uncertain_issue_is_observed_without_another_create(self):
        calls=[]
        def issue(*args,**kwargs):
            calls.append(kwargs)
            if not kwargs:raise TimeoutError()
            self.assertFalse(kwargs['allow_create'])
            return dict(id='existing-plan-issue')
        fx=SimpleNamespace(issue=issue)
        state=dict(stage='issue_intent',owner='cto',execution_authorized=False)
        state=advance(self.config,state,[],fx,now=100)
        self.assertEqual(state['stage'],'observe_issue')
        state=advance(self.config,state,[],fx,now=110)
        self.assertEqual(state['stage'],'plan_dispatch')
        self.assertEqual(state['issue_id'],'existing-plan-issue')
        self.assertEqual(calls,[{},dict(allow_create=False)])

    def test_missing_handle_observation_does_not_restart(self):
        s=advance(self.config,self.state,[],SimpleNamespace(),now=701)
        self.assertEqual(s['stage'],'blocked')
        self.assertIn('no identical restart',s['required_action'])
        self.assertFalse(s['execution_authorized'])

    def test_live_task_observed_before_deadline(self):
        run={**self.task,'status':'running'}
        self.assertEqual(advance(self.config,self.state,[run],SimpleNamespace(),now=700),self.state)

    def test_retain_hold_is_not_fake_success(self):
        p={**self.plan,'action':'retain_hold','steps':[]}
        fx=SimpleNamespace(task=lambda *args:self.task,result=lambda _:p,reads=lambda _:self.reads)
        result=advance(self.config,self.state,[self.task],fx,now=150)
        self.assertEqual(result['stage'],'blocked')

    def test_criteria_come_losslessly_from_hash_bound_capsule(self):
        capsule=freeze('Agent-authored C2: Example Acceptance: ["unicode …", "criterion"]\nMore input','review')
        self.assertEqual(criteria(capsule),{'A01':'unicode …','A02':'criterion'})
        capsule['description']+='changed'
        with self.assertRaises(ValueError):criteria(capsule)

    def test_proxy_plan_schema_cannot_assert_execution(self):
        from jsonschema import Draft202012Validator
        p={**self.plan,'execution_authorized':True}
        self.assertFalse(Draft202012Validator(schema('plan',digest(self.config),['A01','A02'])).is_valid(p))

    def test_bounded_instruction_and_force_read_before_custom_plan_schema(self):
        note=instruction(self.config,{**self.state,'stage':'plan_dispatch'})
        self.assertLess(len(note)+100,4000)
        body=dict(messages=[dict(role='user',content=note)],tools=[dict(type='function',function=dict(name='read_file'))])
        result=apply(body)
        self.assertEqual(result['tool_choice']['function']['name'],'read_file')
        # Contract shape is independently tested without inventing read receipts.
        from remediation_plan_contract import apply_properties
        props=apply_properties(dict(messages=[dict(role='user',content=note)]),{},'technical')
        self.assertEqual(props['action']['enum'],['propose_remediation_plan','retain_hold'])
        self.assertEqual(props['execution_authorized']['enum'],[False])


class RemediationNativeIssueObservationTests(unittest.TestCase):
    def test_absent_issue_observation_cannot_post(self):
        from broker.incremental_provisioning import NativeIssues
        issues=NativeIssues(dict(workspace_id='workspace'))
        calls=[]
        def request(path,body=None):
            calls.append((path,body))
            self.assertIsNone(body)
            return dict(issues=[],total=0)
        issues.request=request
        self.assertIsNone(issues.ensure(dict(title='plan'),allow_create=False))
        self.assertEqual(len(calls),1)


class RemediationPlanIntakeTests(unittest.TestCase):
    from tests.test_service_mode_schema_evidence import ServiceModeSchemaEvidenceTests as fixture
    db=fixture.db
    run_register=fixture.run_register
    enrich=fixture.enrich

    def setUp(self):
        from unittest.mock import Mock
        from broker import handoff_runtime,technical_remediation_plan as plan
        self.fixture.setUp(self)
        self.enrich()
        self.fx=Mock()
        self.task=dict(id='fresh-cto',status='completed',agent_id='cto',issue_id='issue',wakeup_id='fresh-wake')
        self.decision=dict(action='request_test_revision',reason='Verified timing defect.',optional_files=[])
        self.fx.decision.return_value=self.decision
        self.fx.read_evidence.return_value={'/evidence/candidate/'+p:dict(lines=50,total_lines=50)
                                          for p in plan.service_mode_schema_evidence.probe.READ_FILES}
        self.runs=[self.task,dict(id=self.source,agent_id='author',status='failed')]
        self.broker.issue_base=lambda _:dict(base_sha='0'*40,volume='verified-base',manifest_sha256='f'*64)
        (self.broker.STATE/'native.json').write_text(json.dumps(dict(agents=dict(cto='planning',lead='planning'))))
        with self.db() as con:
            from broker import handoffs
            row=handoffs.load(con,self.source);d=json.loads(row['data'])
            d.update(recipient_task='fresh-cto',wakeup_id='fresh-wake',target='cto',decision=self.decision,
                     test_revision_proposal=dict(source_task=self.source,decision_task='fresh-cto'))
            handoffs.save(con,self.source,'issue','test_revision_required','reviewer',d,400)
            route=json.loads(con.execute('SELECT config FROM delivery_routes').fetchone()[0])
            route.update(techlead='lead',contract_sha256='a'*64,execution_context=freeze(
                'Agent-authored C2: Test Acceptance: ["criterion", "other"]\nApproved brief','review'))
            con.execute('UPDATE delivery_routes SET config=?',(json.dumps(route),))
            con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT)')
            for issue,parent in [('issue','parent'),('parent','root')]:
                con.execute('INSERT INTO test_revision_trials VALUES(?,?)',(issue,json.dumps(dict(parent_issue=parent,base_sha='0'*40))))
            con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('root',json.dumps(dict(initial_review=True,base_sha='0'*40))))

    def intake(self):
        from broker import native,handoff_runtime,technical_remediation_plan as plan
        from unittest.mock import patch
        with patch.object(native,'task_record',return_value=self.task), \
             patch.object(native,'issue_task_runs',return_value=self.runs), \
             patch.object(handoff_runtime,'Effects',return_value=self.fx):
            return plan.register(self.broker,self.source)

    def test_source_lineage_and_criteria_preserved_without_third_revision(self):
        from broker import handoffs
        s=self.intake();self.assertEqual(s['stage'],'issue_intent')
        self.assertEqual(self.intake(),s)
        with self.db() as con:
            config=json.loads(con.execute('SELECT config FROM technical_remediation_plans').fetchone()[0])
            self.assertEqual(config['original_depth'],2)
            self.assertEqual(config['revision_lineage'],['issue','parent'])
            self.assertEqual(config['root_issue'],'root')
            self.assertEqual(config['criteria'],{'A01':'criterion','A02':'other'})
            row=handoffs.load(con,self.source);data=json.loads(row['data'])
            self.assertEqual(row['stage'],'technical_decision_required')
            self.assertIn('failed_execution_diagnostic',data)
            self.assertIn('exhausted_revision_proposal',data)
            self.assertFalse(data['technical_remediation_plan']['execution_authorized'])
            self.assertFalse(json.loads(con.execute('SELECT config FROM delivery_routes').fetchone()[0])['enabled'])

    def test_incomplete_native_read_does_not_create_plan(self):
        self.fx.read_evidence.return_value={}
        with self.assertRaisesRegex(ValueError,'complete immutable'):
            self.intake()

    def test_single_revision_cannot_claim_exhaustion(self):
        with self.db() as con:con.execute("DELETE FROM test_revision_trials WHERE issue_id='parent'")
        with self.assertRaisesRegex(ValueError,'exactly two'):
            self.intake()

    def test_initial_review_is_not_a_third_revision(self):
        state=self.intake()
        self.assertEqual(state['stage'],'issue_intent')
        with self.db() as con:
            config=json.loads(con.execute('SELECT config FROM technical_remediation_plans').fetchone()[0])
            self.assertEqual(config['original_depth'],2)
            self.assertEqual(config['root_issue'],'root')

    def parser_fault(self):
        from broker.technical_remediation_plan import initialize
        with self.db() as con:
            initialize(con)
            con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',(self.source,'{}',json.dumps(
                dict(stage='blocked',owner='cto',category='KeyError',execution_authorized=False,
                     required_action='CTO diagnose rejected remediation intake; no identical retry'))))

    def test_parser_fault_recovery_preserves_original_block_without_depth_reset(self):
        self.parser_fault()
        s=self.intake()
        self.assertEqual(s['stage'],'issue_intent')
        self.assertEqual(s['intake_repair']['previous']['category'],'KeyError')
        self.assertFalse(s['intake_repair']['revision_depth_reset'])
        self.assertFalse(s['execution_authorized'])
        self.assertEqual(self.intake(),s)

    def test_parser_repair_failure_is_fenced_not_retried(self):
        self.parser_fault()
        self.fx.read_evidence.return_value={}
        with self.assertRaises(ValueError):self.intake()
        self.fx.read_evidence.return_value={'/evidence/candidate/'+p:dict(lines=50,total_lines=50)
                                          for p in self.proof['input_sha256']}
        s=self.intake()
        self.assertEqual(s['stage'],'blocked')
        self.assertTrue(s['initial_root_parser_repair_attempted'])
