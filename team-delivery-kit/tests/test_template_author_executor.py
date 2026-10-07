import copy,json,sqlite3,threading,tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from broker import template_author_executor as executor,handoffs


class TemplateExecutorTests(unittest.TestCase):
    def cfg(self):return dict(issue_id='issue',source_task='source',author='author',minimum_calls=8)
    def state(self):return dict(stage='plan_qualified',cto_decision={'reason':'After settlement.'},peer_decision={'reason':'Preserve pending.'},peer_task='peer',executor=dict(status='ready',contract_sha256='a'*64,worker_image='sha256:'+'b'*64,surgical={'protocol':'typed_template_v5'}))

    def test_dispatch_intent_survives_restart_without_second_post(self):
        cfg=self.cfg();state=self.state();saved=[];calls=[]
        def wake(*a,**kw):
            calls.append(kw['allow_create']);self.assertEqual(saved[-1]['executor']['status'],'intent');return None
        effects=SimpleNamespace(remaining_calls=lambda:100,implementation_available=lambda *a:True,ensure_wakeup=wake)
        state=executor.advance(cfg,state,effects,lambda s:saved.append(copy.deepcopy(s)))
        executor.advance(cfg,state,effects,lambda s:saved.append(copy.deepcopy(s)))
        self.assertEqual(calls,[True,False])
        self.assertEqual(state['executor']['status'],'intent')
        self.assertFalse(state['executor'].get('delivery_approval',False))
        effects.remaining_calls=lambda:0
        self.assertEqual(executor.advance(cfg,state,effects,saved.append),state)
        self.assertEqual(calls,[True,False])

    def test_capability_is_only_for_exact_live_author_wakeup(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con)
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT,config TEXT,state TEXT)')
        cfg=self.cfg();state=self.state();state['executor'].update(status='waiting',wakeup_id='wake')
        con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',('source',json.dumps(cfg),json.dumps(state)))
        handoffs.save(con,'source','issue','calibration_failure_plan','cto',{'calibration_failure_plan':{'state':state}},0)
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db)
        task=dict(id='new-author',issue_id='issue',agent_id='author',wakeup_id='wake',status='running')
        self.assertEqual(executor.for_task(b,'issue',task)['surgical']['protocol'],'typed_template_v5')
        self.assertIsNone(executor.for_task(b,'issue',{**task,'agent_id':'reviewer'}))
        self.assertIsNone(executor.for_task(b,'issue',{**task,'status':'completed'}))
        # The native broker transport passes task_binding: task_id and no status.
        # Both interfaces must select the same grant, using authoritative status.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'native.json').write_text('{}')
            bound=dict(task_id=task['id'],agent_id='author',issue_id='issue',wakeup_id='wake')
            with patch('broker.native.task_record',return_value=task) as lookup:
                self.assertEqual(executor.for_task(SimpleNamespace(db=db,STATE=root),'issue',bound),executor.for_task(b,'issue',task))
                lookup.assert_called_once_with({},'new-author','author')
            with patch('broker.native.task_record',return_value={**task,'status':'failed'}):
                self.assertIsNone(executor.for_task(SimpleNamespace(db=db,STATE=root),'issue',bound))
            with patch('broker.native.task_record',return_value={**task,'wakeup_id':'foreign'}):
                with self.assertRaises(ValueError):executor.for_task(SimpleNamespace(db=db,STATE=root),'issue',bound)
        with self.assertRaises(ValueError):executor.for_task(b,'issue',{**task,'task_id':'different'})
        with self.assertRaises(ValueError):executor.for_task(b,'issue',{**task,'wakeup_id':'foreign'})
        executor.observe(SimpleNamespace(db=db,LOCK=threading.RLock()),dict(issue_id='issue',author='author',cto='cto'),{**task,'status':'completed'})
        stored=json.loads(con.execute('SELECT state FROM calibration_failure_plans').fetchone()[0])
        self.assertEqual(stored['executor']['status'],'author_completed_awaiting_gates')
        self.assertFalse(stored['executor']['delivery_approval'])

    def test_historical_failures_do_not_starve_a_new_exact_executor(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT,config TEXT,state TEXT)')
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db)
        old=self.state();old['executor'].update(status='blocked',wakeup_id='old-wake')
        active=self.state();active['executor'].update(status='waiting',wakeup_id='new-wake')
        con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',('old',json.dumps(self.cfg()),json.dumps(old)))
        con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',('new',json.dumps({**self.cfg(),'source_task':'new-source'}),json.dumps(active)))
        task=dict(id='new-author',agent_id='author',issue_id='issue',wakeup_id='new-wake',status='running')
        self.assertEqual(executor.for_task(b,'issue',task)['surgical']['protocol'],'typed_template_v5')
        with self.assertRaises(ValueError):executor.for_task(b,'issue',{**task,'wakeup_id':'old-wake'})
        self.assertEqual(json.loads(con.execute("SELECT state FROM calibration_failure_plans WHERE source_task='old'").fetchone()[0]),old)
        old['executor']['status']='waiting'
        con.execute("UPDATE calibration_failure_plans SET state=? WHERE source_task='old'",(json.dumps(old),))
        with self.assertRaises(ValueError):executor.for_task(b,'issue',task)

    def test_recovery_only_grant_is_selected_without_rearming_predecessor(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT,config TEXT,state TEXT)')
        con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT)')
        con.execute("INSERT INTO native_bindings VALUES('request','task','author')")
        state=self.state();active={**state['executor'],'status':'waiting','wakeup_id':'wake'}
        state.pop('executor');state['binding_recovery']={'executor':active}
        con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',('source',json.dumps(self.cfg()),json.dumps(state)))
        @contextmanager
        def db():yield con
        task=dict(id='task',agent_id='author',issue_id='issue',wakeup_id='wake',status='running')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'native.json').write_text('{}')
            b=SimpleNamespace(db=db,STATE=root)
            with patch('broker.native.task_record',return_value=task):
                self.assertEqual(executor.worker_config(b,'request','issue')['surgical']['protocol'],'typed_template_v5')
            state['binding_recovery']['executor']['status']='blocked'
            con.execute('UPDATE calibration_failure_plans SET state=?',(json.dumps(state),))
            with patch('broker.native.task_record') as lookup:
                self.assertIsNone(executor.worker_config(b,'missing','issue'))
                lookup.assert_not_called()

    def test_registry_qualification_cannot_omit_security_flags(self):
        proof=dict(schema='surgical-template-registry-probe-v5',status='passed',uid=10000,network='none',model_calls=0,
                   delivery_approval=False,worker_image='sha256:'+'a'*64,proxy_image='sha256:'+'b'*64,
                   **{k:True for k in executor.FLAGS})
        executor.validate_qualification(proof)
        for key in executor.FLAGS:
            with self.assertRaises(ValueError):executor.validate_qualification({**proof,key:False})
        for change in [dict(model_calls=1),dict(delivery_approval=True),dict(worker_image='latest'),dict(network='bridge')]:
            with self.assertRaises(ValueError):executor.validate_qualification({**proof,**change})
