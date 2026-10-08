import copy
import unittest
from broker import provider_diagnosis_recovery as r


class ProviderDiagnosisTests(unittest.TestCase):
    def evidence(self):
        return dict(source_task='author-task',failed_cto='cto-task',old_wakeup='old',
            issue='issue',actor='cto',cto='cto',author='author',enabled=True,test_first=True,
            mode='planning',source_status='failed',status='failed',failure_reason='agent_error.provider_server_error',
            lease='closed',active=False,red=False,pending=False,
            diagnostic={'kind':'unchanged_seed','files':{'new.py':'hash'}},
            failure={'version':'acp-failure-receipt-v1','categories':['provider_configuration'],
                     'cause':'classified_hint','method':'session/prompt','approval':False},
            qualification={'operation':'provider_diagnosis_transport_qualification_v1',
                'proxy_image':'sha256:'+'a'*64,'model':'anthropic/claude-haiku-5.5',
                'routing_sha256':'b'*64,'response_sha256':'c'*64,'execution_id':'probe',
                'worker_tool_executed':False,'delivery_approval':False})

    def test_qualification_is_cto_only_not_author_retry_or_proven_historical_cause(self):
        p=r.qualify(self.evidence())
        self.assertFalse(p['author_retry_authorized'])
        self.assertFalse(p['delivery_approval'])
        self.assertFalse(p['historical_http_status_proven'])

    def test_wrong_owner_active_red_or_missing_receipt_cannot_resume(self):
        for field,value in [('actor','author'),('mode','implementation'),('source_status','running'),
                            ('status','completed'),('lease','running'),('active',True),('red',True),
                            ('pending',True),('failure_reason','agent_error.process_failure'),
                            ('qualification',{}),('diagnostic',None),('enabled',False)]:
            e=self.evidence();e[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):r.qualify(e)
        e=self.evidence();e['failure']['approval']=True
        with self.assertRaises(ValueError):r.qualify(e)

    def test_canary_requires_real_adapter_hash_and_routing_not_just_http200(self):
        event=dict(event='model_proxy_request',status=200,execution_id='probe',
            routing_compatibility='haiku_named_tool_v1',upstream_require_parameters=False,
            require_parameters=True,tool_count=1,decision_adapter='validated_typed_decision_adapter_v1',
            decision_output_sha256='a'*64,call_number=7)
        receipt=dict(operation='validated_typed_decision_adapter_v1',output_sha256='a'*64,schema_sha256='b'*64,
                     worker_tool_executed=False,delivery_approval=False,model_values_preserved=True)
        r.validate_canary(event,receipt,'probe','a'*64,'b'*64)
        for key,value in [('status',404),('execution_id','other'),('tool_count',0),
                          ('decision_adapter',None),('upstream_require_parameters',True),
                          ('decision_output_sha256','b'*64)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                r.validate_canary({**event,key:value},receipt,'probe','a'*64,'b'*64)
        with self.assertRaises(ValueError):r.validate_canary(event,receipt,'probe','a'*64,'c'*64)

    def test_restart_after_acceptance_restores_only_pointer_then_stops(self):
        import json,sqlite3
        from contextlib import contextmanager
        from types import SimpleNamespace
        from broker import handoffs
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        handoffs.initialize(con)
        con.executescript('CREATE TABLE provider_diagnosis_qualifications(execution_id TEXT,proof TEXT,at REAL);'
                         'CREATE TABLE provider_diagnosis_recoveries(source_task TEXT PRIMARY KEY,record TEXT);')
        proof=r.qualify(self.evidence())
        record={'state':'accepted','proof':proof,'wakeup_id':'new','at':10}
        con.execute('INSERT INTO provider_diagnosis_recoveries VALUES(?,?)',('author-task',json.dumps(record)))
        data={'phase':'test_first','error':'test_first_cto_execution_failed',
              'test_first_cto_wakeup':'old','diagnostic':self.evidence()['diagnostic']}
        handoffs.save(con,'author-task','issue','test_first_blocked','cto',data,1)
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db)
        route={'enabled':True,'test_first':True,'issue_id':'issue','cto':'cto','author':'author'}
        source={'id':'author-task','status':'failed'}
        self.assertTrue(r.recover(b,route,[],source,handoffs.load(con,'author-task'),None))
        row=handoffs.load(con,'author-task');updated=json.loads(row['data'])
        self.assertEqual(row['stage'],'test_first_cto_diagnosis')
        self.assertEqual(updated['test_first_cto_wakeup'],'new')
        handoffs.save(con,'author-task','issue','test_first_blocked','cto',updated,11)
        self.assertFalse(r.recover(b,route,[],source,handoffs.load(con,'author-task'),None))
        con.close()

    def test_once_only_dispatch_observes_unknown_outcome_without_second_post(self):
        from broker.cto_prompt_bound_recovery import dispatch
        saved=[];calls=[];proof=r.qualify(self.evidence())
        def wake(marker,allow):calls.append(allow);return None
        pending=dispatch(None,proof,saved.append,wake,100,32)
        dispatch(pending,proof,saved.append,wake,100,32)
        self.assertEqual(calls,[True,False])
        changed=copy.deepcopy(proof);changed['qualification']['proxy_image']='sha256:'+'d'*64
        with self.assertRaises(ValueError):dispatch(pending,changed,saved.append,wake,100,32)
