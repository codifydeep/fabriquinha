"""Host scheduler/journal tests, not native delivery evidence."""
import hashlib
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import quality_candidate_service as service
import test_quality_candidate_dispatch as fixtures


class CandidateServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.root.chmod(0o700)
        self.authority=fixtures.Authority()
        self.value=dict(namespace=self.authority.namespace,image=self.authority.image,
            private=str(self.root),repositories={'owner/repository':str(self.root)})
        self.path=self.root/'config.json';self.path.write_text(json.dumps(self.value));self.path.chmod(0o600)
        self.pin=hashlib.sha256(self.path.read_bytes()).hexdigest()
        mock=patch.object(service.dispatch,'Authority',return_value=self.authority)
        mock.start();self.addCleanup(mock.stop)

    def test_one_shot_restart_preserves_queue_and_never_enables_execution(self):
        self.authority.paused=True
        first=service.run_once(self.path,self.pin)
        second=service.run_once(self.path,self.pin)
        self.assertEqual(first['result']['stage'],'maintenance')
        self.assertEqual(second['result']['stage'],'maintenance')
        status=service.status(self.path,self.pin)
        self.assertEqual(status['queue']['tasks'],[])
        self.assertEqual(status['service'],second)
        self.assertEqual(second['model_calls'],0);self.assertFalse(second['delivery_approval'])

    def test_two_failures_latch_and_service_restart_does_not_clear_hold(self):
        with patch.object(service.dispatch,'tick',side_effect=RuntimeError('synthetic crash')) as tick:
            first=service.run_once(self.path,self.pin)
            second=service.run_once(self.path,self.pin)
            third=service.run_once(self.path,self.pin)
        self.assertEqual(first['unexpected_exits'],1)
        self.assertEqual(second['stage'],'crash_escalation')
        self.assertEqual(third,second);self.assertEqual(tick.call_count,2)
        self.assertEqual(third['owner'],'cto');self.assertFalse(third['automatic_retry'])

    def test_interrupted_intent_counts_without_replaying_or_forgetting_crash(self):
        with patch.object(service.dispatch,'tick',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):service.run_once(self.path,self.pin)
        with patch.object(service.dispatch,'tick',side_effect=RuntimeError('second failure')) as tick:
            state=service.run_once(self.path,self.pin)
            self.assertEqual(service.run_once(self.path,self.pin),state)
        self.assertEqual(state['stage'],'crash_escalation');self.assertEqual(tick.call_count,1)

    def test_busy_tick_preserves_crash_count_without_claiming_process_dead(self):
        with patch.object(service.dispatch,'tick',side_effect=RuntimeError):service.run_once(self.path,self.pin)
        with patch.object(service.dispatch,'tick',side_effect=service.Pending):result=service.run_once(self.path,self.pin)
        self.assertEqual(result['unexpected_exits'],1)
        self.assertEqual(result['result']['stage'],'busy_or_pending')

    def test_status_does_not_create_files_probe_docker_or_tick(self):
        before=set(self.root.iterdir())
        with patch.object(service.dispatch,'tick',side_effect=AssertionError('no execution')),\
                patch.object(self.authority,'about',side_effect=AssertionError('no Docker')):
            result=service.status(self.path,self.pin)
        self.assertIsNone(result['service']);self.assertEqual(result['queue']['stage'],'unobserved')
        self.assertEqual(set(self.root.iterdir()),before)

    def test_config_pin_and_service_state_corruption_cannot_reset_failures(self):
        self.authority.paused=True;service.run_once(self.path,self.pin)
        receipt=self.root/'quality-candidate-dispatch'/(service.token(self.authority.namespace)+'.json')
        value=json.loads(receipt.read_bytes());value['state']['unexpected_exits']=0
        value['state']['stage']='crash_escalation';receipt.write_text(json.dumps(value))
        with self.assertRaises(ValueError):service.run_once(self.path,self.pin)
        with self.assertRaises(ValueError):service.run_once(self.path,'0'*64)

    def test_registration_is_fixed_private_and_does_not_bootstrap(self):
        with patch('quality_delivery_candidate.repository') as repository:
            first=service.register(self.path,self.pin);second=service.register(self.path,self.pin)
        self.assertEqual(first,second);self.assertEqual(first['stage'],'registered_not_started')
        repository.assert_called_with(str(self.root),'owner/repository')
        plist=Path(first['plist']);self.assertEqual(plist.stat().st_mode&0o077,0)
        value=plistlib.loads(plist.read_bytes())
        self.assertEqual(value['StartInterval'],15);self.assertNotIn('KeepAlive',value)
        self.assertIn(self.pin,value['ProgramArguments']);self.assertNotIn('--watch',value['ProgramArguments'])
        self.assertNotIn('TOKEN',json.dumps(value));self.assertIsNone(service.status(self.path,self.pin)['service'])

    def test_registration_cannot_replace_existing_different_plist(self):
        with patch('quality_delivery_candidate.repository'):
            result=service.register(self.path,self.pin)
            Path(result['plist']).write_bytes(b'different registration')
            with self.assertRaises(ValueError):service.register(self.path,self.pin)

    def test_configuration_pin_is_checked_on_the_bytes_actually_parsed(self):
        self.assertEqual(service.dispatch.configuration(self.path,pin=self.pin),self.value)
        with self.assertRaises(ValueError):service.dispatch.configuration(self.path,pin='0'*64)

    def test_native_registration_uses_standard_private_log_path_not_documents(self):
        with patch('quality_delivery_candidate.repository'),patch.object(service.sys,'platform','darwin'),\
                patch.object(service.Path,'home',return_value=self.root):
            result=service.register(self.path,self.pin,native_paths=True)
        plist=plistlib.loads(Path(result['plist']).read_bytes())
        expected=self.root/'Library'/'Logs'/'DeliveryKit'/self.authority.namespace
        self.assertEqual(Path(plist['StandardOutPath']).parent,expected)
        self.assertEqual(expected.stat().st_mode&0o077,0)
        self.assertTrue(result['plist'].endswith('.native.plist'))

    def test_login_registration_is_scoped_private_and_never_overwrites_other_content(self):
        with patch('quality_delivery_candidate.repository'),patch.object(service.sys,'platform','darwin'),\
                patch.object(service.Path,'home',return_value=self.root):
            result=service.register(self.path,self.pin,native_paths=True,persist_login=True)
            login=Path(result['login_plist'])
            self.assertEqual(login.parent,self.root/'Library'/'LaunchAgents')
            self.assertEqual(login.read_bytes(),Path(result['plist']).read_bytes())
            self.assertEqual(login.stat().st_mode&0o077,0)
            login.write_bytes(b'other service contents')
            with self.assertRaises(ValueError):service.register(self.path,self.pin,native_paths=True,persist_login=True)


if __name__=='__main__':unittest.main()
