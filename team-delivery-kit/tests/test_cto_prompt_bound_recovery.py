import copy
import unittest
from broker.cto_prompt_bound_recovery import qualify, dispatch, recover


class CTOPromptBoundRecoveryTests(unittest.TestCase):
    def evidence(self):
        return dict(enabled=True, test_first=True, author='author', cto='cto',
            actor='cto', issue='issue', task_issue='issue', mode='planning',
            status='failed', error='restricted broker stream failed: broker_internal',
            wakeup='wake', expected_wakeup='wake', lease='closed', active=0,
            red=False, pending=False, events=[('initialize', 1), ('session/new', 1)],
            chars=12175, qualified=True, client_rejected=True,
            diagnostic=dict(kind='rejected_snapshot',category='new_test_syntax_error'),
            source_task='author-task', old_task='cto-task', policy_sha256='a'*64)

    def test_only_verified_pre_prompt_failure_qualifies(self):
        proof=qualify(self.evidence())
        self.assertFalse(proof['author_retry_authorized'])
        self.assertFalse(proof['delivery_approval'])
        for key,value in [('active',1),('red',True),('pending',True),('chars',12000),
                          ('chars',32001),('actor','author'),('lease','running'),
                          ('client_rejected',False),('mode','implementation'),
                          ('events',[('initialize',1),('session/new',1),('session/prompt',0)])]:
            data=self.evidence();data[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):qualify(data)

    def test_durable_intent_then_uncertain_ack_is_observed_not_recreated(self):
        proof=qualify(self.evidence()); saved=[]; calls=[]
        def save(value):saved.append(copy.deepcopy(value))
        def wake(marker,allow_create):
            calls.append(allow_create)
            self.assertEqual(saved[-1]['state'],'intent')
            if allow_create:raise TimeoutError('uncertain')
            return {'id':'new-wake'}
        with self.assertRaises(TimeoutError):dispatch(None,proof,save,wake,100,32)
        record=dispatch(saved[-1],proof,save,wake,100,32)
        self.assertEqual(calls,[True,False]);self.assertEqual(record['wakeup_id'],'new-wake')
        self.assertEqual(dispatch(record,proof,save,wake,100,32),record)
        self.assertEqual(calls,[True,False])

    def test_budget_pause_does_not_consume_attempt_or_send(self):
        calls=[]
        self.assertIsNone(dispatch(None,qualify(self.evidence()),calls.append,
            lambda *a: self.fail('no wakeup'),31,32))
        self.assertEqual(calls,[])

    def test_changed_proof_cannot_reset_consumed_attempt(self):
        proof=qualify(self.evidence()); saved=[]
        record=dispatch(None,proof,saved.append,lambda *a:{'id':'wake'},100,32)
        other=dict(proof,policy_sha256='b'*64)
        with self.assertRaises(ValueError):dispatch(record,other,saved.append,lambda *a:self.fail(),100,32)

    def test_restart_after_acceptance_restores_handoff_without_external_effect(self):
        import json,sqlite3
        from contextlib import contextmanager
        from types import SimpleNamespace
        from broker import handoffs
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        handoffs.initialize(con)
        con.execute('CREATE TABLE cto_prompt_bound_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
        proof=qualify(self.evidence())
        record=dispatch(None,proof,lambda r:None,lambda *a:{'id':'new-wake'},100,32)
        con.execute('INSERT INTO cto_prompt_bound_recoveries VALUES (?,?)',('author-task',json.dumps(record)))
        data=dict(phase='test_first',error='test_first_cto_execution_failed',test_first_cto_wakeup='wake')
        handoffs.save(con,'author-task','issue','diagnose_cto','cto',data,0)
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db)
        route=dict(issue_id='issue',cto='cto',author='author')
        source=dict(id='author-task',status='completed',agent_id='author')
        self.assertTrue(recover(b,route,[],source,
                                handoffs.load(con,'author-task'),None))
        row=handoffs.load(con,'author-task')
        self.assertEqual(row['stage'],'test_first_cto_diagnosis')
        updated=json.loads(row['data']);self.assertEqual(updated['test_first_cto_wakeup'],'new-wake')
        # Another CTO failure cannot consume another attempt, even after restart.
        handoffs.save(con,'author-task','issue','test_first_blocked','cto',updated,1)
        self.assertFalse(recover(b,route,[],source,
                                 handoffs.load(con,'author-task'),None))
        con.close()

    def test_controller_collects_real_transport_evidence_before_dispatch(self):
        import json,sqlite3
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import handoffs,native
        from broker.acp_transport import ControllerPrompt
        from execution_context import freeze
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        handoffs.initialize(con)
        con.executescript('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT);'
            'CREATE TABLE leases(request_id TEXT,status TEXT);'
            'CREATE TABLE acp_events(request_id TEXT,method TEXT,success INTEGER);'
            'CREATE TABLE test_first_red(issue_id TEXT);'
            "INSERT INTO native_bindings VALUES ('request','cto-task','cto','issue');"
            "INSERT INTO leases VALUES ('request','closed');"
            "INSERT INTO acp_events VALUES ('request','initialize',1),('request','session/new',1);")
        route=dict(issue_id='issue',cto='cto',author='author',enabled=True,test_first=True,minimum_calls=32)
        source=dict(id='author-task',agent_id='author',status='completed')
        old=dict(id='cto-task',agent_id='cto',issue_id='issue',status='failed',wakeup_id='wake',
                 error='restricted broker stream failed: broker_internal')
        data=dict(phase='test_first',error='test_first_cto_execution_failed',test_first_cto_wakeup='wake',
                  diagnostic=self.evidence()['diagnostic'])
        handoffs.save(con,'author-task','issue','diagnose_cto','cto',data,0)
        @contextmanager
        def db():yield con
        def render(*args):
            return ControllerPrompt(dict(jsonrpc='2.0',id=1,method='session/prompt',
                params=dict(sessionId='s',prompt=[dict(type='text',text='x'*12175)])),freeze('brief','review'))
        sends=[]
        def wake(*args,**kwargs):
            receipt=json.loads(con.execute('SELECT receipt FROM cto_prompt_bound_recoveries').fetchone()[0])
            self.assertEqual(receipt['state'],'intent')
            sends.append((args,kwargs));return {'id':'new-wake'}
        fx=SimpleNamespace(settings={'agents':{'cto':'planning'}},remaining_calls=lambda:100,ensure_wakeup=wake)
        b=SimpleNamespace(db=db,native_task_prompt=render)
        with patch.object(native,'task_record',return_value=old),patch.object(native,'issue_record',return_value={'id':'issue'}):
            self.assertTrue(recover(b,route,[source,old],source,handoffs.load(con,'author-task'),fx))
        self.assertEqual(len(sends),1);self.assertTrue(sends[0][1]['allow_create'])
        result=json.loads(handoffs.load(con,'author-task')['data'])
        self.assertEqual(result['test_first_cto_wakeup'],'new-wake')
        self.assertEqual(result['cto_prompt_bound_recovery']['proof']['old_task'],'cto-task')
        con.close()
