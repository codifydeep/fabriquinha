"""Every failed phase gets scoped evidence and an executable technical owner."""
from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from fabriquinha.recovery import Recovery,Diagnostic
from test_delivery_core import configuration
from test_intake import document,work


class RecoveryPhases(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.work=self.root/'work';self.work.mkdir()
        (self.work/'app.py').write_text('VALUE = 1\n')
        self.store=Store(self.root/'private');self.snapshot=self.store.capture(self.work)
        self.project=Project.parse({**configuration(),'technical_roles':{'lead':'lead','cto':'cto'},
            'coordination_roles':{'product':'product','lead':'lead'}})
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row;self.addCleanup(self.conn.close)
        self.conn.executescript('CREATE TABLE tasks(id PRIMARY KEY,body,status,assignee,workspace_path,result,idempotency_key,created_at DEFAULT 0);'
            'CREATE TABLE task_runs(id PRIMARY KEY,task_id,profile,ended_at,summary,error,metadata);'
            'CREATE TABLE task_events(id PRIMARY KEY,task_id,run_id,kind,payload);'
            'CREATE TABLE task_links(parent_id,child_id);')
        self.created=[]
        def get_task(conn,ident):
            row=conn.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
            return SimpleNamespace(**dict(row)) if row else None
        def create(conn,**values):
            ident='diag-'+str(len(self.created));self.created.append(values)
            conn.execute('INSERT INTO tasks(id,body,status,assignee,workspace_path,result,idempotency_key) VALUES(?,?,?,?,?,?,?)',(ident,values['body'],'ready',values['assignee'],
                values['workspace_path'],None,values['idempotency_key']))
            return ident
        self.kb=SimpleNamespace(get_task=get_task,create_task=create)
        self.board=SimpleNamespace(ensure=lambda r:None)
        self.recovery=Recovery(self.project,self.store,self.board)

    def failed(self,kind,*,reviewing=False,triage=False,inputs=None):
        actor='cto' if reviewing and kind=='plan' else 'lead' if kind=='plan' else 'backend'
        body=dict(version=1,kind=kind,release='v1',inputs=inputs or {})
        task='source';self.conn.execute('INSERT INTO tasks(id,body,status,assignee,workspace_path,result,idempotency_key) VALUES(?,?,?,?,?,?,?)',
            (task,json.dumps(body),'triage' if triage else 'blocked',actor,str(self.work),None,None))
        self.conn.execute('INSERT INTO task_runs VALUES(1,?,?,1,?,?,?)',(task,actor,'protocol failed',None,'{}'))
        self.conn.execute('INSERT INTO task_events VALUES(1,?,1,?,?)',(task,'claimed',json.dumps({'source_status':'review' if reviewing else 'ready'})))
        self.conn.execute('INSERT INTO task_events VALUES(3,?,1,?,?)',
            (task,'block_loop_detected' if triage else 'blocked',json.dumps({'reason':'protocol failed'})))
        return self.kb.get_task(self.conn,task)

    def approve(self):
        author=Run('brief',1,'product','brief',False,'product','v1','brief-contract')
        proposal=self.store.record('product_brief',author.binding(),dict(project=self.project.fingerprint(),document=document()))
        return self.store.record('brief_approval',dict(actor='ceo',task='brief',release='v1',brief=proposal),
            dict(project=self.project.fingerprint(),decision='approve'))

    def discover(self,task):
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)):
            issues=self.recovery.reconcile(self.conn,Mock())
        self.assertEqual(issues,{})
        self.assertTrue(self.created,'The phase must not disappear from technical recovery')
        key=json.loads(self.created[-1]['body'])['inputs']['incident']
        return key,self.store.receipt(key,kind='incident')

    def test_blocked_planning_creates_one_cto_incident_with_approved_context(self):
        task=self.failed('plan',inputs={'approved_brief':self.approve()})
        key,incident=self.discover(task)
        self.assertEqual(self.created[-1]['assignee'],'cto')
        self.assertEqual(incident['payload']['document_kind'],'plan')
        tree=self.store.tree(incident['payload']['snapshot'])
        self.assertEqual(json.loads((tree/'approved_brief.json').read_text()),document())
        self.discover(task);self.assertEqual(len(self.created),1)

    def test_integration_uses_approved_delivery_instead_of_its_empty_workspace(self):
        original=Run('implementation',2,'lead','implementation',True,'backend','v1','implementation-contract')
        receipt=self.store.record('delivery_review',original.binding(),dict(project=self.project.fingerprint(),snapshot=self.snapshot,
            verdict=dict(decision='approve',reason='Accepted',findings=[])))
        task=self.failed('integration',inputs={'delivery':receipt})
        _,incident=self.discover(task)
        self.assertEqual(incident['payload']['snapshot'],self.snapshot)
        self.assertEqual(incident['binding']['kind'],'integration')

    def test_native_triage_dispatches_cto_without_resetting_or_reclaiming_the_source(self):
        task=self.failed('tests',triage=True)
        _,incident=self.discover(task)
        self.assertEqual(self.created[-1]['assignee'],'cto')
        self.assertFalse(incident['payload']['resume_allowed'])
        self.assertEqual(self.kb.get_task(self.conn,'source').status,'triage')

    def test_planning_experiment_executes_fixed_validator_without_writing_author_files(self):
        key,incident=self.discover(self.failed('plan',inputs={'approved_brief':self.approve()}))
        run=Run('diag-0',2,'cto','diagnostic',False,'cto','v1','diagnostic-contract')
        self.board.input=lambda *a,**kw:key
        q=Quality(self.project,self.store,None,self.board)
        sandbox=SimpleNamespace(project=self.project,store=self.store,board=self.board,run=run,close=Mock())
        operation=Diagnostic(sandbox,q)
        # Evidence must advertise the mounted tree, never the private host path.
        self.kb.latest_run=lambda *a:None
        with patch('fabriquinha.recovery.native',return_value=(self.kb,SimpleNamespace(connect_closing=lambda:nullcontext(self.conn)),None)):
            evidence=operation.evidence()
        self.assertEqual(evidence['incident']['workspace'],'/workspace')
        self.assertNotIn(str(self.work),json.dumps(evidence))
        self.assertEqual(operation.incident['workspace'],str(self.work))
        result=operation.validate({'hypothesis':'The candidate has a valid complete work DAG','document':work()})
        self.assertTrue(result['report']['valid'])
        invalid=operation.validate({'hypothesis':'The original missing document is incomplete'})
        self.assertFalse(invalid['report']['valid'])
        self.assertEqual((self.work/'app.py').read_text(),'VALUE = 1\n')
        with self.assertRaises(ValueError):operation.validate({'hypothesis':'Write source','replacements':{'app.py':'changed'}})

    def test_triage_has_only_hold_and_cannot_be_released_by_a_diagnostic_decision(self):
        key,_=self.discover(self.failed('tests',triage=True))
        self.board.input=lambda *a,**kw:key
        run=Run('diagnostic',2,'cto','diagnostic',False,'cto','v1','diagnostic-contract')
        q=Quality(self.project,self.store,None,self.board)
        sandbox=SimpleNamespace(project=self.project,store=self.store,board=self.board,run=run,close=Mock())
        operation=Diagnostic(sandbox,q)
        self.assertEqual(operation.actions(),['hold'])
        operation.experiment='even-an-experiment-cannot-reset-triage'
        with self.assertRaises(ValueError):operation.decide(dict(action='resume',reason='Do not bypass triage',
            findings=[dict(path='app.py',line=1,detail='Needs a scoped protocol repair before retry')]))
        sandbox.close.assert_not_called()

    def test_expired_controller_effect_cannot_be_blindly_retried_by_integration(self):
        author=Run('implementation',2,'lead','implementation',True,'backend','v1','contract')
        delivery=self.store.record('delivery_review',author.binding(),dict(project=self.project.fingerprint(),
            snapshot=self.snapshot,verdict=dict(decision='approve',reason='Accepted',findings=[])))
        task=self.failed('integration',inputs={'delivery':delivery})
        from fabriquinha.effects import write_json
        write_json(self.recovery.journal.root/'expired.json',dict(identity={'binding':{'task':'source'}},state='intent',deadline=0))
        _,incident=self.discover(task)
        self.assertFalse(incident['payload']['resume_allowed'])
        self.assertEqual(incident['payload']['controller_effects'],['expired'])

    def test_foreign_integration_delivery_is_not_shared_with_a_diagnostic_agent(self):
        author=Run('other-implementation',2,'lead','implementation',True,'backend','other-release','contract')
        delivery=self.store.record('delivery_review',author.binding(),dict(project=self.project.fingerprint(),
            snapshot=self.snapshot,verdict=dict(decision='approve',reason='Accepted',findings=[])))
        self.failed('integration',inputs={'delivery':delivery})
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)):
            issues=self.recovery.reconcile(self.conn,Mock())
        self.assertFalse(self.created)
        self.assertEqual(issues['source']['owner'],'cto')
        self.assertIn('next_action',issues['source'])

    def test_resumed_worker_gets_full_diagnostic_findings_even_if_native_prose_is_capped(self):
        key,incident=self.discover(self.failed('plan',inputs={'approved_brief':self.approve()}))
        diagnostic=Run('diag-0',2,'cto','diagnostic',False,'cto','v1',digest(json.loads(self.created[-1]['body'])))
        experiment=self.store.record('diagnostic_experiment',diagnostic.binding(),dict(incident=key,validator='plan',report={'valid':True}))
        detail='Keep every approved criterion and correct only the dependency edge. '*30
        verdict=dict(decision='changes',reason='Correct the plan from this validated guidance',findings=[dict(path='document.json',line=1,detail=detail)])
        decision=self.store.record('diagnostic_decision',diagnostic.binding(),dict(project=self.project.fingerprint(),
            incident=key,experiment=experiment,action='resume',verdict=verdict))
        self.conn.execute('CREATE TABLE task_comments(id PRIMARY KEY,task_id,author,body)')
        self.conn.execute('INSERT INTO task_comments VALUES(1,?,?,?)',('source','cto','DIAG '+decision+' capped prose'))
        original=Run(**incident['binding']);resumed=replace(original,number=3)
        api=SimpleNamespace(connect_closing=lambda:nullcontext(self.conn))
        with patch('fabriquinha.recovery.native',return_value=(None,api,None)):
            self.assertEqual(self.recovery.guidance(resumed)[0]['verdict']['findings'][0]['detail'],detail)
            self.assertEqual(self.recovery.guidance(replace(resumed,actor='cto',reviewing=True)),[])
            with self.assertRaises(ValueError):self.recovery.guidance(replace(resumed,contract='different'))

    def test_hold_keeps_a_concrete_next_action_and_is_never_reported_as_resolved(self):
        key,incident=self.discover(self.failed('tests',triage=True))
        task=self.kb.get_task(self.conn,'diag-0');body=json.loads(task.body);task.status='done'
        run=Run(task.id,2,'cto','diagnostic',False,'cto','v1',digest(body))
        verdict=dict(decision='changes',reason='Repair the review protocol before asking for another independent review.',
            findings=[dict(path='app.py',line=1,detail='Do not reset the native triage counter.')])
        decision=self.store.record('diagnostic_decision',run.binding(),dict(project=self.project.fingerprint(),
            incident=key,action='hold',verdict=verdict,experiment=None))
        self.recovery.cards=lambda c:[task]
        self.kb.latest_run=lambda c,ident:SimpleNamespace(id=1 if ident=='source' else 2,metadata={'diagnosis':decision})
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)):
            status=self.recovery.status(self.conn)
        self.assertEqual(status[0]['state'],'held');self.assertEqual(status[0]['owner'],'cto')
        self.assertEqual(status[0]['next_action'],verdict);self.assertFalse(status[0]['delivery_approval'])

    def test_infrastructure_diagnosis_can_cite_incident_without_inventing_a_product_defect(self):
        key,_=self.discover(self.failed('tests',triage=True))
        self.board.input=lambda *a,**kw:key
        run=Run('diagnostic',2,'cto','diagnostic',False,'cto','v1','diagnostic-contract')
        q=Quality(self.project,self.store,None,self.board)
        sandbox=SimpleNamespace(project=self.project,store=self.store,board=self.board,run=run,close=Mock())
        operation=Diagnostic(sandbox,q)
        reason='The native breaker requires a protocol repair, not a change to the approved product.'
        for evidence in ['experiment','unrelated-receipt']:
            with self.assertRaises(ValueError):operation.decide(dict(action='hold',reason=reason,
                findings=[dict(evidence=evidence,detail='Unavailable evidence must not be accepted')]))
        kb=SimpleNamespace(complete_task=lambda *a,**kw:True)
        api=SimpleNamespace(connect_closing=lambda:nullcontext(None))
        with patch('fabriquinha.recovery.native',return_value=(kb,api,None)):
            result=operation.decide(dict(action='hold',reason=reason,
                findings=[dict(evidence='incident',detail='Preserve triage and repair the review protocol before retry.')]))
        record=self.store.receipt(result['diagnosis'],kind='diagnostic_decision')
        self.assertEqual(record['payload']['verdict']['findings'][0]['evidence'],'incident')
        self.assertFalse(result['delivery_approval'])


if __name__=='__main__':unittest.main()
