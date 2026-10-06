import unittest
import hashlib
import json
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import Mock
from broker.test_decomposition import advance, validate_result


class DecompositionTests(unittest.TestCase):
    def setUp(self):
        self.config={'source_task':'source','issue_id':'issue','cto':'cto','author':'author',
            'required_files':['app/static/app.js','tests/test_new.py'],
            'criteria':{'C01':'Search control','C02':'Independent queries'},
            'diagnostic_sha256':'a'*64,'diagnostic':{'category':'new_test_no_methods'}}
        self.task={'id':'new-cto','agent_id':'cto','status':'completed','wakeup_id':'wake'}
        self.reads={'/evidence/candidate/'+p:{'lines':10,'total_lines':10}
                    for p in self.config['required_files']}
        self.decision={'action':'propose_test_decomposition','reason':'Reuse the existing DOM harness incrementally.',
            'optional_files':[], 'units':[
                {'id':'U1','depends_on':[],'criteria':['C01'],'objective':'One real search input assertion.'},
                {'id':'U2','depends_on':['U1'],'criteria':['C02'],'objective':'Independent query state.'}]}
        self.effects=SimpleNamespace(ensure_wakeup=Mock(return_value={'id':'wake'}),
            remaining_calls=Mock(return_value=120),decomposition_proposal=Mock(return_value=self.decision),
            read_evidence=Mock(return_value=self.reads))

    def test_source_bound_plan_never_grants_execution_or_approval(self):
        state=advance(self.config,{'stage':'pending'},[],self.effects,now=1)
        state=advance(self.config,state,[self.task],self.effects,now=2)
        self.assertEqual(state['stage'],'proposal_ready')
        self.assertFalse(state['certificate']['execution_authorized'])
        self.assertFalse(state['certificate']['delivery_approval'])
        self.assertEqual(advance(self.config,state,[self.task],self.effects,now=3),state)
        self.effects.ensure_wakeup.assert_called_once()

    def test_missing_scope_duplicate_ids_forward_dependencies_and_unknown_criteria_rejected(self):
        import copy
        for kind in ('missing','duplicate','forward','unknown'):
            d=copy.deepcopy(self.decision)
            if kind=='missing':d['units'].pop()
            if kind=='duplicate':d['units'][1]['id']='U1'
            if kind=='forward':d['units'][0]['depends_on']=['U2']
            if kind=='unknown':d['units'][1]['criteria']=['C03']
            with self.assertRaises(ValueError):validate_result(self.config,self.task,d,self.reads)

    def test_incomplete_reads_other_agent_and_textual_completion_cannot_qualify(self):
        for task,decision,reads in [({**self.task,'agent_id':'author'},self.decision,self.reads),
                                   (self.task,{'action':'done'},self.reads),
                                   (self.task,self.decision,{})]:
            with self.assertRaises(ValueError):validate_result(self.config,task,decision,reads)

    def test_deadline_or_failed_decision_stays_visible_without_new_attempt(self):
        state=advance(self.config,{'stage':'pending'},[],self.effects,now=1)
        failed=advance(self.config,state,[],self.effects,now=1802)
        self.assertEqual(failed['stage'],'blocked')
        self.assertEqual(advance(self.config,failed,[],self.effects,now=1803),failed)
        self.effects.ensure_wakeup.assert_called_once()

    def test_budget_wait_does_not_claim_dispatch(self):
        self.effects.remaining_calls.return_value=7
        self.effects.ensure_wakeup.return_value=None
        state=advance(self.config,{'stage':'pending'},[],self.effects,now=1)
        self.assertNotIn('wakeup_id',state)
        self.assertFalse(self.effects.ensure_wakeup.call_args.kwargs['allow_create'])

    def test_proxy_requires_reads_then_bounded_proposal_for_exact_criterion_ids(self):
        from decision_schema import apply
        import json
        path='/evidence/candidate/tests/test_new.py'
        messages=[{'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:technical\n'
            'DELIVERY_TEST_DECOMPOSITION_V1\nDELIVERY_DECOMPOSITION_CRITERION:C01\n'
            'DELIVERY_DECOMPOSITION_CRITERION:C02\nDELIVERY_REVIEW_READ_PATH:'+path+'\n'}]
        body=apply({'messages':list(messages),'tools':[{'function':{'name':'read_file'}}]})
        self.assertNotIn('response_format',body)
        messages += [{'role':'assistant','tool_calls':[{'id':'read1','function':{
            'name':'read_file','arguments':json.dumps({'path':path})}}]},
            {'role':'tool','tool_call_id':'read1','content':json.dumps({'content':'1|def helper(): pass','total_lines':1})}]
        body=apply({'messages':messages})
        properties=body['response_format']['json_schema']['schema']['properties']
        self.assertEqual(body['tool_choice'],'none')
        self.assertEqual(properties['action']['enum'],['propose_test_decomposition','escalate_cto'])
        self.assertEqual(properties['units']['maxItems'],4)
        self.assertEqual(properties['units']['items']['properties']['criteria']['items']['enum'],['C01','C02'])

    def test_proposal_parser_is_separate_from_general_decision_authority(self):
        import json
        from broker.test_decomposition import parse_proposal
        self.assertEqual(parse_proposal({'result':{'output':json.dumps(self.decision)}},[]),self.decision)
        for output in ('done','[]','x'*6001):
            with self.assertRaises(ValueError):parse_proposal({'result':{'output':output}},[])

    def test_real_diagnostic_probe_requires_readonly_complete_transport(self):
        from broker.test_decomposition import validate_probe
        from model_policy import MODEL
        proof={'schema':'acp-decomposition-probe-v1','status':'passed','model':MODEL,
            'worker_image':'sha256:'+'a'*64,'proxy_image':'sha256:'+'b'*64,
            'execution_id':'11111111-1111-4111-8111-111111111111',
            'delivery_approval':False,'product_retry':False,'prompt_completed':True,
            'full_reads_verified':True,'proposal_valid':True,'unit_count':2,
            'proposal_sha256':'c'*64,'fixture_unchanged':True,'fixture_removed':True,
            'inspection':{'uid':10000,'syntax_valid':True,'baseline_unchanged':True,
                          'credentials_absent':True,'bytes':23,
                          'sha256':'5e41ba724966db023c31ce32089f0ef752e3a33131c12af74856ce99b32b0504'}}
        validate_probe(proof,proof['worker_image'])
        for key,value in [('full_reads_verified',False),('fixture_removed',False),
                          ('delivery_approval',True),('schema','acp-artifact-probe-v1')]:
            with self.assertRaises(ValueError):validate_probe({**proof,key:value},proof['worker_image'])
        with self.assertRaises(ValueError):validate_probe(proof,'sha256:'+'d'*64)

    def test_repaired_diagnostic_uses_new_marker_without_author_dispatch(self):
        original=advance(self.config,{'stage':'pending'},[],self.effects,now=1)
        old_marker=self.effects.ensure_wakeup.call_args.args[3]
        repair={'stage':'pending','transport_repair':{'previous_rejection':original}}
        state=advance(self.config,repair,[],self.effects,now=2)
        self.assertNotEqual(old_marker,self.effects.ensure_wakeup.call_args.args[3])
        self.assertEqual(self.effects.ensure_wakeup.call_args.args[1],'cto')
        self.assertIn('transport_repair',state)

    def test_pre_dispatch_context_block_can_resume_without_resetting_an_execution(self):
        before={'stage':'blocked','category':'decomposition_context_too_large','reader_repair':{'receipt':True}}
        state=advance(self.config,before,[],self.effects,now=1)
        self.assertEqual(state['stage'],'pending');self.assertEqual(state['wakeup_id'],'wake')
        self.assertTrue(state['pre_dispatch_failure']['no_execution_dispatched'])
        self.assertEqual(state['reader_repair'],before['reader_repair'])
        for extra in ({'wakeup_id':'already-dispatched'},{'task_id':'ran'}):
            frozen={**before,**extra}
            self.assertEqual(advance(self.config,frozen,[],self.effects,now=2),frozen)

    def test_v2_allocates_every_criterion_without_inventing_missing_decisions(self):
        import copy
        config={**self.config,'proposal_contract':'criterion-allocation-v2'}
        decision=copy.deepcopy(self.decision)
        for unit in decision['units']:unit.pop('criteria')
        decision['assignments']={'C01':'U1','C02':'U2'}
        proof=validate_result(config,self.task,decision,self.reads)
        self.assertEqual(proof['allocated_criteria_count'],2)
        self.assertEqual(proof['normalized_units'],self.decision['units'])
        self.assertFalse(proof['execution_authorized'])
        self.assertEqual(set(decision['units'][0]),{'id','depends_on','objective'})
        for assignments in ({'C01':'U1'},{'C01':'U1','C02':'U2','C03':'U2'},
                            {'C01':'U1','C02':'U4'},{'C01':'U1','C02':'U1'},
                            {'C01':['U1'],'C02':'U2'}):
            with self.assertRaises(ValueError):validate_result(config,self.task,{**decision,'assignments':assignments},self.reads)
        with self.assertRaises(ValueError):validate_result(config,self.task,self.decision,self.reads)

    def test_v2_schema_requires_all_22_assignments_and_keeps_v1_unchanged(self):
        from decision_schema import apply
        criteria=['C'+str(i).zfill(2) for i in range(1,23)]
        marker='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TEST_DECOMPOSITION_V2\n'
        marker+=''.join('DELIVERY_DECOMPOSITION_CRITERION:'+c+'\n' for c in criteria)
        body=apply({'messages':[{'role':'user','content':marker}]})
        schema=body['response_format']['json_schema']['schema']
        assignments=schema['properties']['assignments']
        self.assertEqual(assignments['required'],criteria)
        self.assertEqual(set(assignments['properties']),set(criteria))
        self.assertFalse(assignments['additionalProperties'])
        self.assertIn('assignments',schema['required'])
        self.assertNotIn('criteria',schema['properties']['units']['items']['properties'])
        with self.assertRaisesRegex(ValueError,'conflicting decomposition'):
            apply({'messages':[{'role':'user','content':marker+'DELIVERY_TEST_DECOMPOSITION_V1\n'}]})

    def test_v2_wakeup_is_bounded_and_has_a_distinct_versioned_marker(self):
        old=advance(self.config,{'stage':'pending'},[],self.effects,now=1)
        marker=self.effects.ensure_wakeup.call_args.args[3]
        state=advance(self.config,{'stage':'pending','proposal_contract':'criterion-allocation-v2'},[],self.effects,now=2)
        call=self.effects.ensure_wakeup.call_args
        self.assertNotEqual(marker,call.args[3]);self.assertLess(len(call.args[4]),3900)
        self.assertIn('DELIVERY_TEST_DECOMPOSITION_V2',call.args[4])
        self.assertEqual(state['proposal_contract'],'criterion-allocation-v2')


