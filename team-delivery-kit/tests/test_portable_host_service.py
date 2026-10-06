import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import portable_host_service as service
import publication_access as access


class HostServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(label='HOST-1', issue_id='issue')
        self.status = dict(label='HOST-1', issue_id='issue', stage='accepted')
        self.run = Mock(return_value=0)
        self.ready = Mock(return_value=True)
        self.access = Mock()
        self.refresh = Mock(return_value=False)

    def tick(self, previous=None):
        return service.tick(self.config, previous or {}, self.status,
            self.run, self.ready, self.access, self.refresh)

    def test_completed_release_never_reexecutes_controller_or_probes(self):
        self.status['stage']='deployed_qa_passed'
        self.assertEqual(self.tick()['stage'],'completed_idle')
        for operation in (self.run,self.ready,self.access,self.refresh):operation.assert_not_called()

    def test_docker_outage_waits_without_agent_execution_or_diagnosis(self):
        self.ready.return_value=False
        self.status.update(stage='escalation_required',category='technical_failure')
        self.assertEqual(self.tick()['stage'],'waiting_infrastructure')
        self.run.assert_not_called();self.refresh.assert_not_called()
        self.ready.return_value=True
        self.assertEqual(self.tick()['stage'],'technical_blocked')
        self.run.assert_not_called()

    def test_authentication_restored_resumes_once_without_status_override(self):
        self.status['stage']='waiting_publication_access'
        original=self.status.copy()
        self.access.side_effect=access.WaitingPublicationAccess('github_auth_required')
        self.assertEqual(self.tick()['stage'],'waiting_publication_access')
        self.run.assert_not_called()
        self.access.side_effect=None
        self.assertTrue(self.tick()['controller_started'])
        self.run.assert_called_once();self.assertEqual(self.status,original)

    def test_only_verified_transport_transition_can_refresh_technical_stop(self):
        self.status['stage']='escalation_required'
        self.assertEqual(self.tick()['stage'],'technical_blocked')
        self.refresh.return_value=True
        self.assertTrue(self.tick()['controller_started'])
        self.run.assert_called_once()

    def test_two_crashes_are_persistent_and_do_not_spin(self):
        self.run.return_value=-9
        first=self.tick();self.assertEqual(first['unexpected_exits'],1)
        second=self.tick(first);self.assertEqual(second['stage'],'crash_escalation')
        self.assertEqual(self.tick(second),second)
        self.assertEqual(self.run.call_count,2)

    def test_other_issue_cannot_be_resumed(self):
        self.status['issue_id']='other'
        with self.assertRaisesRegex(ValueError,'identity drift'):self.tick()
        self.run.assert_not_called()

    def test_busy_controller_does_not_clear_crash_history(self):
        self.run.return_value=75
        self.assertEqual(self.tick(dict(unexpected_exits=1))['unexpected_exits'],1)

    def fixture(self, directory):
        root=Path(directory).resolve();private=root/'private';private.mkdir(mode=0o700)
        issue='01a10dcb-3312-722b-a0b6-58f4ec391154'
        paths={}
        for name,value in (('project',dict(repository='owner/repo')),
                           ('contract',dict(repository='owner/repo')),('run',dict(label='HOST-1'))):
            path=root/(name+'.json');path.write_text(json.dumps(value));paths[name]=str(path)
        (private/'portable-context-HOST-1.json').write_text(json.dumps(dict(issue_id=issue)))
        env=dict(DELIVERY_KIT_INSTANCE_HOME=str(private),DELIVERY_KIT_PROJECT_CONFIG=paths['project'],
            DELIVERY_KIT_DELIVERY_CONTRACT=paths['contract'],DELIVERY_KIT_RUN_SPEC=paths['run'],
            DELIVERY_KIT_COMPOSE_PROJECT='delivery-kit-port2',EVAL_BACKEND_PORT='19081',
            EVAL_FRONTEND_PORT='19310',DELIVERY_KIT_TEST_FIRST='1')
        config=dict(schema=1,label='HOST-1',issue_id=issue,environment=env,
            inputs={path:hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths.values()})
        path=root/'config.json';path.write_text(json.dumps(config));return path,config,paths

    def test_registration_pins_sources_and_rejects_credentials_or_issue_drift(self):
        for mutation in ('valid','pin','source','secret','issue','permissions','symlink'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as tmp:
                path,config,paths=self.fixture(tmp)
                if mutation=='source':Path(paths['run']).write_text('{}')
                if mutation=='secret':config['environment']['GH_TOKEN']='never-store';path.write_text(json.dumps(config))
                if mutation=='issue':
                    Path(config['environment']['DELIVERY_KIT_INSTANCE_HOME'],'portable-context-HOST-1.json').write_text(json.dumps(dict(issue_id='other')))
                if mutation=='permissions':Path(config['environment']['DELIVERY_KIT_INSTANCE_HOME']).chmod(0o755)
                if mutation=='symlink':
                    origin=path.with_name('original.json');path.rename(origin);path.symlink_to(origin)
                pin=hashlib.sha256(path.read_bytes()).hexdigest()
                if mutation=='pin':pin='0'*64
                if mutation=='valid':self.assertEqual(service.load_config(path,pin),config)
                else:
                    with self.assertRaises(ValueError):service.load_config(path,pin)


class PublicationAccessTests(unittest.TestCase):
    def test_auth_errors_wait_without_exposing_credentials(self):
        for message,reason in (('HTTP 401 token=secret','github_auth_required'),
                               ('connection refused secret','github_unavailable')):
            with patch.object(access.subprocess,'run',return_value=Mock(returncode=1,stderr=message)):
                with self.assertRaises(access.WaitingPublicationAccess) as error:access.require_access()
                self.assertEqual(str(error.exception),reason)
                self.assertNotIn('secret',str(error.exception))

    def test_probe_timeout_does_not_start_login_or_change_tokens(self):
        with patch.object(access.subprocess,'run',side_effect=subprocess.TimeoutExpired('gh',15)) as run:
            with self.assertRaisesRegex(access.WaitingPublicationAccess,'github_unavailable'):access.require_access()
            self.assertEqual(run.call_args.args[0],['gh','api','user','--jq','.login'])

    def test_valid_github_access_does_not_store_identity(self):
        with patch.object(access.subprocess,'run',return_value=Mock(returncode=0,stdout='owner\n')):
            self.assertIsNone(access.require_access())
