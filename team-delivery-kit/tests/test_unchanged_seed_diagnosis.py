from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from broker import unchanged_seed_diagnosis as d,remediation_runtime_guard as guard,native

SOURCE='11111111-1111-4111-8111-111111111111'

def messages():
    return [dict(type='tool_use',tool='read_file',call_id='real-read'),
            dict(type='tool_result',tool='read_file',call_id='real-read',output_truncated=False)]

class FakeBroker:
    PREFIX='delivery-kit-fixture';OWNER='owned'
    def __init__(self,root):
        self.STATE=root;self.LOCK=threading.RLock();self.job=None;self.posts=[];self.fail=None
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.con.executescript('CREATE TABLE delivery_handoffs(source_task TEXT,issue_id TEXT,stage TEXT,data TEXT);'
            'CREATE TABLE test_first_red(issue_id TEXT);CREATE TABLE leases(request_id TEXT,status TEXT);'
            'CREATE TABLE native_bindings(task_id TEXT,issue_id TEXT,agent_id TEXT,request_id TEXT);'
            'CREATE TABLE failed_execution_snapshots(task_id TEXT,volume TEXT,status TEXT);'
            'CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);')
        self.con.execute('INSERT INTO delivery_handoffs VALUES (?,?,?,?)',(SOURCE,'issue','test_first_blocked',json.dumps(
            dict(error='test_first_cto_requires_replanning',decision=dict(action='escalate_cto'),cto_task='cto-task',test_first_cto_wakeup='cto-wake'))))
        self.con.execute('INSERT INTO leases VALUES (?,?)',('request','closed'))
        self.con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',(SOURCE,'issue','author','request'))
        self.con.execute('INSERT INTO failed_execution_snapshots VALUES (?,?,?)',(SOURCE,'snapshot','complete'))
        self.con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(dict(cto='cto'))))
    @contextmanager
    def db(self):
        with self.con:yield self.con
    def docker(self,method,path,payload=None):
        if path.startswith('/images/'):return dict(Id=d.IMAGE,Config=dict(Env=['PATH=/usr/bin']))
        if path.startswith('/volumes/'):return dict(Labels={'delivery-kit.owner':self.OWNER,'delivery-kit.source-task':SOURCE})
        if method=='POST':
            self.posts.append(path)
            if self.fail and self.fail in path:raise TimeoutError('uncertain outcome')
            if path.startswith('/containers/create'):
                self.job=dict(Id='fixed-job',Config=copy.deepcopy({k:v for k,v in payload.items() if k!='HostConfig'}),
                    HostConfig=payload['HostConfig'],State=dict(Status='created',Running=False,ExitCode=0))
            else:self.job['State'].update(Status='running',Running=True)
            return dict(Id='fixed-job')
        return self.job
    def docker_stdout(self,*args,**kwargs):
        return json.dumps(dict(status='passed',observation='snapshot_hashes_match',manifest_sha256='a'*64,file_count=63,total_bytes=506239))

class SeedDiagnosisTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        (root/'native.json').write_text('{}');self.b=FakeBroker(root);self.addCleanup(self.b.con.close)
        self.value=dict(amendment=dict(kind='request_scope'),steps=[dict(owner='author')],previous_new_test_delivery=dict(manifest_sha256='a'*64))
        self.tasks={SOURCE:dict(id=SOURCE,agent_id='author',issue_id='issue',status='failed',failure_reason='agent_error.provider_server_error'),
            'cto-task':dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed',wakeup_id='cto-wake')}
        for target,name,kwargs in ((guard,'qualified',dict(return_value=self.value)),
                (native,'task_record',dict(side_effect=lambda settings,task,agent:self.tasks[task])),
                (native,'issue_task_runs',dict(return_value=list(self.tasks.values()))),
                (native,'task_messages',dict(return_value=messages()))):
            p=patch.object(target,name,**kwargs);p.start();self.addCleanup(p.stop)
    def test_only_complete_paired_reads_can_support_inspection(self):
        self.assertEqual(d.read_only_messages(messages()),1)
        for bad in ([],messages()[:1],[dict(m,tool='patch') for m in messages()],
                    messages()+messages(),[messages()[0],dict(messages()[1],output_truncated=True)]):
            with self.assertRaises(ValueError):d.read_only_messages(bad)
    def test_whole_inventory_required_not_matching_test_hash_alone(self):
        proof=json.loads(self.b.docker_stdout())
        d.validate_result(proof,'a'*64)
        for changed in (dict(manifest_sha256='b'*64),dict(file_count=0),dict(file_count=True),dict(source='PRIVATE')):
            with self.assertRaises(ValueError):d.validate_result(dict(proof,**changed),'a'*64)
    def test_fixed_offline_payload_has_no_execution_or_write_authority(self):
        value=d.payload(self.b,SOURCE,'snapshot','a'*64)
        self.assertEqual(value['Image'],d.IMAGE);self.assertEqual(value['HostConfig']['NetworkMode'],'none')
        self.assertEqual(value['HostConfig']['Mounts'],[dict(Type='volume',Source='snapshot',Target='/delivery',ReadOnly=True)])
        self.assertNotIn('socket',json.dumps(value));self.assertEqual(value['Cmd'],['-c',d.SCRIPT])
    def test_actual_job_preserved_and_receipt_does_not_reconstruct_proxy_cause(self):
        self.assertIsNone(d.capture(self.b,'issue',SOURCE))
        self.b.job['State'].update(Status='exited',Running=False)
        proof=d.capture(self.b,'issue',SOURCE)
        self.assertEqual(proof['inventory']['file_count'],63);self.assertFalse(proof['proxy_failure_cause_proven'])
        self.assertFalse(proof['red_verified']);self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['write_executed'])
        self.assertEqual(d.capture(self.b,'issue',SOURCE),proof);self.assertEqual(len(self.b.posts),2)
    def test_uncertain_create_is_observed_without_second_post(self):
        self.b.fail='create'
        with self.assertRaises(TimeoutError):d.capture(self.b,'issue',SOURCE)
        self.assertIsNone(d.capture(self.b,'issue',SOURCE));self.assertEqual(len(self.b.posts),1)
    def test_uncertain_start_is_observed_without_restarting(self):
        self.b.fail='/start'
        with self.assertRaises(TimeoutError):d.capture(self.b,'issue',SOURCE)
        self.assertIsNone(d.capture(self.b,'issue',SOURCE));self.assertEqual(len(self.b.posts),2)
    def test_red_or_live_worker_prevents_a_diagnostic_job(self):
        self.b.con.execute('INSERT INTO test_first_red VALUES (?)',('issue',))
        self.assertIsNone(d.capture(self.b,'issue',SOURCE));self.assertFalse(self.b.posts)
        self.b.con.execute('DELETE FROM test_first_red');self.b.con.execute('UPDATE leases SET status=\'running\'')
        self.assertIsNone(d.capture(self.b,'issue',SOURCE));self.assertFalse(self.b.posts)
    def test_changed_candidate_is_retained_blocked_not_retried_or_approved(self):
        d.capture(self.b,'issue',SOURCE);self.b.job['State'].update(Status='exited',Running=False,ExitCode=1)
        self.assertIsNone(d.capture(self.b,'issue',SOURCE));self.assertIsNone(d.capture(self.b,'issue',SOURCE))
        self.assertEqual(len(self.b.posts),2)