class DiagnosticRepairTests(unittest.TestCase):
    def setUp(self):
        from test_test_artifact_recovery import ArtifactRecoveryTests
        from broker import handoffs,test_decomposition as d
        from model_policy import MODEL
        f=ArtifactRecoveryTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.b=f.b
        self.b.PREFIX='delivery-kit-port2';self.image='sha256:'+'b'*64
        self.b.docker=lambda *_:{'Image':self.image,'State':{'Running':True},
            'Config':{'Labels':{'com.docker.compose.project':self.b.PREFIX}}}
        self.snapshot={'verified':True,'baseline_unchanged':True,'task_id':f.source,'volume':'immutable','manifest_sha256':'d'*64}
        self.state={'stage':'blocked','category':'invalid_or_unread_decomposition','task_id':f.cto,'wakeup_id':'old-wake'}
        f.runs[-1]['wakeup_id']='old-wake'
        self.config={'source_task':f.source,'issue_id':f.issue,'cto':'cto','author':'author',
            'requirements_sha256':hashlib.sha256(b'Original scope.').hexdigest(),
            'diagnostic':f.diagnostic,'snapshot':self.snapshot}
        proof={'schema':'acp-decomposition-probe-v1','status':'passed','model':MODEL,'worker_image':f.b.IMAGE,
            'proxy_image':self.image,'execution_id':'44444444-4444-4444-8444-444444444444',
            'delivery_approval':False,'product_retry':False,'prompt_completed':True,'full_reads_verified':True,
            'proposal_valid':True,'unit_count':2,'proposal_sha256':'c'*64,'fixture_unchanged':True,'fixture_removed':True,
            'inspection':{'uid':10000,'bytes':23,'sha256':'5e41ba724966db023c31ce32089f0ef752e3a33131c12af74856ce99b32b0504',
                'syntax_valid':True,'baseline_unchanged':True,'credentials_absent':True}}
        self.payload={'source_task':f.source,'previous_task':f.cto,'probe':proof,'previous_proxy_image':'sha256:'+'e'*64}
        with self.b.db() as con:
            d.initialize(con);con.execute('INSERT INTO test_decompositions VALUES (?,?,?)',(f.source,json.dumps(self.config),json.dumps(self.state)))
            handoffs.save(con,f.source,f.issue,'test_first_blocked','cto',{'diagnostic':f.diagnostic},3)

    def repair(self):
        from broker.test_decomposition import repair_transport
        with patch('broker.native.issue_task_runs',return_value=self.f.runs),patch(
                'broker.native.issue_record',return_value={'description':'Original scope.'}),patch(
                'broker.artifact_transport_recovery.verify_preserved_failure',return_value=self.snapshot):
            return repair_transport(self.b,self.payload)

    def test_repair_is_idempotent_preserves_rejection_and_never_authorizes_execution(self):
        r=self.repair();self.assertEqual(r,self.repair())
        self.assertEqual(r['previous_rejection'],self.state);self.assertFalse(r['execution_authorized'])
        self.payload['probe']['execution_id']='55555555-5555-4555-8555-555555555555'
        with self.assertRaisesRegex(ValueError,'identity drift'):self.repair()

    def test_live_worker_red_or_wrong_cto_wakeup_cannot_repair(self):
        with self.b.db() as c:c.execute('INSERT INTO leases VALUES (?)',('running',))
        with self.assertRaisesRegex(ValueError,'idle'):self.repair()
        with self.b.db() as c:c.execute('DELETE FROM leases');c.execute('INSERT INTO test_first_red VALUES (?)',(self.f.issue,))
        with self.assertRaisesRegex(ValueError,'without Red'):self.repair()
        with self.b.db() as c:c.execute('DELETE FROM test_first_red')
        self.f.runs[-1]['wakeup_id']='unrelated'
        with self.assertRaisesRegex(ValueError,'exact rejected CTO'):self.repair()

    def test_same_proxy_or_changed_snapshot_cannot_repair(self):
        self.payload['previous_proxy_image']=self.image
        with self.assertRaisesRegex(ValueError,'changed qualified'):self.repair()
        self.payload['previous_proxy_image']='sha256:'+'e'*64
        self.snapshot['manifest_sha256']='f'*64
        # config was serialized before mutating the measured fixture result.
        with self.assertRaisesRegex(ValueError,'snapshot identity drift'):self.repair()


