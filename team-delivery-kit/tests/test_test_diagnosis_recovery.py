import copy
import unittest
import json
import sqlite3
import tempfile
import threading
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker.test_diagnosis_recovery import prepare


class DiagnosisRecoveryTests(unittest.TestCase):
    def test_automatic_json_recovery_pins_the_installed_qualified_proxy_not_a_retired_image(self):
        from broker.test_diagnosis_recovery import JSON_FEEDBACK_PROXY
        self.assertEqual(JSON_FEEDBACK_PROXY,
            'sha256:7b21bc9b5df472dfdf08f025153b28045b1ccf02e39dd4fdf27b3939c372d193')
        self.assertNotEqual(JSON_FEEDBACK_PROXY,
            'sha256:723efcc5a745f67047bf8478773036d8bb82ca2031441718c161916f6fa45953')

    def test_automatic_admission_requires_idle_and_never_rearms(self):
        from broker.test_diagnosis_recovery import automatic
        args=list(copy.deepcopy(self.fixture()))
        args[6]['category']='typed_arguments_invalid'
        args[6]['response_shape'].update(arguments_json_valid=False,arguments_schema_valid=None)
        saved=[]
        fx=SimpleNamespace(idle=lambda:True,candidate=lambda issue:args,
            persist=lambda issue,prior,updated:saved.append(updated))
        self.assertEqual(automatic(None,'child',fx)['stage'],'fresh_diagnosis_admitted')
        self.assertEqual(len(saved),1)
        self.assertFalse(saved[0]['rejection_diagnosis']['schema_recovery']['delivery_approval'])
        args[0]=saved[0]
        self.assertEqual(automatic(None,'child',fx)['stage'],'recovery_consumed')
        self.assertEqual(len(saved),1)
        fx.idle=lambda:False
        self.assertEqual(automatic(None,'child',fx)['stage'],'awaiting_capacity')
        bad=list(copy.deepcopy(self.fixture()));bad[6]['category']='typed_wrong_tool_name'
        fx.idle=lambda:True;fx.candidate=lambda issue:bad
        with self.assertRaises(ValueError):automatic(None,'child',fx)
        self.assertEqual(len(saved),1)

    def fixture(self):
        task=dict(id='cto-task',issue_id='child',agent_id='cto',wakeup_id='old-wake',status='failed')
        red=dict(task_id='author-task',red={'manifest_sha256':'a'*64})
        route=dict(issue_id='child',author='author',cto='cto',test_first_files=['tests/test_new.py'])
        config=dict(reviewer='reviewer')
        state=dict(status='blocked',evidence_policy=1,terminal_contract='typed-review-v1',
            source_task='author-task',manifest_sha256='a'*64,review_task='review-task',
            rejection_diagnosis=dict(status='blocked',target='cto',wakeup_id='old-wake',
                failure=dict(task_id='cto-task',operation='task_completion',detail='CTO diagnosis did not complete')))
        receipt=dict(operation='rejected_typed_decision_adapter_v1',category='typed_schema_violation',
            upstream_sha256='b'*64,worker_tool_executed=False,delivery_approval=False,
            response_shape=dict(parsed=True,terminal=True,submissions=1,content_shape='empty',
                legacy_function_call=False,expected_tool=True,arguments_json_valid=True,arguments_schema_valid=False))
        reads={f'/evidence/{tree}/tests/test_new.py':dict(lines=4,total_lines=4) for tree in ('candidate','previous')}
        return state,red,task,route,config,reads,receipt,'request'

    def test_fresh_diagnosis_only_preserves_failed_evidence_and_review(self):
        args=self.fixture();before=copy.deepcopy(args[0]);result=prepare(*args)
        self.assertEqual(args[0],before)
        self.assertEqual(result['review_task'],'review-task')
        self.assertEqual(result['status'],'blocked')
        recovery=result['rejection_diagnosis']['schema_recovery']
        self.assertEqual(recovery['prior_diagnosis'],before['rejection_diagnosis'])
        self.assertEqual(recovery['attempt_limit'],1)
        self.assertFalse(recovery['author_restarted']);self.assertFalse(recovery['delivery_approval'])
        self.assertEqual(result['rejection_diagnosis']['status'],'dispatch_intent')
        self.assertEqual(prepare(result,*args[1:]),result)

    def test_drift_missing_reads_nonterminal_or_approval_fails_closed(self):
        for mutation in ('manifest','actor','running','issue','wakeup','read','shape','approval','category','execution'):
            args=list(copy.deepcopy(self.fixture()))
            if mutation=='manifest':args[0]['manifest_sha256']='c'*64
            if mutation=='actor':args[2]['agent_id']='author'
            if mutation=='running':args[2]['status']='running'
            if mutation=='issue':args[2]['issue_id']='other'
            if mutation=='wakeup':args[2]['wakeup_id']='other'
            if mutation=='read':args[5]['/evidence/previous/tests/test_new.py']['lines']=2
            if mutation=='shape':args[6]['response_shape']['arguments_json_valid']=False
            if mutation=='approval':args[6]['delivery_approval']=True
            if mutation=='category':args[6]['category']='typed_wrong_tool_name'
            if mutation=='execution':args[7]=''
            with self.assertRaises(ValueError,msg=mutation):prepare(*args)

    def test_consumed_recovery_never_rearms_a_second_failure(self):
        args=list(self.fixture());result=prepare(*args)
        result['rejection_diagnosis']['status']='blocked'
        self.assertEqual(prepare(result,*args[1:]),result)
        args[2]['id']='new-failed-task'
        with self.assertRaises(ValueError):prepare(result,*args[1:])

    def test_malformed_single_submission_can_only_sponsor_fresh_diagnosis(self):
        args=list(copy.deepcopy(self.fixture()))
        args[6]['category']='typed_arguments_invalid'
        args[6]['response_shape'].update(arguments_json_valid=False,arguments_schema_valid=None)
        result=prepare(*args)
        self.assertEqual(result['status'],'blocked')
        proof=result['rejection_diagnosis']['schema_recovery']
        self.assertEqual(proof['rejection_receipt'],args[6])
        self.assertFalse(proof['delivery_approval'])
        for field,value in (('expected_tool',False),('terminal',False),('submissions',2),
                            ('arguments_schema_valid',True),('arguments_rejection','argument_size')):
            changed=copy.deepcopy(args);changed[6]['response_shape'][field]=value
            with self.assertRaises(ValueError,msg=field):prepare(*changed)

    def test_operator_admission_atomically_updates_trial_and_handoff(self):
        from broker import handoffs,test_revision_review,native,handoff_runtime,controller_maintenance
        from broker.test_diagnosis_recovery import resume
        state,red,task,route,config,reads,receipt,execution=self.fixture()
        route['minimum_calls']=4
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'native.json').write_text('{}')
            @contextmanager
            def db():
                con=sqlite3.connect(root/'state.sqlite');con.row_factory=sqlite3.Row
                try:
                    with con:yield con
                finally:con.close()
            with db() as con:
                handoffs.initialize(con);test_revision_review.initialize(con)
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT)')
                con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',(execution,task['id'],'cto','child'))
                con.execute('INSERT INTO delivery_routes VALUES (?,?)',('child',json.dumps(route)))
                con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',('child','parent',json.dumps(config),json.dumps(state)))
                con.execute('CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)')
                con.execute('INSERT INTO test_first_red VALUES (?,?)',('child',json.dumps(red)))
                con.execute('CREATE TABLE leases(status TEXT)')
            b=SimpleNamespace(LOCK=threading.RLock(),db=db,STATE=root,PREFIX='delivery-kit-test',
                docker=lambda *_:dict(Image='sha256:'+'c'*64,Config={'Labels':{
                    'com.docker.compose.project':'delivery-kit-test','com.docker.compose.service':'model-proxy'}}))
            reviewer=dict(id='review-task',issue_id='child',status='completed')
            fx=SimpleNamespace(read_evidence=lambda _:reads,remaining_calls=lambda:100)
            payload=dict(issue_id='child',failed_task=task['id'],execution_id=execution,
                receipt=receipt,proxy_image='sha256:'+'c'*64,operation_id='maintenance')
            with patch.object(controller_maintenance,'current',return_value={'stage':'sealed','operation_id':'maintenance'}), \
                    patch.object(controller_maintenance,'native_active',return_value=[]), \
                    patch.object(native,'task_record',side_effect=lambda _,identity,*a:task if identity==task['id'] else reviewer), \
                    patch.object(handoff_runtime,'Effects',return_value=fx):
                result=resume(b,payload)
                again=resume(b,payload)
            self.assertEqual(result,again)
            with db() as con:
                saved=json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
                handoff=handoffs.load(con,'author-task')
                self.assertEqual(con.execute('SELECT count(*) FROM delivery_handoffs').fetchone()[0],1)
            self.assertEqual(handoff['stage'],'test_review_cto_diagnosis')
            self.assertEqual(saved['rejection_diagnosis']['status'],'dispatch_intent')
            self.assertEqual(json.loads(handoff['data'])['rejection_diagnosis'],saved['rejection_diagnosis'])
            self.assertFalse(result['delivery_approval'])

    def test_recovery_policy_fits_native_bound_without_truncating_finding(self):
        from broker.test_revision_review import schema_recovery_instruction
        reason='x'*1200
        state={'reason':reason,'comparison':{'files':{}}}
        paths=['/evidence/'+tree+'/tests/test_feedback_latest_ui.py' for tree in ('candidate','previous')]
        note=schema_recovery_instruction(state,paths)
        self.assertLessEqual(len('DELIVERY_HANDOFF '+'a'*64+'\n'+note),4000)
        self.assertIn(reason,note)
        for path in paths:self.assertIn(path,note)
        self.assertIn('DELIVERY_TYPED_TEST_DIAGNOSIS_V1',note)
