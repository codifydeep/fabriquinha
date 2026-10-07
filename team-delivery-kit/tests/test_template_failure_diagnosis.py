import copy,json,sqlite3,unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import template_failure_diagnosis as diagnosis,calibration_rework as lane,handoffs


class TemplateFailureDiagnosisTests(unittest.TestCase):
    def bootstrap_fixture(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        con.executescript("""
            CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT,agent_id TEXT);
            CREATE TABLE grants(request_id TEXT,used INTEGER,mode TEXT);
            CREATE TABLE leases(request_id TEXT,name TEXT,status TEXT);
            CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT);
            CREATE TABLE acp_events(request_id TEXT);
            INSERT INTO native_bindings VALUES('req','failed','issue','author');
            INSERT INTO grants VALUES('req',1,'implementation');
            INSERT INTO leases VALUES('req','worker','failed');
            INSERT INTO broker_errors VALUES('req','worker_submit','bootstrap:docker_containers_create');
        """)
        info=dict(Id='physical-id',Image='sha256:old',ExecIDs=None,
            Config={'Labels':{'delivery-kit.owner':'owned','delivery-kit.request':'req'}},
            State={'Status':'created','Running':False,'StartedAt':'0001-01-01T00:00:00Z'})
        b=SimpleNamespace(OWNER='owned',docker=lambda *a:info)
        held={'executor':{'worker_image':'sha256:old'}}
        return con,b,held,info

    def test_bootstrap_requires_consumed_exact_never_started_worker_without_tools(self):
        con,b,held,info=self.bootstrap_fixture()
        proof=diagnosis.bootstrap_evidence(b,con,'failed','issue','author',held,[])
        self.assertEqual(proof['container_id'],'physical-id')
        self.assertFalse(proof['author_retry_authorized']);self.assertFalse(proof['delivery_approval'])
        for messages in ([{'type':'tool_use'}],[{'type':'tool_result'}]):
            with self.assertRaises(ValueError):diagnosis.bootstrap_evidence(b,con,'failed','issue','author',held,messages)
        for key,value in [('Status','exited'),('Running',True),('StartedAt','2026-10-07')]:
            changed=copy.deepcopy(info);changed['State'][key]=value;b.docker=lambda *a:changed
            with self.subTest(key=key),self.assertRaises(ValueError):diagnosis.bootstrap_evidence(b,con,'failed','issue','author',held,[])
        for key,value in [('Image','other'),('ExecIDs',['exec'])]:
            changed=copy.deepcopy(info);changed[key]=value;b.docker=lambda *a:changed
            with self.subTest(key=key),self.assertRaises(ValueError):diagnosis.bootstrap_evidence(b,con,'failed','issue','author',held,[])
        for key in ('delivery-kit.owner','delivery-kit.request'):
            changed=copy.deepcopy(info);changed['Config']['Labels'][key]='foreign';b.docker=lambda *a:changed
            with self.subTest(key=key),self.assertRaises(ValueError):diagnosis.bootstrap_evidence(b,con,'failed','issue','author',held,[])
        b.docker=lambda *a:info
        for sql in ("UPDATE grants SET used=0","UPDATE grants SET mode='review'",
                    "UPDATE leases SET status='closed'","DELETE FROM broker_errors",
                    "INSERT INTO acp_events VALUES('req')",
                    "INSERT INTO native_bindings VALUES('req','failed','issue','author')"):
            con.execute('SAVEPOINT mutation');con.execute(sql)
            with self.subTest(sql=sql),self.assertRaises(ValueError):diagnosis.bootstrap_evidence(b,con,'failed','issue','author',held,[])
            con.execute('ROLLBACK TO mutation');con.execute('RELEASE mutation')
        with self.assertRaises(ValueError):diagnosis.bootstrap_evidence(b,con,'failed','other','author',held,[])

    def test_bootstrap_planning_keeps_independent_review_and_delivery_gates(self):
        config=dict(bootstrap_failure=dict(operation='worker_bootstrap_failure_v1',worker_never_started=True,
            source_task='s'*36,request_id='r'*36,container_id='c'*64,worker_image='sha256:'+'i'*64,
            category='docker_create_ack_timeout',acp_events=0,tool_calls=0,
            author_retry_authorized=False,delivery_approval=False),
            line_recipe={'recipe':{'edits':[{'start_line':476,'end_line':476,
                'new':'    const after_ok = { text: modeText(), calls: after_ok_calls };\n'}],
                'expected_sha256':'a'*64}},
            criteria={f'A0{i}':'unchanged' for i in range(1,9)},
            paths=['/evidence/candidate/app/static/app.js','/evidence/candidate/tests/test_service_mode_indicator.py'])
        for state in (dict(stage='cto_pending'),dict(stage='peer_pending',cto_decision={
                'action':'request_test_revision','reason':'a'*1200,'optional_files':[]})):
            note=lane.instruction(config,state)
            self.assertLessEqual(len(note)+100,4000)
            for text in ('never replayed','Historical surgical denials remain historical','No author admission yet',
                         'full pinned Red','independent review','same-commit deploy/QA','DELIVERY_REVIEW_READ_PATH:'):
                self.assertIn(text,note)

    def test_bootstrap_qualification_requires_registered_exact_worker_and_live_proxy(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        b=SimpleNamespace(IMAGE='worker',PREFIX='project',docker=lambda *a:dict(Image='proxy',State={'Running':True},
            Config={'Labels':{'com.docker.compose.project':'project'}}))
        with self.assertRaises(ValueError):diagnosis.installed_line_qualification(b,con)
        con.execute('CREATE TABLE template_registry_qualifications(worker_image TEXT,receipt TEXT)')
        with self.assertRaises(ValueError):diagnosis.installed_line_qualification(b,con)
        proof=dict(worker_image='worker',proxy_image='proxy')
        con.execute('INSERT INTO template_registry_qualifications VALUES(?,?)',('worker',json.dumps(proof)))
        with patch('broker.template_author_executor.validate_line_qualification') as validate:
            self.assertEqual(diagnosis.installed_line_qualification(b,con),proof);validate.assert_called_once_with(proof)
            for proxy in (None,dict(Image='other',State={'Running':True}),dict(Image='proxy',State={'Running':False}),
                          dict(Image='proxy',State={'Running':True},Config={'Labels':{'com.docker.compose.project':'foreign'}})):
                b.docker=lambda *a:proxy
                with self.assertRaises(ValueError):diagnosis.installed_line_qualification(b,con)

    def test_reconciliation_is_once_only_same_manifest_and_keeps_previous_decisions(self):
        from tests.test_calibration_failure_plan import CalibrationFailurePlanTests
        proof=CalibrationFailurePlanTests().proof()
        identity=dict(source_task='parent',issue_id='issue',manifest_sha256='a'*64)
        experiment=dict(stage='complete',proof=proof,receipt_sha256='e'*64)
        config=dict(source_task='failed',predecessor_plan='parent',issue_id='issue',manifest_sha256='a'*64,
            diagnostic={'test_sha256':'c'*64},diagnosis_only=True,execution_failure=diagnosis.denials(self.messages()),
            experiment_summary=dict(hypothesis=proof['hypothesis'],original_failures=2,variant_positive_tests=15,
                variant_negative_controls=12,diagnostic_copy_only=True),
            criteria={f'A0{i}':'unchanged' for i in range(1,9)},
            paths=['/evidence/candidate/app/static/app.js','/evidence/candidate/tests/test_service_mode_indicator.py'])
        state=dict(stage='plan_qualified',cto_task='cto',peer_task='peer',cto_wakeup='c',peer_wakeup='p',
            cto_decision={'reason':'unsupported old theory'},peer_decision={'reason':'unsupported old theory'},
            probe={'proof':dict(all_files_unchanged=True,manifest_sha256='a'*64,test_sha256='c'*64,
                test_bytes=32674,file_limit_bytes=32768,available_growth_bytes=94)})
        original=copy.deepcopy((config,state))
        changed,new=diagnosis.reconcile(config,state,identity,experiment)
        self.assertEqual((config,state),original)
        self.assertEqual(new['evidence_reconciliation']['previous_state'],state)
        self.assertNotIn('cto_wakeup',new);self.assertNotIn('peer_decision',new)
        self.assertEqual(new['stage'],'cto_pending');self.assertFalse(new['author_retry_authorized'])
        self.assertNotEqual(lane.marker(config,'cto'),lane.marker(changed,'cto'))
        note=lane.instruction(changed,new)
        for name in proof['original']['facts']['positive']['failed_methods']:self.assertIn(name,note)
        self.assertIn('DELIVERY_EXECUTED_FAILURES_V1',note)
        peer={**new,'stage':'peer_pending','cto_decision':dict(action='request_test_revision',reason='a'*1200,optional_files=[])}
        self.assertLessEqual(len(lane.instruction(changed,peer))+100,4000)
        with self.assertRaises(ValueError):diagnosis.reconcile(changed,new,identity,experiment)
        with self.assertRaises(ValueError):diagnosis.reconcile({**config,'manifest_sha256':'x'*64},state,identity,experiment)
        with self.assertRaises(ValueError):diagnosis.reconcile(config,{**state,'executor':{'status':'ready'}},identity,experiment)

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
        self.intake_case(bootstrap=False)

    def test_bootstrap_intake_freezes_new_source_before_planning_without_replaying_author(self):
        self.intake_case(bootstrap=True)

    def intake_case(self,bootstrap):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con)
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
        con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT,agent_id TEXT)')
        con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
        con.execute('INSERT INTO leases VALUES(?,?)',('req','failed' if bootstrap else 'closed'))
        con.execute("INSERT INTO native_bindings VALUES('req','failed','issue','author')")
        config=dict(issue_id='issue',source_task='parent',author='author',cto='cto',peer='lead',
            contract_sha256='c'*64,manifest_sha256='a'*64,volume='previous',diagnostic={'test_sha256':'b'*64},
            paths=['/evidence/candidate/test.py'],criteria={'A01':'unchanged'},minimum_calls=8,
            experiment_summary={'diagnostic_copy_only':True})
        old=dict(stage='plan_qualified',executor=dict(status='blocked',task_id='failed',wakeup_id='wake'))
        if bootstrap:
            config.update(line_recipe_revision=1,line_recipe={'recipe':{'edits':[]}},line_qualification_sha256='old')
        old_raw=json.dumps(old)
        con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',('parent',json.dumps(config),old_raw))
        handoffs.save(con,'failed','issue','test_first_blocked','cto',dict(error='failed'),0)
        @contextmanager
        def db():yield con;con.commit()
        requests=[]
        captures=[]
        def snapshot(payload,diagnostic=False):
            captures.append((payload,diagnostic));return dict(volume='frozen')
        def docker(method,path,body=None):
            requests.append((method,path))
            if path.startswith('/volumes/'):
                return {'Labels':{'delivery-kit.owner':'owned','delivery-kit.source-task':'parent' if path.endswith('previous') else 'failed',
                                  'delivery-kit.diagnostic-only':'true'}}
            return None
        b=SimpleNamespace(db=db,OWNER='owned',PREFIX='delivery-kit-test',docker=docker,
                          snapshot_submission=snapshot)
        route=dict(issue_id='issue',author='author',cto='cto',techlead='lead',enabled=True,contract_sha256='c'*64)
        source=dict(id='failed',agent_id='author',status='failed',wakeup_id='wake')
        effects=SimpleNamespace(settings={})
        payload=dict(HostConfig={'Mounts':[]},Labels={})
        proof=dict(operation='worker_bootstrap_failure_v1',worker_never_started=True)
        with patch('broker.native.task_messages',return_value=[] if bootstrap else self.messages()),\
                patch('broker.harness_qualification.payload',return_value=payload),\
                patch('broker.template_failure_diagnosis.bootstrap_evidence',return_value=proof) as classify,\
                patch('broker.template_failure_diagnosis.installed_line_qualification',return_value={'worker_image':'new'}) as qualify:
            for _ in range(2):
                self.assertTrue(diagnosis.handle(b,route,[source],source,handoffs.load(con,'failed'),effects))
            self.assertEqual(classify.call_count,1 if bootstrap else 0)
            self.assertEqual(qualify.call_count,1 if bootstrap else 0)
        self.assertEqual(captures,[({'task_id':'failed'},True)])
        self.assertEqual(sum(m=='POST' for m,p in requests),1)
        self.assertEqual(con.execute("SELECT state FROM calibration_failure_plans WHERE source_task='parent'").fetchone()[0],old_raw)
        new_config,new_state=map(json.loads,con.execute("SELECT config,state FROM calibration_failure_plans WHERE source_task='failed'").fetchone())
        self.assertEqual(new_state['stage'],'preservation_intent')
        self.assertFalse(new_state['author_retry_authorized'])
        self.assertEqual(new_config['predecessor_plan'],'parent')
        self.assertNotIn('executor',new_state)
        if bootstrap:
            self.assertEqual(new_config['bootstrap_failure'],proof)
            self.assertNotEqual(new_config['line_qualification_sha256'],'old')
        self.assertEqual(handoffs.load(con,'failed')['owner'],'cto')

    def test_qualified_diagnostic_dispatches_its_admitted_executor_not_the_planner(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con)
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
        config=dict(issue_id='issue',source_task='failed',author='author',cto='cto',peer='lead',
            execution_failure={'operation':'surgical_failure_diagnosis_v1'},contract_sha256='c'*64,
            manifest_sha256='a'*64,minimum_calls=8)
        state=dict(stage='plan_qualified',peer_task='peer',cto_decision={'reason':'Fresh observation'},
            peer_decision={'reason':'No timer edit'},executor=dict(status='ready',contract_sha256='d'*64))
        con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',('failed',json.dumps(config),json.dumps(state)))
        handoffs.save(con,'failed','issue','calibration_failure_plan','cto',{},0)
        @contextmanager
        def db():yield con;con.commit()
        calls=[]
        def wake(*a,**kw):calls.append(kw['allow_create']);return None
        effects=SimpleNamespace(remaining_calls=lambda:100,implementation_available=lambda *a:True,ensure_wakeup=wake)
        route=dict(enabled=True,issue_id='issue',author='author',cto='cto',techlead='lead',contract_sha256='c'*64)
        with patch('broker.calibration_rework.advance') as planner:
            for _ in range(2):diagnosis.handle(SimpleNamespace(db=db),route,[],{'id':'failed'},handoffs.load(con,'failed'),effects)
            planner.assert_not_called()
        self.assertEqual(calls,[True,False])
        stored=json.loads(con.execute('SELECT state FROM calibration_failure_plans').fetchone()[0])
        self.assertEqual(stored['executor']['status'],'intent')
        self.assertEqual(handoffs.load(con,'failed')['owner'],'author')
