import copy,hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import template_failure_diagnosis as diagnosis,calibration_rework as lane,handoffs


class TemplateFailureDiagnosisTests(unittest.TestCase):
    def test_archive_checks_private_files_actual_ledger_and_observation_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            b=SimpleNamespace(STATE=Path(root),IMAGE='sha256:'+'a'*64)
            directory=b.STATE/'startup333-network-default-qualified';directory.mkdir(mode=0o700)
            receipt=directory/'probe-receipt.json';database=directory/'leases.sqlite'
            proof=self.infrastructure_proof()
            proof.update(controller_sha256=hashlib.sha256(b'controller').hexdigest(),
                         policy_source_sha256=hashlib.sha256(b'policy').hexdigest())
            receipt.write_text(json.dumps(proof));receipt.chmod(0o600)
            fact=dict(request_id='fixture',worker_image=b.IMAGE,normalized_differences=[],
                delivery_approval=False,author_retry_authorized=False,docker_status='running',omitted_false_network_flag=True)
            raw=json.dumps(fact,sort_keys=True)
            with sqlite3.connect(database) as con:
                con.executescript("CREATE TABLE grants(request_id TEXT,used INTEGER,mode TEXT); INSERT INTO grants VALUES('fixture',1,'planning');"
                    "CREATE TABLE leases(status TEXT); INSERT INTO leases VALUES('closed');"
                    "CREATE TABLE acp_events(method TEXT,success INTEGER); INSERT INTO acp_events VALUES('initialize',1);"
                    "CREATE TABLE acp_sessions(session_id TEXT); CREATE TABLE worker_retirement_intents(state TEXT); INSERT INTO worker_retirement_intents VALUES('gone');"
                    "CREATE TABLE worker_policy_observations(request_id TEXT,receipt_sha256 TEXT,receipt TEXT);")
                con.execute('INSERT INTO worker_policy_observations VALUES(?,?,?)',('fixture',hashlib.sha256(raw.encode()).hexdigest(),raw))
            database.chmod(0o600)
            with patch.object(Path,'read_bytes',autospec=True,side_effect=lambda path:b'controller' if str(path)=='/broker.py' else b'policy'):
                self.assertEqual(diagnosis.infrastructure_archive(b,directory.name),proof)
                for name in ('../escape','startup-qualified','/tmp/fixture'):
                    with self.assertRaises(ValueError):diagnosis.infrastructure_archive(b,name)
                receipt.chmod(0o644)
                with self.assertRaises(ValueError):diagnosis.infrastructure_archive(b,directory.name)
                receipt.chmod(0o600)
                with sqlite3.connect(database) as con:con.execute("UPDATE worker_policy_observations SET receipt_sha256='bad'")
                with self.assertRaises(ValueError):diagnosis.infrastructure_archive(b,directory.name)

    def infrastructure_proof(self):
        return dict(schema='async-startup-integration-probe-v1',status='passed',
            worker_image='sha256:'+'a'*64,controller_sha256='b'*64,policy_source_sha256='c'*64,
            native_identity='disposable_fixture_not_real_multica',lease_status='closed',worker_network='none',
            delivery_approval=False,capability_consumptions=1,model_calls=0,prompts_sent=0,sessions_created=0,
            operations={'create':1,'start':1,'exec':1},**{k:True for k in
                ('installed_controller_code','actual_broker_http','actual_wrapper','actual_docker','actual_acp_transport',
                 'actual_hermes_initialize','lost_create_ack_observed','retirement_observed','network_default_policy',
                 'durable_policy_observations','observed_omitted_false','worker_socket_absent')})

    def test_qualified_new_diagnosis_never_reconstructs_missing_old_inspection(self):
        config=dict(bootstrap_failure={'operation':'worker_bootstrap_failure_v1'},source_task='source',
            manifest_sha256='a'*64,cto='cto',issue_id='issue')
        state=dict(stage='blocked',category='surgical_failure_diagnosis_rejected',cto_wakeup='wake',probe={'preserved':True})
        task=dict(id='failed',status='failed',agent_id='cto',issue_id='issue',wakeup_id='wake')
        payload=dict(Image='sha256:'+'a'*64,NetworkDisabled=False)
        intent=dict(stage='ownership_or_policy_conflict');startup=dict(stage='failed',category='startup_broker_internal')
        retired=dict(container_id='d'*64,name='original-worker',state='gone')
        proof=self.infrastructure_proof();before=copy.deepcopy((config,state))
        changed,new=diagnosis.recover_retired_planner(config,state,task,payload,intent,startup,retired,proof,0,0)
        self.assertEqual((config,state),before)
        self.assertEqual(new['stage'],'cto_pending');self.assertNotIn('executor',new)
        self.assertNotEqual(lane.marker(config,'cto'),lane.marker(changed,'cto'))
        receipt=new['bootstrap_policy_recovery']
        self.assertTrue(receipt['original_inspection_missing']);self.assertFalse(receipt['original_cause_confirmed'])
        self.assertFalse(receipt['transport_replayed']);self.assertFalse(receipt['author_retry_authorized'])
        self.assertFalse(receipt['delivery_approval']);self.assertIn('old cause remains unproved',changed['bootstrap_infrastructure_note'])
        for updates in ({'model_calls':1},{'retirement_observed':False},{'durable_policy_observations':False},
                        {'operations':{'create':2,'start':1,'exec':1}},{'delivery_approval':True},
                        {'controller_sha256':None}):
            with self.assertRaises(ValueError):diagnosis.recover_retired_planner(config,state,task,payload,intent,startup,retired,{**proof,**updates},0,0)
        for c,s,t,r,tools,acp in ((changed,new,task,retired,0,0),
                (config,state,{**task,'agent_id':'author'},retired,0,0),
                (config,state,task,{**retired,'state':'delete_intent'},0,0),
                (config,state,task,retired,1,0),(config,state,task,retired,0,1)):
            with self.assertRaises(ValueError):diagnosis.recover_retired_planner(c,s,t,payload,intent,startup,r,proof,tools,acp)

    def test_infrastructure_proof_requires_exact_installed_source_and_worker(self):
        proof=self.infrastructure_proof()
        diagnosis.validate_infrastructure_probe(proof,'sha256:'+'a'*64,'b'*64,'c'*64)
        for worker,controller,policy in (('sha256:'+'f'*64,'b'*64,'c'*64),
                ('sha256:'+'a'*64,'f'*64,'c'*64),('sha256:'+'a'*64,'b'*64,'f'*64)):
            with self.assertRaises(ValueError):diagnosis.validate_infrastructure_probe(proof,worker,controller,policy)
    def test_omitted_false_CTO_recovery_is_once_only_not_transport_or_author_replay(self):
        from tests.test_worker_creation_intent import WorkerCreationIntentTests
        payload,_,info=WorkerCreationIntentTests().inputs()
        info['Config'].pop('NetworkDisabled')
        config=dict(bootstrap_failure={'operation':'worker_bootstrap_failure_v1'},source_task='source',
            manifest_sha256='a'*64,cto='cto',issue_id='issue')
        state=dict(stage='blocked',category='surgical_failure_diagnosis_rejected',cto_wakeup='wake',
            probe={'immutable':'preserved'})
        task=dict(id='task',status='failed',agent_id='cto',issue_id='issue',wakeup_id='wake')
        intent=dict(stage='ownership_or_policy_conflict')
        startup=dict(stage='failed',category='startup_broker_internal')
        before=copy.deepcopy((config,state))
        changed,new=diagnosis.recover_network_default(config,state,task,payload,intent,startup,info,0,0)
        self.assertEqual((config,state),before)
        self.assertEqual(new['stage'],'bootstrap_retirement_pending')
        self.assertNotIn('cto_wakeup',new);self.assertNotIn('executor',new)
        self.assertEqual(new['bootstrap_policy_recovery']['previous_state'],state)
        self.assertFalse(new['bootstrap_policy_recovery']['transport_replayed'])
        self.assertNotEqual(lane.marker(config,'cto'),lane.marker(changed,'cto'))
        for c,s,t,p,i,st,inf,tools,events in (
            (changed,new,task,payload,intent,startup,info,0,0),
            (config,state,{**task,'status':'running'},payload,intent,startup,info,0,0),
            (config,state,{**task,'agent_id':'author'},payload,intent,startup,info,0,0),
            (config,{**state,'peer_wakeup':'peer'},task,payload,intent,startup,info,0,0),
            (config,state,task,payload,intent,{**startup,'stage':'ready'},info,0,0),
            (config,state,task,payload,intent,startup,info,1,0),
            (config,state,task,payload,intent,startup,info,0,1),
            (config,state,task,{**payload,'NetworkDisabled':True},intent,startup,info,0,0),
            (config,state,task,payload,intent,startup,{**info,'Image':'wrong'},0,0)):
            with self.assertRaises(ValueError):diagnosis.recover_network_default(c,s,t,p,i,st,inf,tools,events)

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
            config['bootstrap_infrastructure_note']='Original CTO inspection missing; old cause remains unproved. Installed zero-model Docker/ACP probe passed. Perform new read-only diagnosis, not a replay or delivery approval. Infrastructure proof SHA256='+'a'*64
            fresh=lane.instruction(config,state)
            self.assertLessEqual(len(fresh)+100,4000);self.assertIn('old cause remains unproved',fresh)

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
