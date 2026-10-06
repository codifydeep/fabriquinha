import copy,unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import u3_controls_execution as execution

class ControlsExecutionTests(unittest.TestCase):
    def test_native_completion_without_artifact_cannot_reach_snapshot(self):
        for messages in ([],[{'type':'text','content':'Done'}],
                [{'type':'tool_result','tool':'write_file','output':'write_file failed: additive_test_rejected'}],
                [{'type':'tool_result','tool':'write_file','output':'created'},
                 {'type':'text','content':'HTTP 400: {}'}]):
            with self.assertRaises(ValueError):execution.require_author_artifact_protocol(messages)
        execution.require_author_artifact_protocol([{'type':'tool_result','tool':'write_file',
            'output':'created'}]) # Not approval: snapshot hashes and real tests are still mandatory.

    def test_diagnosed_recovery_is_idempotent_and_does_not_admit_without_evidence(self):
        from threading import RLock
        b=SimpleNamespace(LOCK=RLock())
        c,s=self.fixture();s['diagnosed_protocol_recovery']={'attempt_limit':1}
        with patch.object(execution,'saved',return_value=(c,s)):
            self.assertIs(execution.resume_diagnosed_author(b,{},{}),s)
        del s['diagnosed_protocol_recovery'];s['stage']='blocked'
        with patch.object(execution,'saved',return_value=(c,s)):
            with self.assertRaises(ValueError):execution.resume_diagnosed_author(b,{}, {})

    def test_changed_contract_recovery_persists_new_worker_and_one_wakeup(self):
        import contextlib,json,sqlite3,tempfile
        from pathlib import Path
        from threading import RLock
        from unittest.mock import Mock
        c,s=self.fixture();c.update(worker_image='sha256:'+'a'*64)
        s.update(stage='blocked',protocol_diagnostic={'task_id':'failed'})
        diagnosis={'schema':'u3-hermes-wal-diagnosis-v1','task_id':'failed',
            'reason':'only existing unittest harness imports allowed','prohibited_import':'__future__',
            'module_assignment':True,'main_guard':True,'artifact_exists':False}
        proof=dict(schema='additive-registry-probe-v1',status='passed',uid=10000,network='none',model_calls=0,
            delivery_approval=False,worker_image='sha256:'+'b'*64)
        proof.update({k:True for k in ('readless_denied','existing_file_write_denied','direct_terminal_denied',
            'patch_denied','invalid_code_denied','new_test_created','overwrite_denied','source_unchanged','fixture_only')})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native.json').write_text('{}');db=sqlite3.connect(root/'state.db')
            db.execute('CREATE TABLE leases(status TEXT)');execution.initialize(db)
            db.execute('INSERT INTO u3_control_executions VALUES(?,?,?)',(execution.SOURCE,'{}','{}'));db.commit()
            @contextlib.contextmanager
            def con():
                with db:yield db
            b=SimpleNamespace(LOCK=RLock(),STATE=root,db=con)
            fx=Mock();fx.remaining_calls.return_value=55;fx.ensure_unit_start.return_value={'id':'new-wake'}
            task=dict(id='failed',status='completed',issue_id='issue',wakeup_id='wake',agent_id='author',handoff_note='old')
            messages=[dict(type='tool_result',tool='write_file',output='additive_test_rejected')]*2
            with patch.object(execution,'saved',return_value=(c,s)),patch.object(execution.intake,'verify'),\
                    patch.object(execution.native,'task_record',return_value=task),\
                    patch.object(execution.native,'task_messages',return_value=messages),\
                    patch.object(execution.handoff_runtime,'Effects',return_value=fx):
                self.assertEqual(execution.resume_diagnosed_author(b,proof,diagnosis)['stage'],'awaiting_author')
                execution.resume_diagnosed_author(b,proof,diagnosis)
            fx.ensure_unit_start.assert_called_once()
            stored=json.loads(db.execute('SELECT config FROM u3_control_executions').fetchone()[0])
            self.assertEqual(stored['worker_image'],proof['worker_image']);db.close()
    def test_fixed_full_suite_command_uses_qualified_existing_policy(self):
        from test_runner_policy import validate_workspace_command
        self.assertEqual(validate_workspace_command(execution.controls_test_command()),
            ['python3','-m','unittest','discover','-s','.','-q'])

    def fixture(self):
        c={'worker_image':'sha256:'+'a'*64,'author':'author','plan_config':{},
            'plan':{'decision':{'units':[{'criteria':['C01'],'objective':'Clear actual search'},
                {'criteria':['C02'],'objective':'Assert post-stale DOM'}]}}}
        s={'step':1,'stage':'awaiting_author','issue_id':'issue','wakeup_id':'wake',
            'policy':{'path':'/workspace/tests/test_u3_c01_controls.py','criterion':'C01'}}
        return c,s

    def test_capability_is_one_current_author_wakeup_and_new_file(self):
        c,s=self.fixture();note=execution.author_note(c,s)
        b=SimpleNamespace(db=lambda:DummyContext())
        task={'agent_id':'author','wakeup_id':'wake','handoff_note':note}
        with patch.object(execution,'saved',return_value=(c,s)),patch.object(execution.intake,'verify'):
            grant=execution.grant(b,'issue',task)
            self.assertEqual(grant['policy']['path'],'/workspace/tests/test_u3_c01_controls.py')
            self.assertIsNone(execution.grant(b,'other',task))
            self.assertIsNone(execution.grant(b,'issue',dict(task,agent_id='reviewer')))
            with self.assertRaises(ValueError):execution.grant(b,'issue',dict(task,wakeup_id='old'))
            with self.assertRaises(ValueError):execution.grant(b,'issue',dict(task,handoff_note='promise'))
        self.assertIn('Do not change ANY existing files',note)
        self.assertIn('DELIVERY_ADDITIVE_CONTROL_V1',note)
        self.assertIn('Do not use from __future__',note)
        self.assertIn('STALE OPEN (with a space)',note)
        self.assertNotIn('STALEOPEN',note)

    def test_second_unit_can_only_use_previous_approved_seed(self):
        c,s=self.fixture();c['seed']={'task_id':'initial'};s['history']=[]
        self.assertEqual(execution.current_seed(c,s),c['seed'])
        s['step']=2
        with self.assertRaises(IndexError):execution.current_seed(c,s)
        s['history']=[{'seed':{'task_id':'independently-approved'}}]
        self.assertEqual(execution.current_seed(c,s)['task_id'],'independently-approved')

    def test_no_registered_execution_has_no_native_or_workspace_side_effect(self):
        with patch.object(execution,'saved',return_value=None):
            self.assertIsNone(execution.worker_config(None,'request','issue'))
            self.assertEqual(execution.mounts(None,{}),[])

class DummyContext:
    def __enter__(self):return object()
    def __exit__(self,*args):return False
