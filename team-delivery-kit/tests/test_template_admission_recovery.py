import copy,json,tempfile,unittest,sqlite3,threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from broker import template_admission_recovery as recovery,template_author_executor as executor,template_preservation_probe as probe


class TemplateAdmissionRecoveryTests(unittest.TestCase):
    def config(self):return dict(source_task='original',manifest_sha256='a'*64,diagnostic=dict(test_sha256='b'*64),contract_sha256='c'*64,criteria={'A01':'unchanged'},author='author')
    def state(self):
        return dict(cto_task='cto-task',peer_task='peer-task',cto_decision={'reason':'preserve pending'},peer_decision={'reason':'read terminal'},
            executor=dict(status='blocked',task_id='failed',contract_sha256='d'*64,surgical={'protocol':'typed_template_v5'},delivery_approval=False),
            binding_recovery=dict(stage='probe_pending',source_task='failed',prior_executor_sha256='d'*64,name='job',
                payload={'fixed':True},qualification=dict(worker_image='sha256:'+'e'*64)))
    def test_new_image_never_waives_current_role_contract(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        cfg={**self.config(),'issue_id':'issue','cto':'cto','peer':'peer'}
        state=self.state();state.pop('binding_recovery');state['stage']='plan_qualified'
        state['executor']['worker_image']='sha256:'+'d'*64
        proof=dict(schema='surgical-template-registry-probe-v5',status='passed',uid=10000,network='none',model_calls=0,delivery_approval=False,
            worker_image='sha256:'+'e'*64,proxy_image='sha256:'+'f'*64,**{k:True for k in executor.FLAGS})
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT,config TEXT,state TEXT)')
        con.execute('INSERT INTO calibration_failure_plans VALUES (?,?,?)',('original',json.dumps(cfg),json.dumps(state)))
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(dict(enabled=True,contract_sha256=cfg['contract_sha256'],author='author',cto='changed',techlead='peer'))))
        con.execute('CREATE TABLE template_registry_qualifications(worker_image TEXT,receipt TEXT)')
        con.execute('INSERT INTO template_registry_qualifications VALUES (?,?)',(proof['worker_image'],json.dumps(proof)))
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db,LOCK=threading.RLock(),IMAGE=proof['worker_image'])
        with self.assertRaisesRegex(ValueError,'changed native-binding admission required'):recovery.arm(b,'original',proof)
        stored=json.loads(con.execute('SELECT state FROM calibration_failure_plans').fetchone()[0])
        self.assertNotIn('binding_recovery',stored)
    def test_uncertain_job_creation_is_not_reposted(self):
        state=self.state();saved=[];calls=[]
        def docker(method,path,payload=None):
            calls.append(method)
            if method=='POST':
                self.assertEqual(saved[-1]['binding_recovery']['stage'],'probe_intent');raise TimeoutError('unknown creation')
            return None
        b=SimpleNamespace(docker=docker)
        with self.assertRaises(TimeoutError):recovery.advance(b,self.config(),state,lambda s:saved.append(copy.deepcopy(s)))
        recovery.advance(b,self.config(),saved[-1],lambda s:saved.append(copy.deepcopy(s)))
        self.assertEqual(calls.count('POST'),1)
        self.assertEqual(saved[-1]['executor'],state['executor'])
    def test_actual_immutable_job_arms_separate_executor_without_resetting_old(self):
        state=self.state();proof=dict(operation='template_admission_preservation_v1',status='passed',manifest_sha256='a'*64,test_sha256='b'*64,files=4,all_files_unchanged=True,delivery_approval=False)
        b=SimpleNamespace(docker=lambda *a:dict(Id='job-id',State=dict(Status='exited',Running=False,ExitCode=0)),docker_stdout=lambda *a,**kw:json.dumps(proof))
        # This function is independently covered against full isolation payloads.
        with patch('broker.harness_qualification.verify_job') as verify:
            result=recovery.advance(b,self.config(),state,lambda s:None)
            verify.assert_called_once()
        self.assertEqual(result['executor'],state['executor'])
        active=executor.selected_executor(result)
        self.assertEqual(active['status'],'ready');self.assertEqual(active['attempt_limit'],1)
        self.assertFalse(active['delivery_approval'])
        self.assertNotEqual(executor.marker(self.config(),result),executor.marker(self.config(),state))
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT,config TEXT,state TEXT)')
        cfg={**self.config(),'issue_id':'issue'}
        result['binding_recovery']['executor'].update(status='waiting',wakeup_id='new-wake')
        con.execute('INSERT INTO calibration_failure_plans VALUES (?,?,?)',('original',json.dumps(cfg),json.dumps(result)))
        @contextmanager
        def db():yield con
        task=dict(id='new-author',issue_id='issue',agent_id='author',status='running',wakeup_id='new-wake')
        self.assertEqual(executor.for_task(SimpleNamespace(db=db),'issue',task)['worker_image'],active['worker_image'])
        with self.assertRaises(ValueError):executor.for_task(SimpleNamespace(db=db),'issue',{**task,'wakeup_id':'old-wake'})
        for key,value in [('manifest_sha256','f'*64),('all_files_unchanged',False),('delivery_approval',True),('test_sha256','f'*64)]:
            with self.assertRaises(ValueError):recovery.validate_preservation({**proof,key:value},self.config())
    def test_scope_requires_two_real_denials_not_agent_claims(self):
        result='patch failed for /workspace/tests/test_service_mode_indicator.py: surgical_edit_rejected:operation_forbidden:use_surgical_tool_only'
        ms=[dict(type='tool_use',tool='read_file'),*[dict(type='tool_use',tool='patch',call_id=str(i)) for i in range(2)],*[dict(type='tool_result',tool='patch',call_id=str(i),output=result) for i in range(2)]]
        recovery.validate_rejections(ms)
        for variant in [ms[:-1],ms+[dict(type='tool_use',tool='terminal')],ms+[dict(type='tool_use',tool='patch')], [{**m,'output':'agent says write denied'} if m['type']=='tool_result' else m for m in ms]]:
            with self.assertRaises(ValueError):recovery.validate_rejections(variant)
    def test_probe_verifies_every_file_and_inventory_not_only_target_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            roots=[Path(directory)/s for s in ('old','new')]
            for root in roots:
                (root/'tests').mkdir(parents=True)
                (root/'tests/test_service_mode_indicator.py').write_text('test bytes')
                (root/'app.js').write_text('product bytes')
                files={name:dict(sha256=hashlib.sha256((root/name).read_bytes()).hexdigest(),bytes=(root/name).stat().st_size) for name in ('app.js','tests/test_service_mode_indicator.py')}
                (root/'manifest.json').write_text(json.dumps(dict(files=files),sort_keys=True))
            self.assertTrue(probe.compare(*roots)['all_files_unchanged'])
            (roots[1]/'app.js').write_text('different product')
            with self.assertRaises(ValueError):probe.compare(*roots)
