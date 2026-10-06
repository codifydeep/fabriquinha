import json
import hashlib
from pathlib import Path
import tempfile
import unittest
import threading
from unittest.mock import patch, MagicMock
from broker import host_restart_recovery as recovery, handoffs, test_first_handoffs
from broker.host_restart_snapshot import preserve
from broker.host_restart_recovery import qualified, register
from test_test_first_handoffs import Broker
from test_test_first_handoffs import Effects


class RestartPreservationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.base=self.root/'base';self.work=self.root/'work';self.snap=self.root/'snapshot'
        for p in (self.base,self.work,self.snap):p.mkdir()
        fixture=Path(__file__).parent/'fixtures'/'tdd'
        # Reuse a validated existing portable contract rather than invent a schema.
        contract=json.loads((Path(__file__).parents[1]/'projects'/'descartavel2-searchgen-1.contract.json').read_text())
        name=next(n for n in contract['files'] if n not in contract['editable_files'])
        self.name=name;self.contract=contract
        (self.work/name).parent.mkdir(parents=True,exist_ok=True)
        (self.work/name).write_bytes(b'original')
        (self.base/'contract.json').write_text(json.dumps(contract))
        (self.base/'manifest.json').write_text(json.dumps(dict(files={name:hashlib.sha256(b'original').hexdigest()})))

    def test_preserves_baseline_and_never_claims_red_or_delivery(self):
        proof=preserve(self.base,self.work,self.snap)
        self.assertTrue(proof['baseline_unchanged'])
        self.assertFalse(proof['red_verified']);self.assertFalse(proof['delivery_approval'])
        self.assertEqual(preserve(self.base,self.work,self.snap),proof)
        self.assertEqual((self.snap/self.name).stat().st_mode & 0o777,0o400)

    def test_changed_baseline_is_rejected(self):
        (self.work/self.name).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'baseline changed'):preserve(self.base,self.work,self.snap)

    def test_symlink_and_undeclared_file_are_rejected(self):
        (self.work/'intruder').write_bytes(b'x')
        with self.assertRaises(ValueError):preserve(self.base,self.work,self.snap)
        (self.work/'intruder').unlink();(self.work/self.name).unlink()
        (self.work/self.name).symlink_to(self.base/'manifest.json')
        with self.assertRaises(ValueError):preserve(self.base,self.work,self.snap)

    def test_resume_cannot_replace_preserved_bytes(self):
        preserve(self.base,self.work,self.snap)
        (self.snap/self.name).chmod(0o600);(self.snap/self.name).write_bytes(b'other')
        with self.assertRaisesRegex(ValueError,'snapshot drift'):preserve(self.base,self.work,self.snap)

    def test_qualification_requires_durable_exact_receipt(self):
        b=Broker(self.root/'state.sqlite');request=dict(issue_id='issue',source_task='source',interrupted_task='prior')
        receipt=dict(request=request,delivery_approval=False)
        with b.db() as c:
            self.assertFalse(qualified(c,'issue','source',{'host_restart_recovery':receipt}))
            c.execute('CREATE TABLE host_restart_recoveries(issue_id TEXT PRIMARY KEY,receipt TEXT)')
            c.execute('INSERT INTO host_restart_recoveries VALUES (?,?)',('issue',json.dumps(receipt)))
            self.assertTrue(qualified(c,'issue','source',{'host_restart_recovery':receipt}))
            self.assertFalse(qualified(c,'issue','other',{'host_restart_recovery':receipt}))
            receipt['delivery_approval']=True
            self.assertFalse(qualified(c,'issue','source',{'host_restart_recovery':receipt}))

    def test_registration_rejects_inexact_identity(self):
        with self.assertRaises(ValueError):register(None,{'issue_id':'not-a-uuid'})


class RestartRegistrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.b=Broker(Path(temp.name)/'state.sqlite');self.b.STATE=Path(temp.name)
        self.b.LOCK=threading.RLock();self.b.IMAGE='sha256:'+'a'*64
        (self.b.STATE/'native.json').write_text('{}')
        self.issue='11111111-1111-4111-8111-111111111111'
        self.source='22222222-2222-4222-8222-222222222222'
        self.interrupted='33333333-3333-4333-8333-333333333333'
        self.payload=dict(issue_id=self.issue,source_task=self.source,interrupted_task=self.interrupted)
        self.route=dict(issue_id=self.issue,author='author',cto='cto',enabled=True,
            test_first=True,test_first_files=['tests/test_new.py'],minimum_calls=8)
        self.data=dict(error='test_first_correction_failed_after_cto_diagnosis',phase='test_first')
        self.runs=[dict(id=self.interrupted,agent_id='author',status='failed',created_at='01',
            error='daemon restarted while task was in flight'),
            dict(id=self.source,agent_id='author',status='failed',created_at='02',
            error='hermes initialize failed: hermes process exited')]
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE test_first_red(issue_id TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT)')
            c.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
            c.execute('CREATE TABLE tool_events(request_id TEXT,tool_count INTEGER)')
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('execution',self.interrupted,'author','scope'))
            c.execute('INSERT INTO leases VALUES (?,?)',('execution','interrupted'))
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',(self.issue,json.dumps(self.route)))
            handoffs.save(c,self.source,self.issue,'test_first_blocked','cto',self.data,1)

    def run_registration(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"remaining":32}'
        with patch.object(recovery.native,'issue_task_runs',return_value=self.runs), \
                patch.object(recovery.urllib.request,'urlopen',return_value=response), \
                patch.object(recovery,'preserve',return_value=dict(baseline_unchanged=True,
                    red_verified=False,manifest_sha256='b'*64,volume='snapshot')) as snapshot:
            receipt=register(self.b,self.payload)
        return receipt,snapshot.call_count

    def test_once_preserves_old_blocker_and_dispatches_cto_not_author(self):
        receipt,count=self.run_registration();self.assertEqual(count,1)
        again,count=self.run_registration();self.assertEqual(count,0);self.assertEqual(receipt,again)
        self.assertEqual(receipt['previous_blocker'],self.data)
        self.assertFalse(receipt['author_retry_authorized'])
        with self.b.db() as c:
            handoffs.save(c,'older',self.issue,'test_first_blocked','cto',{'test_first_cto_wakeup':'old'},0)
            row=handoffs.load(c,self.source)
            self.assertIsNone(c.execute('SELECT 1 FROM test_first_red').fetchone())
        fx=Effects(self.b)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[-1],row,fx)
        self.assertEqual(len(fx.wakeups),1);self.assertEqual(fx.wakeups[0][0][1],'cto')
        self.assertIn('HOST RESTART DIAGNOSIS',fx.wakeups[0][0][4])
        with self.b.db() as c:row=handoffs.load(c,self.source)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[-1],row,fx)
        self.assertEqual(len(fx.wakeups),1)

    def test_active_worker_red_or_accepted_tools_cannot_recover(self):
        for sql,args in [('INSERT INTO leases VALUES (?,?)',('other','running')),
                         ('INSERT INTO test_first_red VALUES (?)',(self.issue,)),
                         ('INSERT INTO tool_events VALUES (?,?)',('execution',1))]:
            with self.b.db() as c:c.execute(sql,args)
            with self.assertRaises(ValueError):self.run_registration()
            with self.b.db() as c:
                c.execute("DELETE FROM leases WHERE request_id='other'")
                c.execute('DELETE FROM test_first_red');c.execute('DELETE FROM tool_events')

    def test_wrong_failure_sequence_or_newer_author_cannot_recover(self):
        self.runs[0]['error']='ordinary test failure'
        with self.assertRaises(ValueError):self.run_registration()
        self.runs[0]['error']='daemon restarted while task was in flight'
        self.runs.append(dict(id='later',agent_id='author',status='failed',created_at='03'))
        with self.assertRaises(ValueError):self.run_registration()

    def test_existing_binding_and_changed_recovery_identity_are_rejected(self):
        with self.b.db() as c:c.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('other',self.source,'author','scope'))
        with self.assertRaises(ValueError):self.run_registration()
        with self.b.db() as c:c.execute("DELETE FROM native_bindings WHERE request_id='other'")
        self.run_registration();self.payload['interrupted_task']='44444444-4444-4444-8444-444444444444'
        with self.assertRaises(ValueError):self.run_registration()

    def test_diagnostic_uses_controller_modules_and_root_workdir_not_worker_image(self):
        self.b.PREFIX='delivery-kit-test';self.b.OWNER='owner'
        created=[]
        def docker(method,path,payload=None):
            if path.endswith('-execution-broker-1/json'):
                return {'Image':'sha256:'+'c'*64,'State':{'Running':True},
                        'Config':{'Labels':{'com.docker.compose.project':self.b.PREFIX}}}
            if path.startswith('/volumes/'):
                if '-work-' in path:return {'Labels':{'delivery-kit.owner':'owner','delivery-kit.scope':'scope'}}
                return None
            if path.startswith('/containers/create'):
                created.append(payload);return {}
            if path.endswith('/json'):
                return {'Id':'job','State':{'Running':False,'ExitCode':0},
                        'Config':{'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':self.interrupted}}}
            return {}
        self.b.docker=docker
        self.b.docker_stdout=lambda *_args,**_kw:'{"baseline_unchanged":true,"red_verified":false}'
        with patch.object(recovery.handoff_runtime,'task_base',return_value={'volume':'base'}):
            recovery.preserve(self.b,self.issue,self.interrupted,'scope')
        self.assertEqual(created[0]['Image'],'sha256:'+'c'*64)
        self.assertEqual(created[0]['WorkingDir'],'/')
        self.assertEqual(created[0]['HostConfig']['NetworkMode'],'none')
        self.assertNotIn('Env',created[0])
