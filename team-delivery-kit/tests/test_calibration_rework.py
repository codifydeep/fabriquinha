import unittest,copy,hashlib
import sqlite3,json,threading
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from broker.calibration_rework import advance,decide,instruction,recover_format,marker,recover_technical_escalation


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
        self.assertIn('EXPECTED Red',self.calls[-1][0][-1])
        self.assertIn('DELIVERY_CONTROLLER_CALIBRATION_V1',self.calls[-1][0][-1])
        self.assertNotIn('Run the full pinned suite',self.calls[-1][0][-1])
        advance(self.config,state,runs,self.fx,self.save,now=6)
        self.assertEqual(len(self.calls),3)

    def test_failed_sponsored_author_is_visible_to_cto_without_another_dispatch(self):
        state=dict(stage='author_dispatched',author_wakeup='wake-author',
                   cto_decision={'action':'request_test_revision'},peer_decision={'action':'request_test_revision'})
        run=dict(id='failed-author',agent_id='author',wakeup_id='wake-author',status='failed')
        for changed in [dict(agent_id='other'),dict(wakeup_id='other'),dict(status='running'),dict(status='completed')]:
            self.assertEqual(advance(self.config,state,[{**run,**changed}],self.fx,self.save),state)
        held=advance(self.config,state,[run],self.fx,self.save)
        self.assertEqual(held['stage'],'blocked');self.assertEqual(held['owner'],'cto')
        self.assertEqual(held['author_task'],'failed-author')
        self.assertFalse(held['author_retry_authorized']);self.assertFalse(held['delivery_approval'])
        self.assertEqual(held['cto_decision'],state['cto_decision'])
        self.assertEqual(self.calls,[])
        self.assertEqual(advance(self.config,held,[run],self.fx,self.save),held)

    def test_changed_calibration_diagnosis_retains_plan_without_author_wakeup(self):
        config={**self.config,'post_execution_diagnosis':dict(previous_diagnostic={'negative_controls_detected':16}),
            'diagnostic':dict(phase='background_timer_control',negative_controls={})}
        note=instruction(config,dict(stage='cto_pending'))
        self.assertIn('NEW FROZEN CALIBRATION INCIDENT',note)
        self.assertIn('"negative_controls_total": 16',note)
        self.assertIn('No shell, edits, author admission',note)
        held=advance(config,dict(stage='author_pending'),[],self.fx,self.save)
        self.assertEqual(held['stage'],'plan_qualified')
        self.assertFalse(held['author_retry_authorized'])
        self.assertFalse(held['delivery_approval'])
        self.assertEqual(held['required_action'],'execute_read_only_experiment_for_exact_calibration_plan')
        self.assertEqual(self.calls,[])

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
        self.assertEqual(decide(self.config,state,[run],self.fx,'cto')[1]['action'],'escalate_cto')
        self.fx.decision=lambda t:dict(action='approve',reason='Unsupported approval',optional_files=[])
        with self.assertRaises(ValueError):decide(self.config,state,[run],self.fx,'cto')

    def test_valid_technical_escalation_is_a_durable_hold_not_a_protocol_error(self):
        self.fx.decision=lambda t:dict(action='escalate_cto',reason='Experiment required',optional_files=[])
        for role in ('cto','peer'):
            state=dict(stage=role+'_waiting',**{role+'_wakeup':'wake'},at=1)
            run=dict(id='task-'+role,agent_id=role,status='completed',wakeup_id='wake')
            held=advance(self.config,state,[run],self.fx,self.save,now=2)
            self.assertEqual(held['category'],'calibration_technical_impediment')
            self.assertEqual(held[role+'_decision']['action'],'escalate_cto')
            self.assertEqual(held['owner'],'cto')
            self.assertFalse(held['author_retry_authorized']);self.assertFalse(held['delivery_approval'])
            self.assertEqual(advance(self.config,held,[run],self.fx,self.save),held)
        self.assertEqual(self.calls,[])

    def test_previous_valid_escalation_can_be_reclassified_once_without_replay(self):
        self.fx.decision=lambda t:dict(action='escalate_cto',reason='Experiment required',optional_files=[])
        state=dict(stage='blocked',category='surgical_failure_diagnosis_rejected',error_type='ValueError',cto_wakeup='wake')
        run=dict(id='task',agent_id='cto',status='completed',wakeup_id='wake')
        original=copy.deepcopy(state)
        held=recover_technical_escalation(self.config,state,[run],self.fx)
        self.assertEqual(state,original)
        self.assertEqual(held['category'],'calibration_technical_impediment')
        self.assertNotIn('error_type',held)
        self.assertEqual(held['escalation_classification_repair']['previous_state'],original)
        self.assertIsNone(recover_technical_escalation(self.config,held,[run],self.fx))
        self.assertIsNone(recover_technical_escalation(self.config,state,[{**run,'agent_id':'author'}],self.fx))
        self.fx.read_evidence=lambda t:{}
        self.assertIsNone(recover_technical_escalation(self.config,state,[run],self.fx))
        self.assertEqual(self.calls,[])

    def test_budget_hold_does_not_record_or_dispatch_and_note_is_bounded(self):
        self.fx.remaining_calls=lambda:0
        state=dict(stage='cto_pending')
        self.assertEqual(advance(self.config,state,[],self.fx,self.save,now=1),state)
        self.assertEqual(self.calls,[]);self.assertEqual(self.saved,[])
        note=instruction(self.config,state)
        self.assertLess(len(note)+100,4000)
        self.assertIn('No shell, edits',note)
        self.assertIn('DELIVERY_TYPED_DECISION_V1\n',note)

    def test_missing_adapter_marker_recovery_requires_actual_complete_failed_inspection_once(self):
        state=dict(stage='blocked',category='calibration_rework_rejected',cto_wakeup='wake',delivery_approval=False)
        task=dict(id='task',status='failed',agent_id='cto',issue_id='issue',wakeup_id='wake',
            handoff_note='DELIVERY_STRUCTURED_DECISION_V1:technical\nCALIBRATION GATE REWORK')
        reads=self.fx.read_evidence(task)
        config,new=recover_format(self.config,state,task,reads)
        self.assertEqual(new['stage'],'cto_pending')
        self.assertFalse(new['format_recovery']['decision_replayed'])
        self.assertFalse(new['format_recovery']['author_retry_authorized'])
        self.assertNotEqual(marker(config,'cto'),marker(self.config,'cto'))
        self.assertIsNone(recover_format(config,new,task,reads))
        for change in [dict(status='completed'),dict(agent_id='author'),dict(wakeup_id='other'),
                       dict(handoff_note=task['handoff_note']+'\nDELIVERY_TYPED_DECISION_V1')]:
            self.assertIsNone(recover_format(self.config,state,{**task,**change},reads))
        self.assertIsNone(recover_format(self.config,state,task,{}))

    def test_actual_instruction_passes_both_proxy_schema_and_typed_adapter_after_reads(self):
        from decision_schema import apply as decision_schema
        from typed_decision_contract import apply as typed_adapter,NAME
        body=dict(messages=[dict(role='user',content=instruction(self.config,dict(stage='cto_pending')))],
                  tools=[dict(type='function',function=dict(name='read_file',parameters={'type':'object','properties':{'path':{'type':'string'}}}))])
        for i,path in enumerate(self.config['paths']):
            body['messages'] += [dict(role='assistant',tool_calls=[dict(id='read-'+str(i),function=dict(
                name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=128))))]),
                dict(role='tool',tool_call_id='read-'+str(i),content=json.dumps(dict(content='1|pass',total_lines=1)))]
        result=typed_adapter(decision_schema(body))
        self.assertEqual(result['tool_choice']['function']['name'],NAME)
        properties=result['tools'][0]['function']['parameters']['properties']
        self.assertEqual(set(properties),{'action','reason','optional_files'})
        self.assertEqual(properties['optional_files']['maxItems'],0)
        self.assertNotIn('approve',properties['action']['enum'])

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
            saved=dict(stage='author_dispatched',author_wakeup='wake-author',
                       cto_decision={'action':'request_test_revision'},peer_decision={'action':'request_test_revision'})
            con.execute('UPDATE calibration_reworks SET state=? WHERE issue_id=?',(json.dumps(saved),'issue'))
            failed=dict(id='later-author',agent_id='author',wakeup_id='wake-author',status='failed')
            handoffs.save(con,failed['id'],'issue','test_first_blocked','cto',old,1)
            self.assertFalse(lane.handle(b,route,[source,failed],failed,handoffs.load(con,failed['id']),self.fx))
            original=handoffs.load(con,'source');result=json.loads(original['data'])['calibration_rework']['state']
            self.assertEqual(result['category'],'calibration_author_failed')
            self.assertEqual(result['author_task'],failed['id']);self.assertEqual(original['owner'],'cto')
            self.assertEqual(handoffs.load(con,failed['id'])['stage'],'test_first_blocked')
            # A later authenticated failed calibration is a separate diagnosis,
            # not a reset of the consumed author correction.
            con.execute('CREATE TABLE failed_test_checkpoint_executions(issue_id TEXT,source_task TEXT,receipt TEXT)')
            con.execute('INSERT INTO failed_test_checkpoint_executions VALUES(?,?,?)',
                ('issue',failed['id'],json.dumps(dict(status='rejected',delivery_approved=False))))
            expected=jobs.payload(b,failed['id'],'later-snapshot','e'*64)
            info=dict(Id='later-job',Config={k:v for k,v in expected.items() if k!='HostConfig'},HostConfig=expected['HostConfig'],
                State=dict(Status='exited',Running=False,ExitCode=1))
            identity=dict(issue_id='issue',task_id=failed['id'],payload=expected,volume='later-snapshot',manifest_sha256='e'*64)
            b.docker_stdout=lambda *args,**kwargs:'fixed calibration rejection'
            held=dict(stage='blocked',container_id='later-job',output_sha256=hashlib.sha256(b'fixed calibration rejection').hexdigest(),diagnostic=dict(phase='background_timer_control',
                manifest_sha256='e'*64,test_sha256='f'*64,positive=dict(tests=15,failures=0),negative_controls={}))
            con.execute('INSERT INTO harness_qualifications VALUES(?,?,?)',(failed['id'],json.dumps(identity),json.dumps(held)))
            original_docker=b.docker
            b.docker=lambda method,path,body=None:dict(Labels={'delivery-kit.owner':'owned','delivery-kit.test-first-task':failed['id']}) if path.startswith('/volumes/') else original_docker(method,path,body)
            failed['created_at']='2026-10-08T12:00:00Z'
            prior=handoffs.load(con,failed['id'])
            # The same manifest cannot re-open an incident.
            original_manifest=identity['manifest_sha256']
            identity['manifest_sha256']='b'*64;held['diagnostic']['manifest_sha256']='b'*64
            con.execute('UPDATE harness_qualifications SET identity=?,state=? WHERE task_id=?',
                (json.dumps(identity),json.dumps(held),failed['id']))
            with patch.object(jobs,'verify_job'):
                self.assertFalse(lane.handle(b,route,[source,failed],failed,prior,self.fx))
            identity['manifest_sha256']=original_manifest;held['diagnostic']['manifest_sha256']=original_manifest
            con.execute('UPDATE harness_qualifications SET identity=?,state=? WHERE task_id=?',
                (json.dumps(identity),json.dumps(held),failed['id']))
            self.assertTrue(lane.handle(b,route,[source,failed],failed,prior,self.fx))
            archived=con.execute('SELECT source_task,state FROM calibration_rework_history WHERE issue_id=?',('issue',)).fetchone()
            self.assertEqual(archived[0],'source')
            self.assertEqual(json.loads(archived[1])['category'],'calibration_author_failed')
            current=con.execute('SELECT source_task,config,state FROM calibration_reworks WHERE issue_id=?',('issue',)).fetchone()
            self.assertEqual(current[0],failed['id'])
            self.assertEqual(json.loads(current[2])['stage'],'cto_waiting')
            self.assertFalse(json.loads(current[1])['post_execution_diagnosis']['author_retry_authorized'])
            self.assertTrue(lane.handle(b,route,[source,failed],failed,handoffs.load(con,failed['id']),self.fx))
            self.assertEqual(con.execute('SELECT count(*) FROM calibration_rework_history').fetchone()[0],1)
