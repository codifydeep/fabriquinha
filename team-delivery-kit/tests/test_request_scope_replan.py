import copy
import unittest
from broker.request_scope_replan import config,payload,supports_request_scope
from broker.technical_remediation_plan import digest,instruction
from service_mode_harness_qualification import TEST,CASES


class RequestScopeReplanTests(unittest.TestCase):
    def test_unrelated_failure_routes_to_cto_before_any_docker_effect(self):
        import json,sqlite3,threading
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import request_scope_replan as module,handoffs
        proposal,peer,_,reference,_,route,_=self.fixture()
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con);con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
        con.execute('CREATE TABLE leases(status TEXT)');con.execute("INSERT INTO snapshots VALUES('source','frozen','complete')")
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',('r2',json.dumps(route)))
        data=dict(inherited_test_replan=proposal,inherited_peer_review=peer,
            completed_validation_diagnostic=dict(volume='frozen'),validation_failure=dict(
                category='executed_test_failure',diagnostic_read_files=['tests/test_feedback_latest_ui.py'],
                failures=[dict(qualified_name='tests.test_feedback_latest_ui.FeedbackLatestMatchClientTest.test_poll_and_filter_change_request_latest')]))
        handoffs.save(con,'source','r2','inherited_replan_required','cto',data,0)
        @contextmanager
        def db():
            with con:yield con
        def docker(*args):raise AssertionError('unsupported recipe must not touch Docker')
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),docker=docker,OWNER='owner',PREFIX='delivery-kit-port2')
        with patch.object(module.refs,'qualified',return_value=reference):module.advance(b,proposal,peer)
        current=handoffs.load(con,'source');self.assertEqual(current['stage'],'diagnose_cto')
        self.assertFalse(json.loads(current['data'])['unsupported_recipe_route']['docker_effects_executed'])
        self.assertEqual(con.execute('SELECT count(*) FROM request_scope_experiments').fetchone()[0],0)
    def test_fixed_recipe_does_not_accept_an_unrelated_peer_test_revision_vote(self):
        failure=dict(category='executed_test_failure',diagnostic_read_files=[TEST],failures=[
            dict(qualified_name='tests.test_service_mode_indicator.ServiceModeClientTests.'+name) for name in (
                'test_client_requests_service_mode_once_at_load','test_exactly_one_request_per_page_load_across_all_loads',
                'test_pending_probe_shows_checking_then_terminal_demo')])
        reference=dict(red=dict(red=dict(test_sha256={TEST:'a'*64})))
        self.assertTrue(supports_request_scope(failure,reference))
        failure['failures']=[dict(qualified_name='tests.test_feedback_latest_ui.FeedbackLatestMatchClientTest.test_poll_and_filter_change_request_latest')]
        self.assertFalse(supports_request_scope(failure,reference))
        self.assertFalse(supports_request_scope({},reference))
    def fixture(self):
        good=dict(tests=15,failures=0,errors=0,skipped=0,unexpected_successes=0,expected_failures=0,failed_methods=[])
        bad={**good,'tests':1,'failures':1}
        baseline={**good,'failures':3,'failed_methods':sorted([
            'test_client_requests_service_mode_once_at_load','test_exactly_one_request_per_page_load_across_all_loads',
            'test_pending_probe_shows_checking_then_terminal_demo'])}
        previous=dict(source_task='previous',criteria={'A01':'entire scope'},original_depth=2,root_issue='root',
            revision_lineage=['old2','old1'],steps=[{},dict(owner='author')],contract_sha256='a'*64,
            base=dict(base_sha='b'*40,manifest_sha256='c'*64),amendment=dict(operation='inherited_harness_contract_amendment_v1'))
        reference=dict(source_task='previous',issue_id='r2',execution_contract_sha256=digest(previous),
            criteria=previous['criteria'],red=dict(task_id='red',red=dict(test_sha256={TEST:'d'*64})))
        proposal=dict(source_task='source',issue_id='r2',reference_sha256=digest(reference),criteria=previous['criteria'],
            original_depth=2,reviewer='lead',cto_task='cto-task',cto_wakeup='cto-wake',required_paths=['/evidence/candidate/'+TEST])
        peer=dict(stage='peer_reviewed',decision=dict(action='request_test_revision'),execution_authorized=False,task_id='peer')
        result=dict(operation='immutable_request_scope_experiment_v1',status='experiment_only_not_approved',
            baseline=baseline,scoped=good,background_control=good,negative_controls={case:bad for case in CASES},
            actual_duplicate_control=bad,test_sha256='d'*64,product_sha256='e'*64,manifest_sha256='f'*64,
            snapshot_modified=False,assertions_modified=False,test_edits_authorized=False,delivery_approval=False,product_green=False)
        route=dict(issue_id='r2',author='author',reviewer='reviewer',techlead='lead',cto='cto',contract_sha256='a'*64,
            execution_context=dict(sha256='f'*64))
        return proposal,peer,result,reference,previous,route,'frozen'

    def test_distinct_fault_keeps_previous_amendment_depth_criteria_and_all_gates(self):
        args=self.fixture();value=config(*args)
        self.assertEqual(value['criteria'],args[4]['criteria']);self.assertEqual(value['revision_lineage'],['old2','old1'])
        self.assertEqual(value['amendment']['previous_amendment_sha256'],digest(args[4]['amendment']))
        self.assertFalse(value['amendment']['execution_authorized']);self.assertFalse(value['amendment']['revision_depth_reset'])
        note=instruction(value,dict(stage='plan_dispatch'))
        self.assertIn('background-traffic calibration',note)
        self.assertNotIn('fails Node syntax compilation',note)
        self.assertIn('A01',note)

    def test_replayed_same_fault_or_weakened_experiment_and_roles_are_rejected(self):
        for slot,key,new in ((1,'task_id',None),(1,'execution_authorized',True),(2,'test_sha256','0'*64),
            (2,'snapshot_modified',True),(2,'product_green',True),(0,'criteria',{'A01':'weakened'}),
            (0,'reference_sha256','0'*64),(5,'cto','author')):
            args=list(copy.deepcopy(self.fixture()));args[slot][key]=new
            with self.subTest(key=key),self.assertRaises(ValueError):config(*args)
        args=list(copy.deepcopy(self.fixture()));args[4]['amendment']['kind']='request_scope'
        args[3]['execution_contract_sha256']=digest(args[4]);args[0]['reference_sha256']=digest(args[3])
        with self.assertRaises(ValueError):config(*args)

    def test_job_has_fixed_command_and_no_network_socket_or_credentials(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import request_scope_replan as module
        b=SimpleNamespace(OWNER='owner',docker=lambda *a:None)
        with patch.object(module.jobs,'image_environment',return_value=['PATH=/usr/bin']):
            p=payload(b,'source','frozen')
        self.assertEqual(p['Cmd'],['/service_mode_request_scope_experiment.py','/delivery'])
        self.assertTrue(p['NetworkDisabled']);self.assertEqual(p['HostConfig']['NetworkMode'],'none')
        self.assertEqual(p['HostConfig']['Mounts'],[dict(Type='volume',Source='frozen',Target='/delivery',ReadOnly=True)])
        self.assertTrue(p['HostConfig']['ReadonlyRootfs'])

    def test_uncertain_create_is_observed_not_repeated_after_restart(self):
        import json,sqlite3,threading
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import request_scope_replan as module,handoffs
        proposal,peer,result,reference,previous,route,volume=self.fixture()
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;handoffs.initialize(con)
        con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
        con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('CREATE TABLE request_scope_experiments(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        con.execute("INSERT INTO snapshots VALUES('source','frozen','complete')")
        con.execute('INSERT INTO delivery_routes VALUES (?,?)',('r2',json.dumps(route)))
        data=dict(inherited_test_replan=proposal,inherited_peer_review=peer,
            completed_validation_diagnostic=dict(volume='frozen'))
        handoffs.save(con,'source','r2','inherited_replan_required','cto',data,0)
        @contextmanager
        def db():yield con
        calls=[]
        def docker(method,path,*args):
            calls.append((method,path))
            if path=='/volumes/frozen':return dict(Labels={'delivery-kit.owner':'owner','delivery-kit.source-task':'source'})
            return None
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),docker=docker,OWNER='owner',PREFIX='delivery-kit-port2')
        with patch.object(module.jobs,'image_environment',return_value=[]),patch.object(module.refs,'qualified',return_value=reference):
            identity=dict(source_task='source',issue_id='r2',volume='frozen',proposal_sha256=digest(proposal),
                peer_task=peer['task_id'],peer_decision_sha256=digest(peer['decision']),payload=payload(b,'source','frozen'))
            con.execute('INSERT INTO request_scope_experiments VALUES(?,?,?)',('source',json.dumps(identity),json.dumps(dict(stage='create_intent',at=0))))
            module.tick_one(b,proposal,peer);module.tick_one(b,proposal,peer)
        state=json.loads(con.execute('SELECT state FROM request_scope_experiments').fetchone()[0])
        self.assertEqual(state['stage'],'blocked');self.assertIn('no repeated POST',state['required_action'])
        self.assertFalse(any(method=='POST' for method,_ in calls))
        con.close()

    def test_approved_continuation_waits_for_preparation_without_reprovisioning(self):
        import json,sqlite3,threading
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import request_scope_replan as module,remediation_execution as execution,remediation_preparation,remediation_author_context
        proposal,peer,result,reference,previous,route,volume=self.fixture()
        cfg=config(proposal,peer,result,reference,previous,route,volume)
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        con.execute('CREATE TABLE technical_remediation_plans(source_task TEXT,config TEXT,state TEXT)')
        con.execute('CREATE TABLE remediation_admissions(source_task TEXT,intent TEXT)')
        con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',('source',json.dumps(cfg),json.dumps(dict(stage='plan_approved'))))
        con.execute('INSERT INTO remediation_admissions VALUES(?,?)',('previous',json.dumps(dict(root_issue='root',execution_contract_sha256=reference['execution_contract_sha256']))))
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db,LOCK=threading.RLock())
        with patch.object(execution,'register',return_value=dict(stage='r1_provision_pending')),patch.object(execution,'provision_issue') as create,patch.object(remediation_preparation,'prepare') as prepare:
            module.continue_approved(b,'source',result);create.assert_not_called()
            prepare.assert_called_once_with(b,'source')
        with patch.object(execution,'register',return_value=dict(stage='r1_base_qualified')),patch.object(execution,'provision_issue') as create,patch.object(remediation_author_context,'prepare') as runtime:
            module.continue_approved(b,'source',result);create.assert_not_called()
            runtime.assert_called_once_with(b,'source')
        con.execute('DELETE FROM remediation_admissions')
        with self.assertRaises(ValueError):module.continue_approved(b,'source',result)
        con.close()