class EofDiagnosticRepairTests(DiagnosticRepairTests):
    def setUp(self):
        super().setUp()
        old_proof=json.loads(json.dumps(self.payload['probe']))
        old_proof['worker_image']='sha256:'+'1'*64
        self.state['transport_repair']={'request':{'probe':old_proof},'previous_rejection':{'stage':'blocked'}}
        self.payload['previous_proxy_image']=self.image
        self.payload['probe'].update(schema='acp-decomposition-probe-v2',unterminated_fixture=True,
            read_contract='logical-lines-eof-v1')
        self.payload['probe']['inspection'].update(bytes=22,
            sha256='f8b2eb37b0ef6aa2351a68a11036de171473f0814e5c78ed464f824f2b47a217')
        self.config['required_files']=['tests/test_new.py']
        self.messages=[{'type':'tool_use','tool':'read_file','call_id':'r'},
            {'type':'tool_result','call_id':'r','output':'Read /evidence/candidate/tests/test_new.py — 0 total lines\n\n```python\n1|import unittest\n```'}]
        with self.b.db() as con:
            con.execute('UPDATE test_decompositions SET config=?,state=?',(json.dumps(self.config),json.dumps(self.state)))

    def repair(self):
        with patch('broker.native.task_messages',return_value=self.messages):return super().repair()

    def test_same_proxy_or_changed_snapshot_cannot_repair(self):
        self.state['transport_repair']['request']['probe']['worker_image']=self.b.IMAGE
        with self.b.db() as con:con.execute('UPDATE test_decompositions SET state=?',(json.dumps(self.state),))
        with self.assertRaisesRegex(ValueError,'changed worker'):self.repair()

    def test_eof_repair_preserves_both_rejections_and_requires_new_valid_reads(self):
        from broker.test_decomposition import eof_failure_evidence,validate_probe
        from artifact_read_evidence import observations
        receipt=self.repair()
        self.assertEqual(receipt['repair_class'],'logical_lines_eof_v1')
        self.assertEqual(receipt['previous_rejection'],self.state)
        self.assertEqual(observations(self.messages),{})
        paged=[self.messages[0],{**self.messages[-1],'output':self.messages[-1]['output'].replace(' — 0',' (from line 1, limit 100) — 0')}]
        self.assertEqual(len(eof_failure_evidence(paged,self.config['required_files'])),1)
        for messages in ([],[{**self.messages[-1],'output_truncated':True}],
                         [self.messages[0],{**self.messages[-1],'output':self.messages[-1]['output'].replace('0 total','1 total')} ]):
            with self.assertRaises(ValueError):eof_failure_evidence(messages,self.config['required_files'])
        for key,value in [('read_contract','unknown'),('unterminated_fixture',False)]:
            with self.assertRaises(ValueError):validate_probe({**self.payload['probe'],key:value},self.b.IMAGE,eof=True)


