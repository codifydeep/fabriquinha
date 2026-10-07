import unittest,copy
import sqlite3,json,threading
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from broker.calibration_rework import advance,decide,instruction


class CalibrationReworkTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(issue_id='issue',source_task='source',author='author',cto='cto',peer='peer',
            manifest_sha256='a'*64,criteria={'A01':'unchanged'},minimum_calls=8,
            diagnostic={'phase':'positive_reference','positive':{'tests':15,'failures':2}},
            paths=['/evidence/candidate/tests/test_new.py'])
        self.saved=[];self.calls=[]
        def wake(*args,**kwargs):
            self.calls.append((args,kwargs))
            self.assertTrue(self.saved[-1]['stage'].endswith('_intent'))
            return {'id':'wake-'+args[1]}
        self.fx=SimpleNamespace(remaining_calls=lambda:100,ensure_wakeup=wake,
            implementation_available=lambda *a:True,
            decision=lambda t:dict(action='request_test_revision',reason='Correct stale observation after settling.',optional_files=[]),
            read_evidence=lambda t:{self.config['paths'][0]:dict(lines=10,total_lines=10)})

    def save(self,state):self.saved.append(copy.deepcopy(state))

    def test_cto_peer_then_original_author_no_approval_or_gate_skip(self):
        state=dict(stage='cto_pending',delivery_approval=False,attempt_limit=1,revision_depth_reset=False)
        state=advance(self.config,state,[],self.fx,self.save,now=1)
        self.assertEqual(state['stage'],'cto_waiting')
        runs=[dict(id='cto-task',agent_id='cto',wakeup_id='wake-cto',status='completed')]
        state=advance(self.config,state,runs,self.fx,self.save,now=2)
        self.assertEqual(state['stage'],'peer_pending')
        state=advance(self.config,state,runs,self.fx,self.save,now=3)
        runs.append(dict(id='peer-task',agent_id='peer',wakeup_id='wake-peer',status='completed'))
        state=advance(self.config,state,runs,self.fx,self.save,now=4)
        self.assertEqual(state['stage'],'author_pending')
        state=advance(self.config,state,runs,self.fx,self.save,now=5)
        self.assertEqual(state['stage'],'author_dispatched')
        self.assertEqual([args[1] for args,kw in self.calls],['cto','peer','author'])
        self.assertFalse(state['delivery_approval']);self.assertFalse(state['revision_depth_reset'])
        self.assertIn('calibration and genuine Red',self.calls[-1][0][-1])
        advance(self.config,state,runs,self.fx,self.save,now=6)
        self.assertEqual(len(self.calls),3)

    def test_restart_after_ambiguous_intent_only_observes_never_reposts(self):
        state=dict(stage='cto_intent',intent_at=1)
        self.saved.append(state)
        def wake(*args,**kw):
            self.assertFalse(kw['allow_create']);return None
        self.fx.ensure_wakeup=wake
        self.assertEqual(advance(self.config,state,[],self.fx,self.save,now=2)['stage'],'cto_intent')
        self.assertEqual(advance(self.config,state,[],self.fx,self.save,now=1801)['stage'],'blocked')

    def test_stale_partial_self_or_rejected_decision_cannot_sponsor_author(self):
        state=dict(stage='cto_waiting',cto_wakeup='wake')
        run=dict(id='task',agent_id='cto',status='completed',wakeup_id='wake')
        for actor in ['peer','author']:
            with self.assertRaises(ValueError):decide(self.config,state,[{**run,'agent_id':actor}],self.fx,'cto')
        self.fx.read_evidence=lambda t:{self.config['paths'][0]:dict(lines=2,total_lines=10)}
        with self.assertRaises(ValueError):decide(self.config,state,[run],self.fx,'cto')
        self.fx.read_evidence=lambda t:{self.config['paths'][0]:dict(lines=10,total_lines=10)}
        self.fx.decision=lambda t:dict(action='escalate_cto',reason='Insufficient evidence',optional_files=[])
        with self.assertRaises(ValueError):decide(self.config,state,[run],self.fx,'cto')

    def test_budget_hold_does_not_record_or_dispatch_and_note_is_bounded(self):
        self.fx.remaining_calls=lambda:0
        state=dict(stage='cto_pending')
        self.assertEqual(advance(self.config,state,[],self.fx,self.save,now=1),state)
        self.assertEqual(self.calls,[]);self.assertEqual(self.saved,[])
        note=instruction(self.config,state)
        self.assertLess(len(note)+100,4000)
        self.assertIn('No shell, edits',note)

    def test_normal_supervisor_intakes_actual_failed_calibration_once_and_preserves_history(self):
        from broker import calibration_rework as lane,handoffs,harness_qualification as jobs,remediation_runtime_guard as guard
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);con.row_factory=sqlite3.Row
        handoffs.initialize(con)
        con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
        con.execute('CREATE TABLE harness_qualifications(task_id TEXT,identity TEXT,state TEXT)')
        route=dict(issue_id='issue',author='author',cto='cto',techlead='peer',enabled=True,
            contract_sha256='c'*64,test_first_files=['tests/test_new.py'],minimum_calls=8)
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(route)))
        old=dict(error='test_first_correction_failed_after_cto_diagnosis',phase='test_first',source_task='source')
        handoffs.save(con,'source','issue','test_first_blocked','cto',old,0)
        @contextmanager
        def db():
            yield con
            con.commit()
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),IMAGE='sha256:'+'a'*64,OWNER='owned')
        def docker(method,path,body=None):
            if path.startswith('/images/'):return dict(Id=b.IMAGE,Config=dict(Env=['PATH=/bin']))
            if path.startswith('/volumes/'):return dict(Labels={'delivery-kit.owner':'owned','delivery-kit.test-first-task':'source'})
            return info
        b.docker=docker
        expected=jobs.payload(b,'source','snapshot','b'*64)
        info=dict(Id='job',Config={k:v for k,v in expected.items() if k!='HostConfig'},HostConfig=expected['HostConfig'],
            State=dict(Status='exited',Running=False,ExitCode=1))
        identity=dict(payload=expected,volume='snapshot',manifest_sha256='b'*64)
        held=dict(stage='blocked',container_id='job',diagnostic=dict(phase='positive_reference',manifest_sha256='b'*64,test_sha256='d'*64,positive=dict(tests=15,failures=2)))
        con.execute('INSERT INTO harness_qualifications VALUES(?,?,?)',('source',json.dumps(identity),json.dumps(held)))
        source=dict(id='source',agent_id='author',status='completed')
        self.fx.ensure_wakeup=lambda *args,**kw:{'id':'wake-cto'}
        with patch.object(guard,'qualified',return_value=dict(amendment={'operation':'fixed'},criteria={'A01':'unchanged'})):
            self.assertTrue(lane.handle(b,route,[source],source,handoffs.load(con,'source'),self.fx))
            row=handoffs.load(con,'source');data=json.loads(row['data'])
            self.assertEqual(row['stage'],'calibration_rework')
            self.assertEqual(data['error'],old['error'])
            self.assertEqual(data['calibration_rework']['state']['stage'],'cto_waiting')
            self.assertFalse(data['calibration_rework']['state']['delivery_approval'])
            self.assertTrue(lane.handle(b,route,[source],source,row,self.fx))
            self.assertEqual(con.execute('SELECT count(*) FROM calibration_reworks').fetchone()[0],1)
            self.assertFalse(lane.handle(b,route,[source],{**source,'id':'later-author'},row,self.fx))
