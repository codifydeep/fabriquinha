import copy,json,unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import template_author_executor as executor,template_line_replan as replan,calibration_rework as lane


class TemplateLineReplanTests(unittest.TestCase):
    def qualification(self):
        registry=dict(schema='surgical-template-line-registry-probe-v6',status='passed',uid=10000,network='none',model_calls=0,delivery_approval=False)
        registry.update({k:True for k in executor.FLAGS+('line_range_atomic_rejection','legacy_payload_denied')})
        proxy=dict(schema='template-line-proxy-image-probe-v6',status='passed',model_calls=0,delivery_approval=False,
            source_sha256={'surgical_test_edit.py':'a'*64,'test_artifact_schema.py':'b'*64})
        proxy.update({k:True for k in ('actual_proxy_request_validation','actual_response_validation','legacy_payload_denied','mixed_protocol_denied','path_and_hash_mismatch_denied')})
        return dict(schema='template-lines-v6-image-qualification-v1',status='passed',delivery_approval=False,
            worker_image='sha256:'+'a'*64,proxy_image='sha256:'+'b'*64,registry=registry,proxy=proxy)

    def inputs(self):
        cfg=dict(source_task='failed-author',issue_id='issue',author='author',cto='cto',peer='peer',diagnosis_only=True,
            execution_failure=dict(results=[{'category':'file_size_exceeded'},{'category':'replacement_not_unique_or_bounded'}]),
            manifest_sha256='a'*64,diagnostic=dict(test_sha256='b'*64),criteria=['A01'],paths=['/evidence/candidate/test.py'],
            experiment_summary=dict(hypothesis='fresh_terminal_observation_after_async_settlement',original_failures=2,
                variant_positive_tests=15,variant_negative_controls=12,diagnostic_copy_only=True))
        held=dict(stage='blocked',category='calibration_technical_impediment',owner='cto',cto_task='old-cto',cto_wakeup='old-wake',
            cto_decision=dict(action='escalate_cto',reason='Need bounded experiment.'),delivery_approval=False,
            probe=dict(proof=dict(all_files_unchanged=True,manifest_sha256='a'*64,test_sha256='b'*64,test_bytes=32674,
                file_limit_bytes=32768,available_growth_bytes=94)))
        proof=dict(operation='template_line_recipe_feasibility_v1',status='prepared',original_manifest_sha256='a'*64,
            original_test_sha256='b'*64,variant_test_sha256='c'*64,exact_experiment_variant=True,inputs_unchanged=True,
            diagnostic_only=True,valid_red_green_receipt=False,author_retry_authorized=False,delivery_approval=False,
            file_bytes=32674,proposed_bytes=32671,growth_bytes=-3,file_limit_bytes=32768,available_growth_bytes=94,
            recipe=dict(expected_sha256='b'*64,edits=[dict(start_line=476,end_line=476,new='const after_ok = modeText();\n')]))
        return cfg,held,proof,self.qualification()

    def test_replan_archives_verbatim_and_requires_new_independent_decisions(self):
        inputs=self.inputs();before=copy.deepcopy(inputs)
        cfg,held=replan.prepare(*inputs)
        self.assertEqual(inputs,before)
        self.assertEqual(held['stage'],'cto_pending')
        self.assertNotIn('cto_decision',held);self.assertNotIn('cto_wakeup',held)
        self.assertEqual(held['line_recipe_reconciliation']['previous_state'],inputs[1])
        self.assertFalse(held['author_retry_authorized']);self.assertFalse(held['delivery_approval'])
        self.assertNotIn('executor',held)
        self.assertNotEqual(lane.marker(cfg,'cto'),lane.marker(inputs[0],'cto'))
        note=lane.instruction(cfg,held)
        self.assertIn('DELIVERY_TEMPLATE_LINES_V6_REPLAN',note)
        self.assertIn('growth_bytes=-3',note)
        peer_note=lane.instruction(cfg,{**held,'stage':'peer_pending','cto_decision':dict(action='request_test_revision',reason='Minimal observation.')})
        self.assertIn('Independent Tech Lead',peer_note)
        self.assertLess(len(peer_note)+100,4000)
        cfg['criteria']=['A%02d'%i for i in range(1,9)]
        cfg['paths']=['/evidence/candidate/tests/test_service_mode_indicator.py','/evidence/candidate/app.js']
        cfg['empirical_failure']=dict(phase='positive_reference',failed_methods=['test_exact_demo_object_yields_demo_environment','test_indicator_text_constants_are_exact'])
        worst=lane.instruction(cfg,{**held,'stage':'peer_pending','cto_decision':dict(action='request_test_revision',reason='x'*1200,optional_files=[])})
        self.assertLess(len(worst)+100,4000)
        with self.assertRaises(ValueError):replan.prepare(cfg,held,inputs[2],inputs[3])

    def test_wrong_identity_approval_size_protocol_or_receipt_cannot_reopen_hold(self):
        for section,key,value in [(0,'line_recipe_revision',1),(0,'author','cto'),(1,'category','different'),
            (1,'executor',{'status':'blocked'}),(1,'owner','CEO'),(2,'original_manifest_sha256','d'*64),
            (2,'original_test_sha256','d'*64),(2,'delivery_approval',True),(2,'inputs_unchanged',False),
            (2,'growth_bytes',100),(2,'file_limit_bytes',65536),(2,'proposed_bytes',True),
            (3,'schema','surgical-template-registry-probe-v5')]:
            items=list(self.inputs());items[section][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):replan.prepare(*items)
        items=list(self.inputs());items[2]['recipe']['edits'][0]['old']='legacy'
        with self.assertRaises(ValueError):replan.prepare(*items)

    def test_v6_qualification_requires_all_actual_registry_and_proxy_fences(self):
        proof=self.qualification();executor.validate_line_qualification(proof)
        with self.assertRaises(ValueError):executor.validate_qualification(proof)
        for section,key in [('registry','native_binding_prompt'),('registry','line_range_atomic_rejection'),
                            ('registry','direct_handler_fenced'),('proxy','mixed_protocol_denied')]:
            bad=copy.deepcopy(proof);bad[section][key]=False
            with self.subTest(key=key),self.assertRaises(ValueError):executor.validate_line_qualification(bad)

    def test_supervisor_admission_is_only_after_a_new_line_plan_and_delegates_all_gates(self):
        cfg,held,proof,qualification=self.inputs();cfg,state=replan.prepare(cfg,held,proof,qualification)
        class Cursor:
            def fetchone(self):return (json.dumps(qualification),)
        @contextmanager
        def db():yield SimpleNamespace(execute=lambda *a:Cursor())
        b=SimpleNamespace(db=db,IMAGE=qualification['worker_image'])
        with patch.object(executor,'arm',return_value={'status':'ready'}) as admit:
            self.assertIsNone(executor.admit_line_plan(b,cfg,state));admit.assert_not_called()
            ready={**state,'stage':'plan_qualified'}
            self.assertEqual(executor.admit_line_plan(b,cfg,ready),{'status':'ready'})
            admit.assert_called_once_with(b,cfg['source_task'],qualification)
            self.assertIsNone(executor.admit_line_plan(b,cfg,{**ready,'executor':{'status':'blocked'}}))
            self.assertIsNone(executor.admit_line_plan(b,{k:v for k,v in cfg.items() if k!='line_recipe_revision'},ready))

    def test_fixed_job_never_accepts_an_arbitrary_command_or_writable_snapshot(self):
        cfg,_,_,qualification=self.inputs();cfg['volume']='owned-frozen-volume'
        image=qualification['worker_image']
        b=SimpleNamespace(IMAGE=image,OWNER='owner',docker=lambda *a:{'Id':image,'Config':{'Env':[]}})
        payload=replan.job_payload(b,cfg,'c'*64)
        self.assertEqual(payload['Cmd'],['/template_line_recipe_probe.py','/delivery',cfg['manifest_sha256'],'c'*64])
        self.assertTrue(payload['NetworkDisabled']);self.assertTrue(payload['HostConfig']['ReadonlyRootfs'])
        self.assertTrue(all(m['ReadOnly'] for m in payload['HostConfig']['Mounts']))
        self.assertNotIn('/var/run/docker.sock',str(payload))
        with self.assertRaises(ValueError):replan.job_payload(b,cfg,'arbitrary shell')
        with self.assertRaises(ValueError):replan.arm(b,'source','invalid-container')
