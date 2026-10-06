import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from broker.remediation_preparation import payload,validate_job,validate_proof
from broker.remediation_workspace_probe import prepare
import test_revision_seed as fixtures


class RemediationPreparationTests(unittest.TestCase):
    def setUp(self):
        self.value=dict(run_id='run',contract_sha256='c'*64,base=dict(volume='base',base_sha='a'*40,manifest_sha256='b'*64),
            previous_new_test_delivery=dict(volume='previous',task_id='test-author',manifest_sha256='d'*64,
                                           test_sha256={'tests/test_new.py':'e'*64}))
        self.b=SimpleNamespace(IMAGE='sha256:'+'f'*64,OWNER='owner',PREFIX='delivery-kit-port2',
                               docker=lambda *args:dict(Config=dict(Env=['PATH=/usr/bin'])))

    def job(self):
        expected=payload(self.b,self.value,'issue','target')
        info=dict(Image=expected['Image'],Config={k:expected[k] for k in ('User','Entrypoint','Cmd','Env','Labels')},
                  HostConfig=copy.deepcopy(expected['HostConfig']))
        info['Config']['Env']=['PATH=/usr/bin']+expected['Env']
        info['Config']['Labels']={**expected['Labels'],'com.docker.compose.project':'delivery-kit-port2-tests'}
        info['Mounts']=[dict(Type='volume',Name=m['Source'],Destination=m['Target'],RW=not m['ReadOnly']) for m in expected['HostConfig']['Mounts']]
        return expected,info

    def test_job_is_fixed_grouped_credential_free_without_source_write_or_socket(self):
        expected,info=self.job();validate_job(self.b,info,expected)
        for mutate in (lambda i:i['HostConfig'].update(NetworkMode='host'),
                       lambda i:i['Config']['Env'].append('GH_TOKEN=synthetic'),
                       lambda i:i['Mounts'][0].update(RW=True),
                       lambda i:i['Mounts'].append(dict(Type='bind',Destination='/var/run/docker.sock')),
                       lambda i:i['Config'].update(Cmd=['arbitrary-command'])):
            bad=copy.deepcopy(info);mutate(bad)
            with self.assertRaises(ValueError):validate_job(self.b,bad,expected)

    def test_fixed_probe_copies_only_original_base_and_preserved_new_tests(self):
        f=fixtures.RevisionSeedTests();f.setUp()
        try:
            target=f.base.parent/'target';target.mkdir()
            proof=prepare(f.base,target,f.previous,f.work,f.env['BASE_MANIFEST_SHA256'],f.selection)
            self.assertTrue(proof['baseline_unchanged']);self.assertTrue(proof['product_unchanged'])
            self.assertFalse(proof['red_executed']);self.assertFalse(proof['execution_authorized'])
            self.assertEqual((f.work/'app.py').read_bytes(),b'original product')
            self.assertEqual((f.work/f.name).read_bytes(),f.data)
            value={**self.value,'contract_sha256':proof['contract_sha256'],
                'base':{**self.value['base'],'manifest_sha256':proof['manifest_sha256']},
                'previous_new_test_delivery':{**self.value['previous_new_test_delivery'],
                    'manifest_sha256':proof['previous_manifest_sha256'],'test_sha256':proof['seed_test_sha256']}}
            validate_proof(value,proof)
            for change in (dict(red_executed=True),dict(execution_authorized=True),dict(product_unchanged=False),
                           dict(previous_manifest_sha256='0'*64)):
                with self.assertRaises(ValueError):validate_proof(value,{**proof,**change})
        finally:f.doCleanups()

    def test_tampered_historical_seed_cannot_qualify(self):
        f=fixtures.RevisionSeedTests();f.setUp()
        try:
            target=f.base.parent/'target';target.mkdir()
            (f.previous/f.name).write_bytes(b'changed')
            with self.assertRaises(ValueError):prepare(f.base,target,f.previous,f.work,f.env['BASE_MANIFEST_SHA256'],f.selection)
        finally:f.doCleanups()

    def test_lost_create_ack_does_not_create_another_job(self):
        import sqlite3
        import threading
        from contextlib import contextmanager
        from unittest.mock import patch
        from broker import remediation_preparation as preparation
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('CREATE TABLE remediation_executions(source_task TEXT,contract TEXT,state TEXT)')
        con.execute('INSERT INTO remediation_executions VALUES(?,?,?)',('source',json.dumps(self.value),
            json.dumps(dict(stage='r1_provision_pending',issue_id='issue'))))
        @contextmanager
        def db():
            yield con
            con.commit()
        created=[]
        def docker(method,path,data=None):
            if path=='/volumes/base':return dict(Labels={'delivery-kit.owner':'owner'})
            if path=='/volumes/previous':return dict(Labels={'delivery-kit.owner':'owner','delivery-kit.test-first-task':'test-author'})
            if path.startswith('/volumes/'):
                return dict(Labels={'delivery-kit.owner':'owner','delivery-kit.issue-id':'issue','delivery-kit.base-sha':'a'*40})
            if method=='GET' and path.startswith('/containers/'):return None
            if method=='POST' and path.startswith('/containers/create'):
                created.append(path);raise TimeoutError()
            raise AssertionError('unexpected Docker operation')
        b=SimpleNamespace(LOCK=threading.RLock(),db=db,docker=docker,OWNER='owner',PREFIX='delivery-kit-port2',IMAGE='sha256:'+'f'*64)
        with patch.object(preparation.execution,'register'):
            with self.assertRaises(TimeoutError):preparation.prepare(b,'source')
            with self.assertRaisesRegex(ValueError,'handle absent'):preparation.prepare(b,'source')
        self.assertEqual(len(created),1)
        self.assertEqual(json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])['stage'],'r1_base_job_intent')

    def test_observation_timeout_keeps_same_job_and_semantic_failure_is_visible(self):
        import sqlite3
        from contextlib import contextmanager
        from unittest.mock import patch
        from broker import remediation_preparation as preparation
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        preparation.execution.initialize(con)
        state=dict(stage='r1_base_job_running',preparation={'name':'fixed-owned-job'})
        con.execute('INSERT INTO remediation_executions VALUES(?,?,?)',('source','{}',json.dumps(state)))
        @contextmanager
        def db():
            yield con
            con.commit()
        b=SimpleNamespace(db=db)
        timeout=type('DockerOperationTimeout',(RuntimeError,),{})()
        with patch.object(preparation,'prepare',side_effect=timeout) as observe:
            preparation.tick(b);observe.assert_called_once_with(b,'source')
        self.assertEqual(json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0]),state)
        with patch.object(preparation,'prepare',side_effect=ValueError()):preparation.tick(b)
        result=json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])
        self.assertEqual(result['stage'],'r1_preparation_blocked')
        self.assertEqual(result['preparation']['name'],'fixed-owned-job')
