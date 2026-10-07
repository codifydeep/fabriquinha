import copy,json,sqlite3,unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import template_failure_diagnosis as diagnosis,calibration_rework as lane,handoffs


class TemplateFailureDiagnosisTests(unittest.TestCase):
    def messages(self):
        rows=[dict(type='tool_use',tool='read_file',call_id='read')]
        for i,category in enumerate(('file_size_exceeded','replacement_not_unique_or_bounded')):
            rows.extend([dict(type='tool_use',tool='surgical_test_edit',call_id=str(i)),
                dict(type='tool_result',tool='surgical_test_edit',call_id=str(i),output_truncated=False,
                     output='surgical_test_edit failed: surgical_edit_rejected:'+category+':hint')])
        return rows

    def test_denials_are_actual_distinct_paired_failures_not_prose_or_success(self):
        rows=self.messages();proof=diagnosis.denials(rows)
        self.assertFalse(proof['author_retry_authorized']);self.assertFalse(proof['delivery_approval'])
        self.assertEqual([r['category'] for r in proof['results']],['file_size_exceeded','replacement_not_unique_or_bounded'])
        cases=[rows[:-1],rows+[dict(type='tool_use',tool='terminal')],rows[1:]]
        changed=copy.deepcopy(rows);changed[-1]['output_truncated']=True;cases.append(changed)
        changed=copy.deepcopy(rows);changed[-1]['call_id']='unpaired';cases.append(changed)
        changed=copy.deepcopy(rows);changed[-1]['output']='success';cases.append(changed)
        changed=copy.deepcopy(rows);changed[-1]['output']=changed[2]['output'];cases.append(changed)
        for value in cases:
            with self.subTest(value=value),self.assertRaises(ValueError):diagnosis.denials(value)

    def probe_state(self):
        return dict(stage='preservation_pending',probe={'name':'owned-probe','payload':{'fixed':True}})

    def test_probe_reboot_observes_unknown_intent_without_second_create(self):
        requests=[];saved=[]
        def docker(method,path,body=None):requests.append((method,path));return None
        b=SimpleNamespace(docker=docker)
        state=diagnosis.probe(b,{},self.probe_state(),saved.append)
        self.assertEqual(saved[0]['stage'],'preservation_intent')
        state=diagnosis.probe(b,{},state,saved.append)
        self.assertEqual(sum(m=='POST' for m,p in requests),1)
        self.assertEqual(state['stage'],'preservation_intent')
        with patch('broker.template_failure_diagnosis.time.time',return_value=state['intent_at']+1801):
            state=diagnosis.probe(b,{},state,saved.append)
        self.assertEqual(state['stage'],'blocked')
        self.assertEqual(sum(m=='POST' for m,p in requests),1)

    def test_measured_preservation_advances_only_to_diagnosis(self):
        proof=dict(operation='template_admission_preservation_v1',status='passed',manifest_sha256='a'*64,
            test_sha256='b'*64,files=63,test_bytes=32700,file_limit_bytes=32768,available_growth_bytes=68,
            all_files_unchanged=True,delivery_approval=False)
        config=dict(manifest_sha256='a'*64,diagnostic={'test_sha256':'b'*64})
        b=SimpleNamespace(docker=lambda *a:dict(Id='job',State={'Running':False,'Status':'exited','ExitCode':0}),
            docker_stdout=lambda *a,**kw:json.dumps(proof))
        state={**self.probe_state(),'stage':'preservation_intent','intent_at':0}
        with patch('broker.harness_qualification.verify_job'):
            next_state=diagnosis.probe(b,config,state,lambda s:None)
            self.assertEqual(next_state['stage'],'cto_pending')
            self.assertNotIn('executor',next_state)
            for key,value in [('available_growth_bytes',69),('test_bytes',True),('all_files_unchanged',False),('delivery_approval',True)]:
                broken={**proof,key:value};b.docker_stdout=lambda *a,**kw:json.dumps(broken)
                with self.subTest(key=key),self.assertRaises(ValueError):diagnosis.probe(b,config,state,lambda s:None)

    def test_instruction_explains_denials_and_does_not_authorize_retry(self):
        config=dict(diagnosis_only=True,execution_failure=diagnosis.denials(self.messages()),
            experiment_summary={'diagnostic_copy_only':True},diagnostic={'phase':'positive_reference'},
            paths=['/evidence/candidate/test.py'],criteria={'A01':'unchanged'})
        state=dict(stage='cto_pending',probe={'proof':dict(all_files_unchanged=True,test_bytes=32700,
            file_limit_bytes=32768,available_growth_bytes=68)})
        note=lane.instruction(config,state)
        self.assertIn('all original bytes remain unchanged',note)
        self.assertIn('"available_growth_bytes": 68',note)
        self.assertIn('No larger file limit',note)
        self.assertIn('Neither decision grants execution',note)
        config['paths']=['/evidence/candidate/app/static/app.js','/evidence/candidate/tests/test_service_mode_indicator.py']
        config['criteria']={f'A0{i}':'unchanged' for i in range(1,9)}
        peer={**state,'stage':'peer_pending','cto_decision':{'action':'request_test_revision','reason':'a'*1200,'optional_files':[]}}
        self.assertLess(len(lane.instruction(config,peer))+100,4001)
        with self.assertRaises(ValueError):lane.instruction(config,dict(stage='cto_pending'))

    def test_normal_intake_preserves_predecessor_and_never_reposts_probe(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con)
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
        con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT,agent_id TEXT)')
        con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
        con.execute("INSERT INTO leases VALUES('req','closed')")
        con.execute("INSERT INTO native_bindings VALUES('req','failed','issue','author')")
        config=dict(issue_id='issue',source_task='parent',author='author',cto='cto',peer='lead',
            contract_sha256='c'*64,manifest_sha256='a'*64,volume='previous',diagnostic={'test_sha256':'b'*64},
            paths=['/evidence/candidate/test.py'],criteria={'A01':'unchanged'},minimum_calls=8,
            experiment_summary={'diagnostic_copy_only':True})
        old=dict(stage='plan_qualified',executor=dict(status='blocked',task_id='failed',wakeup_id='wake'))
        old_raw=json.dumps(old)
        con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',('parent',json.dumps(config),old_raw))
        handoffs.save(con,'failed','issue','test_first_blocked','cto',dict(error='failed'),0)
        @contextmanager
        def db():yield con;con.commit()
        requests=[]
        def docker(method,path,body=None):
            requests.append((method,path))
            if path.startswith('/volumes/'):
                return {'Labels':{'delivery-kit.owner':'owned','delivery-kit.source-task':'parent' if path.endswith('previous') else 'failed',
                                  'delivery-kit.diagnostic-only':'true'}}
            return None
        b=SimpleNamespace(db=db,OWNER='owned',PREFIX='delivery-kit-test',docker=docker,
                          snapshot_submission=lambda *a,**kw:dict(volume='frozen'))
        route=dict(issue_id='issue',author='author',cto='cto',techlead='lead',enabled=True,contract_sha256='c'*64)
        source=dict(id='failed',agent_id='author',status='failed',wakeup_id='wake')
        effects=SimpleNamespace(settings={})
        payload=dict(HostConfig={'Mounts':[]},Labels={})
        with patch('broker.native.task_messages',return_value=self.messages()),patch('broker.harness_qualification.payload',return_value=payload):
            for _ in range(2):
                self.assertTrue(diagnosis.handle(b,route,[source],source,handoffs.load(con,'failed'),effects))
        self.assertEqual(sum(m=='POST' for m,p in requests),1)
        self.assertEqual(con.execute("SELECT state FROM calibration_failure_plans WHERE source_task='parent'").fetchone()[0],old_raw)
        new_config,new_state=map(json.loads,con.execute("SELECT config,state FROM calibration_failure_plans WHERE source_task='failed'").fetchone())
        self.assertEqual(new_state['stage'],'preservation_intent')
        self.assertFalse(new_state['author_retry_authorized'])
        self.assertEqual(new_config['predecessor_plan'],'parent')
        self.assertNotIn('executor',new_state)
        self.assertEqual(handoffs.load(con,'failed')['owner'],'cto')
