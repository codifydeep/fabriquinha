import json
import unittest
from unittest.mock import patch
from broker import surgical_recovery as recovery,handoffs,test_first_handoffs
import test_test_artifact_recovery as fixtures
from test_test_first_handoffs import Effects


class SurgicalRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ArtifactRecoveryTests();fixture.setUp();fixture.framework_setup()
        self.addCleanup(fixture.doCleanups)
        self.f=fixture;self.b=fixture.b
        self.request=dict(issue_id=fixture.issue,source_task=fixture.source,failure=dict(
            origin='operator_verified_historical_proxy_metadata',category='artifact_test_methods_missing',
            status=502,execution_id='request',call_number=10))
        with self.b.db() as con:
            con.execute('ALTER TABLE test_first_red ADD COLUMN task_id TEXT')
            con.execute('ALTER TABLE test_first_red ADD COLUMN receipt TEXT')
            con.execute('CREATE TABLE native_bindings(task_id TEXT,request_id TEXT)')
            con.execute('INSERT INTO native_bindings VALUES(?,?)',(fixture.source,'request'))
            row=handoffs.load(con,'old');data=json.loads(row['data'])
            data['framework_replan']={'qualified':True};data['test_first_cto_wakeup']='cto-wake'
            handoffs.save(con,'old',fixture.issue,row['stage'],'author',data,1)

    def arm(self):
        with patch('broker.native.issue_task_runs',return_value=self.f.runs),patch(
                'broker.handoff_runtime.Effects') as effects,patch(
                'broker.artifact_transport_recovery.verify_preserved_failure',return_value={
                    'verified':True,'baseline_unchanged':True,'task_id':self.f.source,'manifest_sha256':'b'*64}):
            effects.return_value.decision.return_value=self.f.decision
            return recovery.arm(self.b,self.request)

    def test_one_arm_dispatch_and_exact_wakeup_only(self):
        config=self.arm();self.assertEqual(config,self.arm())
        effects=Effects(self.b)
        with self.b.db() as con:prior=handoffs.load(con,self.f.source)
        test_first_handoffs.technical_recovery(self.b,self.f.route,self.f.runs,self.f.runs[0],prior,effects)
        with self.b.db() as con:prior=handoffs.load(con,self.f.source)
        test_first_handoffs.technical_recovery(self.b,self.f.route,self.f.runs,self.f.runs[0],prior,effects)
        self.assertEqual(len(effects.wakeups),1)
        self.assertEqual(prior['stage'],'test_first_surgical_recovery_wait')
        task=dict(id='new-task',agent_id='author',wakeup_id='wakeup')
        self.assertEqual(recovery.for_task(self.b,self.f.issue,task),
                         {'path':'/workspace/tests/test_new.py','expected_sha256':'c'*64})
        with self.assertRaises(ValueError):recovery.for_task(self.b,self.f.issue,{**task,'wakeup_id':'wrong'})
        self.assertIsNone(recovery.for_task(self.b,self.f.issue,self.f.runs[0]))
        with self.b.db() as con:con.execute('INSERT INTO test_first_red(issue_id) VALUES(?)',(self.f.issue,))
        self.assertIsNone(recovery.for_task(self.b,self.f.issue,task))

    def test_rejected_execution_or_stale_task_never_reopens(self):
        self.request['failure']['execution_id']='unrelated'
        with self.assertRaisesRegex(ValueError,'execution drift'):self.arm()
        self.request['failure']['execution_id']='request'
        self.f.runs[0]['status']='running'
        with self.assertRaisesRegex(ValueError,'idle completed'):self.arm()

    def test_consumed_surgical_policy_cannot_block_later_regular_author(self):
        self.arm()
        with self.b.db() as con:
            old=handoffs.load(con,self.f.source)
            handoffs.save(con,self.f.source,self.f.issue,'test_first_cto_correction_wait','author',json.loads(old['data']),2)
        self.assertIsNone(recovery.for_task(self.b,self.f.issue,dict(id='later-author',agent_id='author',wakeup_id='new-qualified-wake')))

    def test_failed_surgical_worker_cannot_use_generic_idle_retry(self):
        self.arm();effects=Effects(self.b)
        with self.b.db() as con:prior=handoffs.load(con,self.f.source)
        test_first_handoffs.technical_recovery(self.b,self.f.route,self.f.runs,self.f.runs[0],prior,effects)
        failed=dict(id='failed-surgical',agent_id='author',status='failed',failure_reason='idle_watchdog',
                    wakeup_id='wakeup',created_at='03')
        runs=[*self.f.runs,failed]
        test_first_handoffs.reconcile(self.b,self.f.route,runs,effects)
        test_first_handoffs.reconcile(self.b,self.f.route,runs,effects)
        self.assertEqual(len(effects.wakeups),1)
        with self.b.db() as con:self.assertEqual(handoffs.load(con,failed['id'])['stage'],'test_first_blocked')

    def test_typed_recovery_preserves_v1_and_can_only_arm_once(self):
        original=self.arm();effects=Effects(self.b)
        with self.b.db() as con:prior=handoffs.load(con,self.f.source)
        test_first_handoffs.technical_recovery(self.b,self.f.route,self.f.runs,self.f.runs[0],prior,effects)
        failed='44444444-4444-4444-8444-444444444444'
        failure=dict(kind='surgical_pre_tool_rejection_v1',category='invalid_surgical_response',
            status=502,write_tool_calls=0,task_id=failed,execution_id='execution')
        with self.b.db() as con:
            con.execute('INSERT INTO native_bindings VALUES(?,?)',(failed,'execution'))
            handoffs.save(con,failed,self.f.issue,'test_first_blocked','cto',dict(
                error='test_first_correction_failed_after_cto_diagnosis',transport_failure_receipt=failure),3)
        proof=dict(schema='surgical-typed-registry-probe-v2',status='passed',delivery_approval=False,
            network='none',credentials_absent=True,actual_registry=True,actual_default_selection=True,
            actual_acp_selection=True,full_proxy_request_validation=True,fixture_removed=True,
            preserved_bodies=True,stale_edit_denied=True,legacy_write_denied=True,readless_edit_denied=True,
            response_gate_qualified=True,worker_image=self.b.IMAGE,proxy_image='sha256:'+'d'*64)
        request=dict(issue_id=self.f.issue,source_task=failed,qualification=proof)
        self.b.PREFIX='project'
        self.b.docker=lambda *a:dict(Image=proof['proxy_image'],State=dict(Running=True),
            Config=dict(Labels={'com.docker.compose.project':'project'}))
        runs=[*self.f.runs,dict(id=failed,agent_id='author',status='failed',created_at='03',wakeup_id='wakeup')]
        with patch('broker.native.issue_task_runs',return_value=runs),patch(
            'broker.artifact_transport_recovery.verify_preserved_failure',return_value=dict(verified=True,baseline_unchanged=True)):
            result=recovery.arm_typed(self.b,request)
            self.assertEqual(result['previous_grant'],original)
            self.assertEqual(result['protocol'],'typed_v2')
            self.assertEqual(result,recovery.arm_typed(self.b,request))
            with self.assertRaisesRegex(ValueError,'already consumed'):
                recovery.arm_typed(self.b,{**request,'qualification':{**proof,'proxy_image':'sha256:'+'e'*64}})
        with self.b.db() as con:prior=handoffs.load(con,failed)
        test_first_handoffs.technical_recovery(self.b,self.f.route,runs,runs[-1],prior,effects)
        self.assertEqual(len(effects.wakeups),2)
        self.assertIn('surgical_test_edit',effects.wakeups[-1][0][4])
        self.assertNotIn('write_file JSON-envelope',effects.wakeups[-1][0][4])
        grant=recovery.for_task(self.b,self.f.issue,dict(id='typed-author',agent_id='author',wakeup_id='wakeup'))
        self.assertEqual(grant['protocol'],'typed_v2')

    def selection_fixture(self):
        original=self.arm();effects=Effects(self.b)
        with self.b.db() as con:prior=handoffs.load(con,self.f.source)
        test_first_handoffs.technical_recovery(self.b,self.f.route,self.f.runs,self.f.runs[0],prior,effects)
        task='55555555-5555-4555-8555-555555555555'
        proof=dict(schema='surgical-typed-registry-probe-v2',status='passed',delivery_approval=False,
            network='none',credentials_absent=True,actual_registry=True,actual_default_selection=True,
            actual_acp_selection=True,full_proxy_request_validation=True,fixture_removed=True,
            preserved_bodies=True,stale_edit_denied=True,legacy_write_denied=True,readless_edit_denied=True,
            response_gate_qualified=True,worker_image=self.b.IMAGE,proxy_image='sha256:'+'d'*64)
        failure=dict(kind='typed_tool_selection_failure_v2',task_id=task,issue_id=self.f.issue,
            execution_id='selection-execution',observed_proxy_category='invalid_request',status=400,
            model_calls_consumed=0,tool_calls=0,old_default_selection_has_tool=False,
            corrected_default_selection_has_tool=True,
            origin='operator_verified_proxy_metadata_and_offline_negative_control')
        old={**original,'protocol':'typed_v2','typed_request':{'source_task':'historic'}}
        with self.b.db() as con:
            con.execute('UPDATE surgical_test_recoveries SET config=? WHERE issue_id=?',(json.dumps(old),self.f.issue))
            con.execute('INSERT INTO native_bindings VALUES(?,?)',(task,'selection-execution'))
            handoffs.save(con,task,self.f.issue,'test_first_blocked','cto',dict(
                error='test_first_correction_failed_after_cto_diagnosis',typed_selection_failure=failure),3)
        self.b.PREFIX='project';self.b.docker=lambda *a:dict(Image=proof['proxy_image'],State=dict(Running=True),
            Config=dict(Labels={'com.docker.compose.project':'project'}))
        runs=[*self.f.runs,dict(id=task,agent_id='author',status='completed',created_at='03',wakeup_id='wakeup')]
        return dict(issue_id=self.f.issue,source_task=task,qualification=proof),old,runs

    def selection_arm(self,request,runs):
        with patch('broker.native.issue_task_runs',return_value=runs),patch('broker.native.task_messages',return_value=[]),patch(
            'broker.artifact_transport_recovery.verify_preserved_failure',return_value=dict(verified=True,baseline_unchanged=True)):
            return recovery.arm_selection(self.b,request)

    def test_selection_recovery_preserves_failure_and_dispatches_once(self):
        request,old,runs=self.selection_fixture()
        result=self.selection_arm(request,runs)
        self.assertEqual(result['previous_grant'],old)
        self.assertEqual(result,self.selection_arm(request,runs))
        effects=Effects(self.b)
        with self.b.db() as con:prior=handoffs.load(con,request['source_task'])
        test_first_handoffs.technical_recovery(self.b,self.f.route,runs,runs[-1],prior,effects)
        with self.b.db() as con:prior=handoffs.load(con,request['source_task'])
        test_first_handoffs.technical_recovery(self.b,self.f.route,runs,runs[-1],prior,effects)
        self.assertEqual(len(effects.wakeups),1)
        with self.b.db() as con:
            data=json.loads(prior['data']);self.assertEqual(data['typed_selection_failure']['status'],400)
        with self.assertRaisesRegex(ValueError,'already consumed'):
            self.selection_arm({**request,'qualification':{**request['qualification'],'proxy_image':'sha256:'+'e'*64}},runs)

    def test_selection_recovery_rejects_red_live_tools_and_stale_source(self):
        request,old,runs=self.selection_fixture()
        with self.assertRaisesRegex(ValueError,'complete tool selection'):
            self.selection_arm({**request,'qualification':{**request['qualification'],'actual_acp_selection':False}},runs)
        runs[-1]['status']='running'
        with self.assertRaisesRegex(ValueError,'latest idle'):self.selection_arm(request,runs)
        runs[-1]['status']='completed'
        with patch('broker.native.task_messages',return_value=[{'type':'tool_use','tool':'read_file'}]),patch(
                'broker.native.issue_task_runs',return_value=runs):
            with self.assertRaisesRegex(ValueError,'no tool execution'):recovery.arm_selection(self.b,request)
        with self.b.db() as con:con.execute('INSERT INTO test_first_red(issue_id) VALUES(?)',(self.f.issue,))
        with self.assertRaisesRegex(ValueError,'Red exists'):self.selection_arm(request,runs)

    def acp_fixture(self):
        request,old,runs=self.selection_fixture()
        old['selection_request']={'source_task':'previous-selection-failure'}
        with self.b.db() as con:
            con.execute('UPDATE surgical_test_recoveries SET config=? WHERE issue_id=?',(json.dumps(old),self.f.issue))
            row=handoffs.load(con,request['source_task']);data=json.loads(row['data'])
            failure=data.pop('typed_selection_failure')
            failure.update(kind='typed_acp_selection_failure_v2',
                observed_proxy_category='typed surgical tool missing from actual registry',
                origin='operator_verified_proxy_metadata_and_exact_acp_source',baseline_unchanged=True)
            data['typed_acp_selection_failure']=failure
            handoffs.save(con,request['source_task'],self.f.issue,row['stage'],row['owner'],data,3)
        return request,old,runs

    def acp_arm(self,request,runs):
        with patch('broker.native.issue_task_runs',return_value=runs),patch('broker.native.task_messages',return_value=[]),patch(
            'broker.artifact_transport_recovery.verify_preserved_failure',return_value=dict(verified=True,baseline_unchanged=True)):
            return recovery.arm_acp_selection(self.b,request)

    def test_acp_recovery_preserves_consumed_selection_and_is_idempotent(self):
        request,old,runs=self.acp_fixture()
        config=self.acp_arm(request,runs)
        self.assertEqual(config['selection_request'],old['selection_request'])
        self.assertEqual(config['previous_grant'],old)
        self.assertEqual(config,self.acp_arm(request,runs))
        with self.assertRaisesRegex(ValueError,'already consumed'):
            self.acp_arm({**request,'qualification':{**request['qualification'],'proxy_image':'sha256:'+'e'*64}},runs)
        effects=Effects(self.b)
        with self.b.db() as con:row=handoffs.load(con,request['source_task'])
        test_first_handoffs.technical_recovery(self.b,self.f.route,runs,runs[-1],row,effects)
        with self.b.db() as con:row=handoffs.load(con,request['source_task'])
        test_first_handoffs.technical_recovery(self.b,self.f.route,runs,runs[-1],row,effects)
        self.assertEqual(len(effects.wakeups),1)

    def test_acp_recovery_requires_exact_failure_and_consumed_selection(self):
        request,old,runs=self.selection_fixture()
        with self.assertRaisesRegex(ValueError,'exact zero-call'):self.acp_arm(request,runs)
        request,old,runs=self.acp_fixture()
        with self.b.db() as con:
            row=handoffs.load(con,request['source_task']);data=json.loads(row['data'])
            data['typed_acp_selection_failure']['execution_id']='unrelated'
            handoffs.save(con,request['source_task'],self.f.issue,row['stage'],row['owner'],data,4)
        with self.assertRaisesRegex(ValueError,'exact zero-call'):self.acp_arm(request,runs)

    def feedback_fixture(self):
        request,old,runs=self.acp_fixture()
        proof=request['qualification'];proof.update(structured_feedback_visible=True,invalid_candidate_preserved=True)
        old['acp_selection_request']={'source_task':'prior-acp-failure'}
        categories=['all tests must remain unittest discoverable','no preserved test methods']
        with self.b.db() as con:
            con.execute('UPDATE surgical_test_recoveries SET config=? WHERE issue_id=?',(json.dumps(old),self.f.issue))
            row=handoffs.load(con,request['source_task']);data=json.loads(row['data'])
            data['surgical_edit_rejections']=dict(kind='rejected_surgical_edits_v2',task_id=request['source_task'],
                issue_id=self.f.issue,execution_id='selection-execution',tool_calls=2,rejected_tool_results=2,
                test_sha256=old['expected_sha256'],baseline_unchanged=True,categories=categories,
                origin='operator_verified_native_results_and_offline_prepare_on_frozen_source')
            handoffs.save(con,request['source_task'],self.f.issue,row['stage'],row['owner'],data,4)
        (self.b.STATE/('surgical-prepare-diagnosis-'+request['source_task']+'.json')).write_text(json.dumps(dict(
            task_id=request['source_task'],input_sha256=old['expected_sha256'],categories=categories,baseline_unchanged=True)))
        messages=[]
        for index in range(2):messages.extend([
            dict(type='tool_use',tool='surgical_test_edit',input=dict(path=old['path'])),
            dict(type='tool_result',tool='surgical_test_edit',output='Error: surgical_edit_rejected')])
        return request,old,runs,messages

    def feedback_arm(self,request,runs,messages):
        with patch('broker.native.issue_task_runs',return_value=runs),patch('broker.native.task_messages',return_value=messages),patch(
            'broker.artifact_transport_recovery.verify_preserved_failure',return_value=dict(verified=True,baseline_unchanged=True)):
            return recovery.arm_feedback(self.b,request)

    def test_feedback_recovery_once_preserves_prior_allowances(self):
        request,old,runs,messages=self.feedback_fixture()
        config=self.feedback_arm(request,runs,messages)
        self.assertEqual(config['previous_grant'],old)
        self.assertEqual(config,self.feedback_arm(request,runs,messages))
        effects=Effects(self.b)
        with self.b.db() as con:row=handoffs.load(con,request['source_task'])
        test_first_handoffs.technical_recovery(self.b,self.f.route,runs,runs[-1],row,effects)
        self.assertIn('unittest_discovery_required',effects.wakeups[0][0][4])
        with self.assertRaisesRegex(ValueError,'already consumed'):
            self.feedback_arm({**request,'qualification':{**request['qualification'],'proxy_image':'sha256:'+'e'*64}},runs,messages)

    def test_feedback_recovery_rejects_weak_probe_and_unrelated_tools(self):
        request,old,runs,messages=self.feedback_fixture()
        with self.assertRaisesRegex(ValueError,'feedback qualification'):
            self.feedback_arm({**request,'qualification':{**request['qualification'],'structured_feedback_visible':False}},runs,messages)
        with self.assertRaisesRegex(ValueError,'exact rejected surgical'):
            self.feedback_arm(request,runs,[*messages,dict(type='tool_use',tool='terminal')])
