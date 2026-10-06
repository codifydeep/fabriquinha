import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from broker import review_dependency_recovery as recovery
from test_test_first_handoffs import Broker


class ReviewDependencyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.b=Broker(root/'state.sqlite')
        self.b.STATE=root;self.b.LOCK=threading.RLock();self.b.IMAGE='old'
        (root/'native.json').write_text(json.dumps(dict(agents={'reviewer':'planning'})))
        self.task=dict(id='task',agent_id='reviewer',status='failed',wakeup_id='wake',
            error='restricted broker stream failed: broker_internal',handoff_note='private')
        self.state=dict(status='blocked',manifest_sha256='a'*64,wakeup_id='wake',
                        review_failure=dict(task_id='task'))
        self.payload=dict(issue_id='issue',failed_task='task',manifest_sha256='a'*64)
        def missing(*args):raise ModuleNotFoundError(name='execution_context')
        self.b.native_task_prompt=missing
        with self.b.db() as con:
            con.execute('CREATE TABLE native_bindings(task_id TEXT,issue_id TEXT,agent_id TEXT,request_id TEXT)')
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('task','issue','reviewer','request'))
            con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT,state TEXT)')
            con.execute('INSERT INTO test_revision_trials VALUES (?,?,?)',('issue',json.dumps(dict(reviewer='reviewer')),json.dumps(self.state)))
            con.execute('CREATE TABLE tool_events(request_id TEXT,tool_count INT)')
            con.execute('CREATE TABLE acp_events(request_id TEXT,method TEXT)')

    def record(self):
        with patch('broker.native.task_record',return_value=self.task),patch(
                'broker.native.issue_record',return_value=dict(id='issue')):
            return recovery.record(self.b,'task')

    def test_failure_reproduced_once_without_native_restart_or_approval(self):
        receipt=self.record();self.assertEqual(self.record(),receipt)
        self.assertEqual(receipt['missing_module'],'execution_context')
        self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(receipt['model_calls'],0)
        self.assertNotIn('private',json.dumps(receipt))

    def test_model_or_tool_phase_is_not_dependency_bootstrap(self):
        with self.b.db() as con:con.execute('INSERT INTO tool_events VALUES (?,?)',('request',1))
        with self.assertRaisesRegex(ValueError,'pre-model'):self.record()
        with self.b.db() as con:
            con.execute('DELETE FROM tool_events')
            con.execute('INSERT INTO acp_events VALUES (?,?)',('request','session/prompt'))
        with self.assertRaisesRegex(ValueError,'pre-model'):self.record()

    def test_unchanged_image_or_wrong_snapshot_cannot_authorize_retry(self):
        self.record()
        with self.b.db() as con:
            with self.assertRaisesRegex(ValueError,'changed exact'):
                recovery.repaired(self.b,con,self.payload,self.task,self.state)
            self.b.IMAGE='new'
            with self.assertRaisesRegex(ValueError,'changed exact'):
                recovery.repaired(self.b,con,{**self.payload,'manifest_sha256':'b'*64},self.task,self.state)

    def test_repair_requires_real_successful_prompt_probe(self):
        self.record();self.b.IMAGE='new'
        with self.b.db() as con,patch('broker.native.issue_record',return_value=dict(id='issue')):
            with patch.object(recovery,'probe',side_effect=ModuleNotFoundError):
                with self.assertRaises(ModuleNotFoundError):
                    recovery.repaired(self.b,con,self.payload,self.task,self.state)
            with patch.object(recovery,'probe',return_value='a'*64) as probe:
                receipt=recovery.repaired(self.b,con,self.payload,self.task,self.state)
                probe.assert_called_once()
                self.assertEqual(receipt['fixed_image'],'new')
                self.assertFalse(receipt['delivery_approval'])

    def test_unknown_missing_module_is_not_qualified(self):
        def missing(*args):raise ModuleNotFoundError(name='unrelated')
        self.b.native_task_prompt=missing
        with self.assertRaisesRegex(ValueError,'unqualified'):self.record()

    def test_fixed_prompt_cannot_be_recorded_as_an_old_failure(self):
        self.b.native_task_prompt=lambda *args: {}
        with self.assertRaisesRegex(ValueError,'not reproduced'):self.record()
