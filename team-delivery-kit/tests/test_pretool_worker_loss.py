import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock


class PretoolWorkerLossTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.b = types.SimpleNamespace(STATE=Path(self.tmp.name), OWNER='delivery-kit-port2-broker-v1',
                                       PREFIX='delivery-kit-port2')
        spec = importlib.util.spec_from_file_location('fault_trial_under_test',
                         Path(__file__).resolve().parents[1] / 'inject_pretool_worker_loss.py')
        self.m = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, broker=self.b): spec.loader.exec_module(self.m)
        self.row = dict(name='delivery-kit-port2-job-request',request_id='request')
        self.info = dict(State=dict(Running=True),Config=dict(Labels={
            'delivery-kit.owner':self.b.OWNER,'delivery-kit.request':'request',
            'com.docker.compose.project':'delivery-kit-port2-tests'}))

    def test_ownership_requires_exact_test_group_request_and_running(self):
        self.assertTrue(self.m.owned(self.row,self.info))
        self.info['Config']['Labels']['com.docker.compose.project']='toso-project'
        self.assertFalse(self.m.owned(self.row,self.info))

    def test_receipt_cannot_be_overwritten(self):
        p=Path(self.tmp.name)/'receipt.json';self.m.write_once(p,dict(stage='intent'))
        with self.assertRaises(FileExistsError):self.m.write_once(p,dict(stage='done'))
        self.assertEqual(json.loads(p.read_text())['stage'],'intent')

    def test_receipt_rejects_symlink(self):
        p=Path(self.tmp.name)/'link';p.symlink_to(Path(self.tmp.name)/'missing')
        with self.assertRaises(ValueError):self.m.write_once(p,{})

    def test_invalid_identity_never_arms_or_touches_docker(self):
        with self.assertRaises(ValueError):self.m.inject('invalid')
        self.assertFalse((self.b.STATE/'fault-injection').exists())

    def test_pretool_checks_current_request_not_old_scope_sessions(self):
        connection=Mock();connection.execute.side_effect=[Mock(fetchone=Mock(return_value=[0])),
                                                        Mock(fetchone=Mock(return_value=None))]
        context=Mock();context.__enter__=Mock(return_value=connection);context.__exit__=Mock(return_value=False)
        self.b.db=Mock(return_value=context)
        self.assertTrue(self.m.pretool(self.row))
        query,args=connection.execute.call_args.args
        self.assertIn('acp_events',query);self.assertEqual(args,('request',))
        self.assertNotIn('scope',query)

    def test_paused_pretool_exact_kill_records_only_observed_exit(self):
        issue='11111111-1111-4111-8111-111111111111'
        row=dict(self.row,task_id='22222222-2222-4222-8222-222222222222')
        running=dict(self.info,Id='exact')
        paused=dict(running,State=dict(Running=True,Paused=True))
        stopped=dict(running,State=dict(Running=False,ExitCode=137))
        self.b.docker=Mock(side_effect=[running,{},paused,paused,{},stopped])
        with patch.object(self.m,'candidate',return_value=row),patch.object(self.m,'pretool',return_value=True):
            self.m.inject(issue,1)
        receipt=json.loads((self.b.STATE/'fault-injection'/(row['task_id']+'.json')).read_text())
        self.assertEqual(receipt['exit_code'],137)
        self.assertTrue(receipt['acp_operation_absent_for_request'])
        kills=[call for call in self.b.docker.call_args_list if '/kill?' in call.args[1]]
        self.assertEqual(len(kills),1);self.assertEqual(kills[0].args[1],'/containers/exact/kill?signal=SIGKILL')

    def test_uncertain_kill_never_repeats_or_fabricates_receipt(self):
        issue='11111111-1111-4111-8111-111111111111'
        row=dict(self.row,task_id='22222222-2222-4222-8222-222222222222')
        running=dict(self.info,Id='exact');paused=dict(running,State=dict(Running=True,Paused=True))
        self.b.docker=Mock(side_effect=[running,{},paused,paused,TimeoutError('unknown')])
        with patch.object(self.m,'candidate',return_value=row),patch.object(self.m,'pretool',return_value=True):
            with self.assertRaises(TimeoutError):self.m.inject(issue,1)
        self.assertTrue((self.b.STATE/'fault-injection'/(row['task_id']+'.intent.json')).exists())
        self.assertFalse((self.b.STATE/'fault-injection'/(row['task_id']+'.json')).exists())
        self.assertEqual(len([call for call in self.b.docker.call_args_list if '/kill?' in call.args[1]]),1)


if __name__=='__main__':unittest.main()
