import copy
import json
import unittest
from unittest.mock import patch
from execution_context import freeze,reference,resolve
import test_remediation_r2_preparation as fixtures
from broker import remediation_product_context as context
from broker.technical_remediation_plan import digest


class RemediationProductContextTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.RemediationR2PreparationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.value=f.f.value
        original=freeze('Full original brief.\nDELIVERY_OLD_MARKER: historical only','Full original independent review.')
        self.value['context_sha256']=original['sha256']
        self.source=dict(author='author',reviewer='product-reviewer',techlead='lead',cto='cto',contract_sha256='c'*64,
                         minimum_calls=8,enabled=False,execution_context=original,review_instruction=reference(original,'review'))
        with self.b.db() as con:
            self.state=json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])
        self.state['r1_gate']['execution_contract_sha256']=digest(self.value)
        self.state['contract_sha256']=digest(self.value)
        self.command='full original suite'
        self.state['r1_runtime']=dict(test_command_sha256=digest(self.command))
        f.f.f.f.f.save(value=self.value,state=self.state)
        with self.b.db() as con:
            policy=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',('r1',)).fetchone()[0])
            policy['remediation_execution_sha256']=digest(self.value)
            con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(policy),'r1'))
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(self.source),self.value['source_issue']))
            con.execute('CREATE TABLE issue_test_commands(issue_id TEXT,command TEXT)')
            for issue in (self.value['source_issue'],'r1'):
                con.execute('INSERT INTO issue_test_commands VALUES (?,?)',(issue,self.command))
            for path in ('/workspace/app.js','/workspace/tests/test_new.py'):
                con.execute('INSERT INTO issue_editables VALUES (?,?)',(self.value['source_issue'],path))
        self.projection={**self.value,'previous_new_test_delivery':dict(volume='candidate',task_id='new-author-task',
            manifest_sha256='8'*64,test_sha256={'tests/test_new.py':'6'*64})}
        proof=dict(operation='remediation_original_base_seed_v1',base_sha=self.value['base']['base_sha'],
            manifest_sha256=self.value['base']['manifest_sha256'],contract_sha256='c'*64,
            previous_manifest_sha256='8'*64,seed_test_sha256={'tests/test_new.py':'6'*64},
            baseline_test_sha256={'tests/test_old.py':'a'*64},baseline_unchanged=True,snapshot_permissions_unchanged=True,
            product_unchanged=True,red_executed=False,execution_authorized=False,release_homologated=False)
        from broker import remediation_r2_preparation
        with self.b.db() as con:
            remediation_r2_preparation.initialize(con)
            con.execute('INSERT INTO remediation_r2_preparations VALUES (?,?,?)',('source',
                digest(dict(contract=self.value,gate=self.state['r1_gate'],issue_id=f.f.ITEM_ID)),
                json.dumps(dict(stage='base_qualified',issue_id=f.f.ITEM_ID,volume=self.b.PREFIX+'-base-'+f.f.ITEM_ID,
                    execution_authorized=False,release_homologated=False,seed_proof=proof,
                    copy_proof=dict(baseline_test_sha256=proof['baseline_test_sha256'])))))
        self.b.issue_base=lambda issue:{**self.value['base'],'issue_id':issue,'volume':self.b.PREFIX+'-base-'+issue}
        self.calls=[]
        def editables(payload):
            self.calls.append('editables')
            with self.b.db() as con:
                existing=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(payload['issue_id'],))]
                if existing and sorted(existing)!=sorted(payload['paths']):raise ValueError('immutable paths')
                if not existing:
                    for p in payload['paths']:con.execute('INSERT INTO issue_editables VALUES (?,?)',(payload['issue_id'],p))
                con.execute('INSERT OR IGNORE INTO issue_test_commands VALUES (?,?)',(payload['issue_id'],payload['test_command']))
        self.b.register_issue_editables=editables
        def route(b,desired):
            self.calls.append('route')
            with b.db() as con:
                con.execute('INSERT INTO delivery_routes VALUES (?,?)',(desired['issue_id'],json.dumps(desired)))
        self.route=route

    def test_capsule_retains_full_brief_criteria_origin_and_separates_product_review(self):
        route=context.route(self.value,self.state,self.source,self.f.f.ITEM_ID)
        capsule=route['execution_context'];self.assertFalse(route['enabled']);self.assertNotIn('test_first',route)
        self.assertIn('A01: full criterion',capsule['description']);self.assertIn('Full original brief.',capsule['description'])
        self.assertNotIn('\nDELIVERY_OLD_MARKER:',capsule['description'])
        self.assertIn('origin=r1',capsule['description']);self.assertIn('PRODUCT ONLY',capsule['description'])
        self.assertIn('Do not edit tests',capsule['description']);self.assertIn('Do not rerun Red',capsule['description'])
        self.assertIn('Full original independent review.',capsule['review_instruction'])
        self.assertIn('immutable product delivery',capsule['review_instruction'])
        self.assertEqual(resolve(capsule,route['review_instruction'],'review'),capsule['review_instruction'])

    def test_source_context_drift_or_wrong_author_rejected(self):
        for change in (dict(enabled=True),dict(author='wrong'),dict(contract_sha256='0'*64),
                       dict(execution_context=freeze('Different brief','Different review')),dict(review_instruction='different reference')):
            with self.assertRaises(ValueError):context.route(self.value,self.state,{**self.source,**change},self.f.f.ITEM_ID)

    def test_oversized_original_is_not_truncated(self):
        source={**self.source,'execution_context':freeze('x'*11980,'review')}
        value={**self.value,'context_sha256':source['execution_context']['sha256']}
        state=copy.deepcopy(self.state);state['r1_gate']['execution_contract_sha256']=digest(value)
        with self.assertRaises(ValueError):context.route(value,state,source,self.f.f.ITEM_ID)

    def amended(self, description=None, review=None):
        original=freeze(description or ('CURRENT TASK: R2 PRODUCT ONLY.\n'+'historical phase '*350+
            '\nORIGINAL BRIEF DATA: '+json.dumps('Complete user brief.\nBusiness detail preserved.')),
            review or ('CURRENT REVIEW: independent immutable product delivery for R2.\n'+
            'old review controls '*200+'\nORIGINAL REVIEW DATA: '+json.dumps('Complete original review.')))
        value={**self.value,'context_sha256':original['sha256'],
               'amendment':dict(operation='inherited_harness_contract_amendment_v1')}
        state=copy.deepcopy(self.state);state['r1_gate']['execution_contract_sha256']=digest(value)
        source={**self.source,'execution_context':original,'review_instruction':reference(original,'review')}
        return value,state,source

    def test_amended_r2_preserves_business_data_not_duplicate_phase_instructions(self):
        value,state,source=self.amended()
        before=copy.deepcopy((value,state,source))
        capsule=context.route(value,state,source,self.f.f.ITEM_ID)['execution_context']
        self.assertIn('Complete user brief.',capsule['description'])
        self.assertIn('Business detail preserved.',capsule['description'])
        self.assertIn('Complete original review.',capsule['review_instruction'])
        self.assertNotIn('historical phase ',capsule['description'])
        self.assertNotIn('old review controls ',capsule['review_instruction'])
        self.assertIn(source['execution_context']['sha256'],capsule['description'])
        self.assertEqual((value,state,source),before)
        brief,review,_=context.historical_data(value,capsule)
        self.assertEqual(brief,'Complete user brief.\nBusiness detail preserved.')
        self.assertEqual(review,'Complete original review.')

    def test_amendment_cannot_unwrap_arbitrary_or_incomplete_data(self):
        for description,review in [
            ('arbitrary ORIGINAL BRIEF DATA: "brief"',None),
            ('CURRENT TASK: R2 PRODUCT ONLY.\nORIGINAL BRIEF DATA: "brief" garbage',None),
            ('CURRENT TASK: R2 PRODUCT ONLY.\nORIGINAL BRIEF DATA: {}',None),
            (None,'CURRENT REVIEW: independent immutable product delivery for R2.\nORIGINAL REVIEW DATA: "review" garbage'),
        ]:
            with self.subTest(description=description,review=review):
                value,state,source=self.amended(description,review)
                with self.assertRaises(ValueError):context.route(value,state,source,self.f.f.ITEM_ID)

    def test_changed_context_recovery_preserves_hold_without_grant_or_repeat(self):
        value,state,source=self.amended(description=('CURRENT TASK: R2 PRODUCT ONLY.\n'+
            'historical phase '*650+'\nORIGINAL BRIEF DATA: '+json.dumps('Full brief.')))
        state['steps']['R1']['stage']='approved'
        state['r2_issue_hold']=dict(category='r2_context_precondition_failed')
        before=copy.deepcopy(state)
        new=context.context_recovery(value,state,source,self.f.f.ITEM_ID)
        self.assertEqual(state,before)
        self.assertNotIn('r2_issue_hold',new)
        receipt=new['r2_context_recovery']
        self.assertEqual(receipt['previous_hold'],before['r2_issue_hold'])
        self.assertFalse(receipt['execution_authorized']);self.assertFalse(receipt['dispatch_ready'])
        self.assertFalse(receipt['release_homologated'])
        self.assertNotIn('r2_runtime',new)
        with self.assertRaises(ValueError):context.context_recovery(value,new,source,self.f.f.ITEM_ID)
        for change in (dict(r2_runtime={'already':'registered'}),
                       dict(r2_issue_hold={'category':'different'})):
            with self.assertRaises(ValueError):context.context_recovery(value,{**state,**change},source,self.f.f.ITEM_ID)

    def test_maintenance_recovery_archives_hold_and_does_not_create_route(self):
        value,state,source=self.amended(description=('CURRENT TASK: R2 PRODUCT ONLY.\n'+
            'historical phase '*650+'\nORIGINAL BRIEF DATA: '+json.dumps('Full brief.')))
        state['steps']['R1']['stage']='approved'
        state['r2_issue_hold']=dict(category='r2_context_precondition_failed')
        with self.b.db() as con:
            con.execute('UPDATE remediation_executions SET contract=?,state=?',
                (json.dumps(value),json.dumps(state)))
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',
                (json.dumps(source),value['source_issue']))
            con.execute('UPDATE remediation_r2_preparations SET input_sha256=?',
                (digest(dict(contract=value,gate=state['r1_gate'],issue_id=self.f.f.ITEM_ID)),))
        from types import SimpleNamespace
        fx=SimpleNamespace(native=SimpleNamespace(settings={}))
        with patch.object(context.planning,'Effects',return_value=fx),\
             patch.object(context.preparation.review,'verify'),\
             patch('broker.native.issue_task_runs',return_value=[]):
            new=context.arm_context_recovery(self.b,'source')
            self.assertEqual(context.arm_context_recovery(self.b,'source'),new)
        self.assertNotIn('r2_issue_hold',new)
        self.assertFalse(new['r2_context_recovery']['execution_authorized'])
        self.assertEqual(self.calls,[])
        with self.b.db() as con:
            self.assertFalse(con.execute('SELECT 1 FROM delivery_routes WHERE issue_id=?',
                (self.f.f.ITEM_ID,)).fetchone())

    def test_amended_source_permissions_do_not_grant_frozen_test_writes(self):
        value,state,source=self.amended()
        paths=context.source_permissions(value)
        self.assertEqual(paths,['/workspace/app.js'])
        self.assertNotIn('/workspace/tests/test_new.py',paths)
        self.assertEqual(context.source_permissions(self.value),['/workspace/app.js','/workspace/tests/test_new.py'])
        state['r2_context_recovery']=dict(operation='retained_context_recovery')
        state['r2_issue_hold']=dict(category='r2_context_precondition_failed')
        before=copy.deepcopy(state)
        new=context.scope_recovery(value,state,paths)
        self.assertEqual(state,before)
        self.assertFalse(new['r2_scope_recovery']['execution_authorized'])
        self.assertEqual(new['r2_scope_recovery']['readonly_test_paths'],['/workspace/tests/test_new.py'])
        for data,permissions in ((new,paths),(state,paths+['/workspace/tests/test_new.py']),
                                 (state,[])):
            with self.assertRaises(ValueError):context.scope_recovery(value,data,permissions)

    def invoke(self):
        with patch.object(context.planning,'Effects',return_value=self.f.f.fx),patch.object(context.preparation.review,'verify'),\
             patch.object(context.handoff_runtime,'register',side_effect=self.route),\
             patch.object(context.references.review,'verify'):
            return context.prepare(self.b,'source')

    def test_prepares_paused_exact_product_scope_and_real_foreign_reference_idempotently(self):
        proof=self.invoke();self.assertEqual(proof['operation'],'paused_remediation_r2_runtime_v1')
        self.assertFalse(proof['execution_authorized']);self.assertFalse(proof['dispatch_ready'])
        self.assertEqual(proof['writable_paths'],['/workspace/app.js'])
        self.assertEqual(proof['readonly_tests'],['/workspace/tests/test_new.py'])
        self.assertEqual(self.invoke(),proof)
        with self.b.db() as con:
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(self.f.f.ITEM_ID,)).fetchone()[0])
            self.assertFalse(route['enabled']);self.assertNotIn('test_first',route)
            self.assertEqual(con.execute('SELECT count(*) FROM test_first_red WHERE issue_id=?',(self.f.f.ITEM_ID,)).fetchone()[0],0)
            self.assertEqual(con.execute('SELECT count(*) FROM remediation_red_references').fetchone()[0],1)

    def test_base_qualification_or_full_command_drift_prevents_registration(self):
        with self.b.db() as con:con.execute("UPDATE issue_test_commands SET command='partial suite' WHERE issue_id=?",('r1',))
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls,[])

    def test_fault_after_route_registration_resumes_without_different_context(self):
        with patch.object(context.planning,'Effects',return_value=self.f.f.fx),patch.object(context.preparation.review,'verify'),\
             patch.object(context.handoff_runtime,'register',side_effect=self.route),\
             patch.object(context.references,'register',side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):context.prepare(self.b,'source')
        self.assertFalse(self.invoke()['dispatch_ready'])
        self.assertEqual(self.calls.count('route'),1)

    def test_watchdog_registers_once_without_dispatch_or_grant(self):
        with patch.object(context.planning,'Effects',return_value=self.f.f.fx),patch.object(context.preparation.review,'verify'),\
             patch.object(context.handoff_runtime,'register',side_effect=self.route),patch.object(context.references.review,'verify'):
            context.tick(self.b);context.tick(self.b)
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])
        self.assertFalse(state['r2_runtime']['dispatch_ready']);self.assertFalse(state['r2_runtime']['execution_authorized'])
        self.assertEqual(self.calls.count('route'),1)

    def test_paused_reference_requires_full_suite_same_baseline_and_no_frozen_test_write(self):
        with self.b.db() as con:
            row=json.loads(con.execute('SELECT state FROM remediation_r2_preparations').fetchone()[0])
            row['seed_proof']['product_unchanged']=False
            con.execute('UPDATE remediation_r2_preparations SET state=?',(json.dumps(row),))
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls,[])

    def test_context_observation_deadline_publishes_hold_without_identical_retry(self):
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])
            state['r2_context_observation']=dict(started_at=0,execution_authorized=False)
            con.execute('UPDATE remediation_executions SET state=?',(json.dumps(state),))
        context.tick(self.b);context.tick(self.b)
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])
        self.assertEqual(state['r2_issue_hold']['category'],'r2_context_observation_deadline')
        self.assertEqual(state['r2_issue_hold']['owner'],'lead');self.assertEqual(self.calls,[])