class AllocationDiagnosticRepairTests(DiagnosticRepairTests):
    def setUp(self):
        super().setUp()
        prior=json.loads(json.dumps(self.payload['probe']))
        prior.update(schema='acp-decomposition-probe-v2',unterminated_fixture=True,read_contract='logical-lines-eof-v1')
        self.state.update(transport_repair={'preserved':True},reader_repair={'request':{'probe':prior}})
        self.payload['previous_proxy_image']=self.image
        self.image='sha256:'+'2'*64
        self.payload['probe'].update(schema='acp-decomposition-probe-v3',proxy_image=self.image,
            unterminated_fixture=True,read_contract='logical-lines-eof-v1',proposal_contract='criterion-allocation-v2',
            criteria_count=22,allocated_criteria_count=22)
        self.payload['probe']['inspection'].update(bytes=22,
            sha256='f8b2eb37b0ef6aa2351a68a11036de171473f0814e5c78ed464f824f2b47a217')
        self.config.update(required_files=['tests/test_new.py'],criteria={'C01':'a','C02':'b','C03':'c'},diagnostic_sha256='a'*64)
        self.decision={'action':'propose_test_decomposition','reason':'Reuse harness','optional_files':[],
            'units':[{'id':'U1','depends_on':[],'criteria':['C01'],'objective':'a'},
                     {'id':'U2','depends_on':['U1'],'criteria':['C02'],'objective':'b'}]}
        self.reads={'/evidence/candidate/tests/test_new.py':{'lines':1,'total_lines':1}}
        with self.b.db() as con:
            con.execute('UPDATE test_decompositions SET config=?,state=?',(json.dumps(self.config),json.dumps(self.state)))

    def repair(self):
        with patch('broker.handoff_runtime.Effects.decomposition_proposal',return_value=self.decision),patch(
                'broker.handoff_runtime.Effects.read_evidence',return_value=self.reads):return super().repair()

    def test_same_proxy_or_changed_snapshot_cannot_repair(self):
        current=self.image
        self.payload['previous_proxy_image']=current
        with self.assertRaisesRegex(ValueError,'changed qualified'):self.repair()
        self.payload['previous_proxy_image']='sha256:'+'b'*64
        self.snapshot['manifest_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'snapshot identity drift'):self.repair()

    def test_only_exact_scope_rejection_can_resume_with_new_contract(self):
        from broker.test_decomposition import validate_probe
        proof=self.payload['probe']
        validate_probe(proof,self.b.IMAGE,eof=True,allocation=True)
        with self.assertRaises(ValueError):validate_probe({**proof,'allocated_criteria_count':13},self.b.IMAGE,eof=True,allocation=True)
        old=self.reads;self.reads={}
        with self.assertRaisesRegex(ValueError,'complete-read scope'):self.repair()
        self.reads=old
        receipt=self.repair()
        self.assertEqual(receipt['rejected_scope_evidence']['missing_criteria'],['C03'])
        self.assertFalse(receipt['execution_authorized'])
        with self.b.db() as c:state=json.loads(c.execute('SELECT state FROM test_decompositions').fetchone()[0])
        self.assertEqual(state['proposal_contract'],'criterion-allocation-v2')
        self.assertEqual(state['reader_repair'],self.state['reader_repair'])
        self.assertEqual(state['transport_repair'],self.state['transport_repair'])


class StreamDiagnosticRepairTests(AllocationDiagnosticRepairTests):
    def setUp(self):
        super().setUp()
        prior=json.loads(json.dumps(self.payload['probe']))
        self.state['allocation_repair']={'request':{'probe':prior}}
        self.payload['previous_proxy_image']=self.image
        self.image='sha256:'+'3'*64;self.payload['probe']['proxy_image']=self.image
        self.payload['probe']['read_stream_recovery']={'schema':'read-stream-recovery-probe-v1','status':'passed',
            'proxy_image':self.image,'transport':'real-http-synthetic-upstream','real_model_calls':0,'durable_calls':4,
            'delivery_approval':False,'product_retry':False,**{k:True for k in ('single_retry_verified','valid_response_only',
                'repeated_failure_blocked','restart_blocked','write_retry_forbidden','payload_absent','fixture_removed')}}
        self.f.runs[-1]['status']='failed'
        self.failure={'source_task':self.f.source,'previous_task':self.f.cto,
                      'proxy_image':self.payload['previous_proxy_image'],'category':'upstream_stream_error'}
        with self.b.db() as c:
            c.execute('UPDATE test_decompositions SET state=?',(json.dumps(self.state),))
            c.execute('INSERT INTO decomposition_stream_failures VALUES (?,?,?)',
                (self.f.source,self.f.cto,json.dumps(self.failure)))

    def test_same_proxy_or_changed_snapshot_cannot_repair(self):
        original=self.payload['previous_proxy_image'];self.payload['previous_proxy_image']=self.image
        with self.assertRaisesRegex(ValueError,'changed qualified'):self.repair()
        self.payload['previous_proxy_image']=original;self.snapshot['manifest_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'snapshot identity drift'):self.repair()

    def test_only_exact_scope_rejection_can_resume_with_new_contract(self):
        receipt=self.repair()
        self.assertEqual(receipt['repair_class'],'read_stream_recovery_v1')
        self.assertEqual(receipt['observed_stream_failure'],self.failure)
        with self.b.db() as c:state=json.loads(c.execute('SELECT state FROM test_decompositions').fetchone()[0])
        self.assertEqual(state['allocation_repair'],self.state['allocation_repair'])
        self.assertFalse(receipt['execution_authorized'])

    def test_missing_observed_failure_or_weakened_fault_probe_cannot_resume(self):
        with self.b.db() as c:c.execute('DELETE FROM decomposition_stream_failures')
        with self.assertRaisesRegex(ValueError,'observed failed stream'):self.repair()
        self.payload['probe']['read_stream_recovery']['restart_blocked']=False
        with self.assertRaisesRegex(ValueError,'HTTP stream recovery proof'):self.repair()

    def test_capture_requires_correlated_failed_planning_with_no_tools(self):
        from broker.test_decomposition import capture_stream_failure
        execution='66666666-6666-4666-8666-666666666666'
        self.b.docker=lambda *_:{'Image':self.payload['previous_proxy_image'],
            'Config':{'Labels':{'com.docker.compose.project':self.b.PREFIX}}}
        event={'event':'model_proxy_request','execution_id':execution,'status':502,
               'artifact_rejection_category':'upstream_stream_error','call_number':10}
        self.b.docker_stdout=lambda *a,**kw:json.dumps(event)
        with self.b.db() as c:
            c.execute('DELETE FROM decomposition_stream_failures');c.execute('ALTER TABLE leases ADD COLUMN request_id TEXT')
            c.execute('CREATE TABLE grants(request_id TEXT,mode TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT)')
            c.execute('INSERT INTO leases VALUES (?,?)',('closed',execution))
            c.execute('INSERT INTO grants VALUES (?,?)',(execution,'planning'))
            c.execute('INSERT INTO native_bindings VALUES (?,?)',(execution,self.f.cto))
        payload={'source_task':self.f.source,'previous_task':self.f.cto}
        task={'id':self.f.cto,'status':'failed','wakeup_id':'old-wake'}
        with patch('broker.native.task_record',return_value=task),patch('broker.native.task_messages',return_value=[]):
            receipt=capture_stream_failure(self.b,payload)
            self.assertEqual(receipt,capture_stream_failure(self.b,payload))
            self.assertEqual(receipt['call_number'],10)
        with self.b.db() as c:c.execute('DELETE FROM decomposition_stream_failures')
        with patch('broker.native.task_record',return_value={**task,'status':'completed'}):
            with self.assertRaisesRegex(ValueError,'failed stream wakeup'):capture_stream_failure(self.b,payload)
        with patch('broker.native.task_record',return_value=task),patch('broker.native.task_messages',return_value=[{'type':'tool_use'}]):
            with self.assertRaisesRegex(ValueError,'zero tool'):capture_stream_failure(self.b,payload)

    def test_deterministic_read_repair_requires_actual_native_reads_not_dispatch_claims(self):
        from broker.test_decomposition import validate_probe
        p=self.payload['probe']
        p.update(schema='acp-decomposition-probe-v4',deterministic_reads=True,controller_read_requests=3,
                 decision_model_calls=1,dispatch_provenance='controller_request_not_read_evidence')
        validate_probe(p,self.b.IMAGE,eof=True,allocation=True,deterministic=True)
        for key,value in [('full_reads_verified',False),('controller_read_requests',0),('decision_model_calls',4),
                          ('dispatch_provenance','model_read_evidence')]:
            with self.assertRaises(ValueError):validate_probe({**p,key:value},self.b.IMAGE,eof=True,allocation=True,deterministic=True)
        receipt=self.repair();self.assertFalse(receipt['execution_authorized'])
        with self.b.db() as c:state=json.loads(c.execute('SELECT state FROM test_decompositions').fetchone()[0])
        self.assertTrue(state['deterministic_reads']);self.assertEqual(state['proposal_contract'],'criterion-allocation-v2')
