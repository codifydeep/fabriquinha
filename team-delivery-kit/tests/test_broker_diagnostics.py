import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock


with patch.dict(os.environ, {'BROKER_WORKER_IMAGE': 'sha256:' + 'a' * 64}):
    spec = importlib.util.spec_from_file_location('broker_server_diagnostics', Path(__file__).parents[1] / 'broker/server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)


class BrokerDiagnosticTests(unittest.TestCase):
    def test_retirement_archives_sanitized_policy_before_delete(self):
        from broker import worker_creation_intent as intents
        from tests.test_worker_creation_intent import WorkerCreationIntentTests
        payload,_,info=WorkerCreationIntentTests().inputs()
        payload['Labels']={'delivery-kit.owner':server.OWNER,'delivery-kit.request':'request'}
        info['Config']['Labels']=payload['Labels'];info['Id']='c'*64
        info['Config'].pop('NetworkDisabled')
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)),\
                patch.dict(sys.modules,{'worker_creation_intent':intents}):
            with server.db() as con:intents.record(con,'request',payload)
            def docker(method,path,body=None):
                if method=='DELETE':
                    with server.db() as con:
                        receipt=json.loads(con.execute('SELECT receipt FROM worker_policy_observations').fetchone()[0])
                        self.assertEqual(receipt['container_id'],'c'*64)
                        self.assertEqual(receipt['normalized_differences'],[])
                        self.assertTrue(receipt['omitted_false_network_flag'])
                    return {}
            with patch.object(server,'docker') as call:
                # The second GET is the same name after the DELETE.
                deleted=[False]
                def sequence(method,path,*args):
                    if method=='DELETE':deleted[0]=True;return docker(method,path,*args)
                    return None if deleted[0] else info
                call.side_effect=sequence
                server.remove_owned('owned','request')
                self.assertEqual(sum(c.args[0]=='DELETE' for c in call.call_args_list),1)
            with server.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM worker_policy_observations').fetchone()[0],1)

    def test_pending_retirement_does_not_starve_other_closing_leases(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            with server.db() as con:
                con.execute('CREATE TABLE leases(request_id TEXT,name TEXT,status TEXT,deadline REAL)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT)')
                con.executemany('INSERT INTO leases VALUES (?,?,?,?)',[('first','one','closing',9999999999),('second','two','closing',9999999999)])
            with patch.object(server,'remove_owned',side_effect=[server.DockerOperationTimeout('DELETE','/containers/one'),None]) as remove:
                server.tick();self.assertEqual(remove.call_count,2)
            with server.db() as con:
                self.assertEqual([tuple(r) for r in con.execute('SELECT request_id,status FROM leases')],[('first','closing'),('second','closed')])

    def test_unknown_delete_is_never_reposted_even_if_docker_still_reports_running(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            info={'Id':'owned-id','Config':{'Labels':{'delivery-kit.owner':server.OWNER,'delivery-kit.request':'request'}},'State':{'Status':'running'}}
            error=server.DockerOperationTimeout('DELETE','/containers/owned-id')
            with patch.object(server,'docker',side_effect=[info,error,info,None]) as docker:
                with self.assertRaises(server.DockerOperationTimeout):server.remove_owned('owned','request')
                with self.assertRaises(server.DockerOperationTimeout):server.remove_owned('owned','request')
                server.remove_owned('owned','request')
                self.assertEqual(len([c for c in docker.call_args_list if c.args[0]=='DELETE']),1)
            with server.db() as con:self.assertEqual(con.execute('SELECT state FROM worker_retirement_intents').fetchone()[0],'gone')

    def test_acknowledged_delete_waits_for_actual_absence(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            info={'Id':'owned-id','Config':{'Labels':{'delivery-kit.owner':server.OWNER,'delivery-kit.request':'request'}},'State':{'Status':'removing'}}
            initial={**info,'State':{'Status':'running'}}
            with patch.object(server,'docker',side_effect=[initial,{},info,None]) as docker:
                with self.assertRaises(server.DockerOperationTimeout):server.remove_owned('owned','request')
                server.remove_owned('owned','request')
                self.assertEqual(len([c for c in docker.call_args_list if c.args[0]=='DELETE']),1)

    def test_transport_primary_failure_is_not_replaced_by_cleanup_timeout(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            with server.db() as con:
                con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
                con.execute("INSERT INTO leases VALUES ('request','running')")
                con.execute('CREATE TABLE native_bindings(request_id TEXT,scope TEXT,issue_id TEXT,task_id TEXT)')
                con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
            transport=Mock(side_effect=RuntimeError('Docker did not upgrade stream'))
            with patch.dict(sys.modules,{'acp_transport':SimpleNamespace(Transport=transport)}),patch.object(server,'remove_owned',side_effect=TimeoutError('cleanup')):
                with self.assertRaisesRegex(RuntimeError,'Docker did not upgrade stream'):
                    server.open_granted_transport({'request_id':'request','mode':'planning'},{'name':'owned'},None)
            with server.db() as con:
                self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0],'closing')
                self.assertEqual([tuple(r) for r in con.execute('SELECT operation,category FROM broker_errors')],
                    [('transport_start','bootstrap:worker_attach'),('transport_cleanup','prompt_timeout')])

    def test_worker_start_timeout_preserves_single_start_without_delete(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            with server.db() as con:
                con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY,scenario TEXT,name TEXT,status TEXT,deadline REAL)')
                con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
            error=server.DockerOperationTimeout('POST','/containers/owned/start')
            with patch.object(server,'config',return_value={'Image':'fixture'}),patch.object(server,'docker',side_effect=[{'Id':'owned'},error]) as docker,patch.object(server,'remove_owned') as remove:
                with self.assertRaises(server.DockerOperationTimeout):server.submit({'request_id':'request','scenario':'acp-session'},trusted_acp=True)
                self.assertEqual(docker.call_count,2);remove.assert_not_called()
                self.assertEqual(server.submit({'request_id':'request','scenario':'acp-session'},trusted_acp=True)['status'],'creating')
                self.assertEqual(docker.call_count,2)
            with server.db() as con:
                self.assertEqual(json.loads(con.execute('SELECT state FROM worker_creation_intents').fetchone()[0])['stage'],'start_outcome_unknown')
                self.assertEqual(con.execute('SELECT category FROM broker_errors').fetchone()[0],'bootstrap:docker_containers_start')

    def test_worker_create_timeout_is_observed_without_delete_or_duplicate_post(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            with server.db() as con:
                con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY,scenario TEXT,name TEXT,status TEXT,deadline REAL)')
                con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
            error=server.DockerOperationTimeout('POST','/containers/create?name=owned')
            with patch.object(server,'config',return_value={'Image':'fixture'}),patch.object(server,'docker',side_effect=error) as docker,patch.object(server,'remove_owned') as remove:
                with self.assertRaises(server.DockerOperationTimeout):server.submit({'request_id':'request','scenario':'acp-session'},trusted_acp=True)
                self.assertEqual(docker.call_count,1);remove.assert_not_called()
                self.assertEqual(server.submit({'request_id':'request','scenario':'acp-session'},trusted_acp=True)['status'],'creating')
                self.assertEqual(docker.call_count,1)
            with server.db() as con:
                self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0],'creating')
                self.assertEqual(json.loads(con.execute('SELECT state FROM worker_creation_intents').fetchone()[0])['stage'],'create_outcome_unknown')
                payload=json.loads(con.execute('SELECT payload FROM worker_creation_intents').fetchone()[0])
                self.assertEqual(payload['Labels']['com.docker.compose.project'],server.PREFIX+'-tests')
                self.assertEqual(payload['Labels']['com.docker.compose.oneoff'],'True')
    def test_only_container_create_gets_bounded_longer_deadline(self):
        conn=Mock();conn.getresponse.return_value.status=204;conn.getresponse.return_value.read.return_value=b''
        for method,path,deadline in [('POST','/containers/create?name=public',30),('GET','/containers/public/json',10),('DELETE','/containers/public',10)]:
            with patch.object(server,'DockerConnection',return_value=conn) as factory:
                server.docker(method,path,{'Image':'public-fixture'} if method=='POST' else None)
                factory.assert_called_once_with('localhost',timeout=deadline)
    def test_bootstrap_primary_failure_survives_cleanup_timeout(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'STATE',Path(tmp)):
            with server.db() as con:
                con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY,scenario TEXT,name TEXT,status TEXT,deadline REAL)')
                con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
            primary=server.DockerOperationTimeout('POST','/volumes/create')
            with patch.object(server,'config',side_effect=primary),patch.object(server,'remove_owned',side_effect=TimeoutError('slow cleanup')):
                with self.assertRaises(server.DockerOperationTimeout):
                    server.submit({'request_id':'request','scenario':'acp-session'},trusted_acp=True)
            with server.db() as con:
                self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0],'closing')
                errors=[tuple(r) for r in con.execute('SELECT operation,category FROM broker_errors')]
            self.assertEqual(errors,[('worker_submit','bootstrap:docker_volumes_create'),('bootstrap_cleanup','prompt_timeout')])
    def test_docker_timeout_identifies_operation_without_private_path(self):
        for method,path,category in [('POST','/containers/create?name=secret','docker_containers_create'),
                ('DELETE','/containers/private-id?force=true','docker_containers_delete'),
                ('POST','/volumes/create','docker_volumes_create')]:
            with self.subTest(category=category):
                self.assertEqual(server.failure_category(server.DockerOperationTimeout(method,path)),category)
        conn=Mock();conn.getresponse.side_effect=TimeoutError('secret details')
        with patch.object(server,'DockerConnection',return_value=conn):
            with self.assertRaises(server.DockerOperationTimeout) as caught:server.docker('GET','/containers/private/json')
        self.assertEqual(server.failure_category(caught.exception),'docker_containers_inspect')
        self.assertNotIn('private',str(caught.exception));conn.close.assert_called_once()
    def test_timeout_has_safe_explicit_category(self):
        self.assertEqual(server.failure_category(TimeoutError('secret prompt contents')), 'prompt_timeout')

    def test_internal_exception_does_not_expose_message(self):
        self.assertEqual(server.failure_category(RuntimeError('secret token')), 'broker_runtime')
        self.assertEqual(server.failure_category(RuntimeError('ACP response size limit')),
                         'acp_response_size')

    def test_safe_categories_separate_infrastructure_failures(self):
        self.assertEqual(server.failure_category(sqlite3.OperationalError('secret SQL')), 'broker_sqlite')
        self.assertEqual(server.failure_category(subprocess.CalledProcessError(1, ['secret'])), 'worker_process')
        self.assertEqual(server.failure_category(OSError('secret path')), 'worker_io')

    def test_model_limit_completion_is_not_reviewable(self):
        self.assertTrue(server.model_output_limit({'result': {'output':
            'No visible answer was produced. The model hit its output-token limit.'}}))
        self.assertFalse(server.model_output_limit({'result': {'output': 'Tests passed.'}}))
        self.assertFalse(server.model_output_limit({'result': None}))
