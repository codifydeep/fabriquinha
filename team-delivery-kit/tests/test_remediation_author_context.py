import copy
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import test_remediation_execution as fixtures
from execution_context import freeze,resolve,reference
from broker import remediation_author_context as context
from broker.technical_remediation_plan import digest


class RemediationAuthorContextTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.RemediationExecutionContractTests();fixture.setUp()
        from broker.remediation_execution import contract
        self.value=contract(fixture.c,fixture.s,['tests/test_new.py'],['app.js'])
        self.value['previous_new_test_delivery']=dict(task_id='historic',volume='frozen',
            manifest_sha256='a'*64,test_sha256={'tests/test_new.py':'b'*64})
        original=freeze('Entire original product brief.\nDELIVERY_OLD_MARKER:data',
                        'Entire original independent review criteria.')
        self.value['context_sha256']=original['sha256']
        self.route=dict(issue_id='source',author='author',reviewer='delivery-reviewer',techlead='lead',cto='cto',
            contract_sha256='c'*64,minimum_calls=16,enabled=False,test_first=True,
            test_first_files=['tests/test_new.py'],execution_context=original,
            review_instruction=reference(original,'review'))

    def test_context_preserves_every_criterion_and_original_prose_without_active_old_markers(self):
        capsule=context.capsule(self.value,self.route)
        self.assertIn('A01: criterion',capsule['description'])
        self.assertIn('Entire original product brief.',capsule['description'])
        self.assertIn('Entire original independent review criteria.',capsule['review_instruction'])
        self.assertNotIn('\nDELIVERY_OLD_MARKER:',capsule['description'])
        self.assertIn('R1',capsule['description'])
        self.assertIn('Do not edit product',capsule['description'])
        self.assertNotEqual(capsule['sha256'],self.value['context_sha256'])
        self.assertEqual(resolve(capsule,reference(capsule,'implementation'),'implementation'),capsule['description'])

    def test_stale_source_context_author_contract_or_enabled_route_rejected(self):
        for change in (dict(enabled=True),dict(author='other'),dict(contract_sha256='0'*64),
                       dict(execution_context=freeze('Other brief','Other review'))):
            with self.assertRaises(ValueError):context.capsule(self.value,{**self.route,**change})

    def test_paused_r1_route_keeps_roles_contract_and_seed_scope_without_dispatch(self):
        route=context.route(self.value,self.route,'r1')
        self.assertEqual(route['issue_id'],'r1')
        self.assertFalse(route['enabled'])
        self.assertEqual(route['author'],'author')
        self.assertEqual(route['test_first_files'],['tests/test_new.py'])
        self.assertEqual(route['contract_sha256'],'c'*64)
        self.assertEqual(resolve(route['execution_context'],route['review_instruction'],'review'),
                         route['execution_context']['review_instruction'])
        self.assertEqual(context.paths(self.value),['/workspace/app.js','/workspace/tests/test_new.py'])

    def test_long_context_is_rejected_not_truncated_or_criteria_dropped(self):
        original=freeze('x'*11980,'review')
        self.value['context_sha256']=original['sha256']
        with self.assertRaises(ValueError):context.capsule(self.value,{**self.route,'execution_context':original})

    def test_amendment_unwraps_only_controller_phase_prose_preserving_full_original_brief(self):
        import json
        brief='Entire approved original brief. '+('detailed product scope '*300)
        outer=freeze('CURRENT TASK: R2 PRODUCT ONLY.\nSuperseded phase instructions.\nORIGINAL BRIEF DATA: '+json.dumps(brief),
                     'Entire previous independent review.')
        value={**self.value,'context_sha256':outer['sha256'],
               'amendment':dict(operation='inherited_harness_contract_amendment_v1')}
        route={**self.route,'execution_context':outer}
        capsule=context.capsule(value,route)
        self.assertIn(json.dumps(brief),capsule['description'])
        self.assertIn(outer['sha256'],capsule['description'])
        self.assertIn('A01: criterion',capsule['description'])
        self.assertNotIn('Superseded phase instructions.',capsule['description'])
        for bad in ('unrecognized wrapper',outer['description']+' trailing content'):
            altered=freeze(bad,outer['review_instruction'])
            with self.assertRaises(ValueError):context.capsule({**value,'context_sha256':altered['sha256']},
                {**route,'execution_context':altered})

    def test_r2_input_requires_exact_approved_r1_and_never_relabels_red(self):
        red=dict(issue_id='r1',task_id='new-tests',volume='new-snapshot',red=dict(manifest_sha256='d'*64,
            test_sha256={'tests/test_new.py':'e'*64}))
        gate=dict(operation='immutable_remediation_r1_gate_v1',run_id=self.value['run_id'],
            execution_contract_sha256=digest(self.value),red=red,review_task='lead-review',
            review_decision=dict(action='approve_test_revision',manifest_sha256='d'*64),
            product_execution_authorized=False,release_homologated=False)
        state=dict(r1_gate=gate,steps={'R1':dict(stage='approved',issue_id='r1',manifest_sha256='d'*64,review_task='lead-review')})
        result=context.product_input(self.value,state)
        self.assertEqual(result['red'],red)
        self.assertEqual(result['origin_issue'],'r1')
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(result['editable_files'],['app.js'])
        self.assertEqual(result['readonly_tests'],['tests/test_new.py'])
        for mutate in (lambda s:s['r1_gate'].update(execution_contract_sha256='0'*64),
                       lambda s:s['r1_gate']['review_decision'].update(manifest_sha256='0'*64),
                       lambda s:s['steps']['R1'].update(stage='waiting'),
                       lambda s:s['r1_gate'].update(review_task='new-tests')):
            bad=copy.deepcopy(state);mutate(bad)
            with self.assertRaises(ValueError):context.product_input(self.value,bad)

    def test_prepare_is_paused_idempotent_and_requires_idle_exact_scope(self):
        import json
        import test_remediation_test_review as review_fixtures
        fixture=review_fixtures.RemediationTestReviewTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        b=fixture.b
        value={**fixture.value,'context_sha256':self.route['execution_context']['sha256'],
            'criteria':{'A01':'criterion'},'steps':copy.deepcopy(self.value['steps'])}
        state={**fixture.f.state,'contract_sha256':digest(value)}
        source={**fixture.route,'issue_id':'old','reviewer':'delivery-reviewer',
            'execution_context':self.route['execution_context'],
            'review_instruction':self.route['review_instruction']}
        with b.db() as con:
            con.execute('UPDATE remediation_executions SET contract=?,state=?',(json.dumps(value),json.dumps(state)))
            con.execute('DELETE FROM delivery_routes WHERE issue_id=?',('r1',))
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(source),'old'))
            con.execute('CREATE TABLE issue_editables(issue_id TEXT,path TEXT)')
            con.execute('CREATE TABLE issue_test_commands(issue_id TEXT,command TEXT)')
            con.execute('CREATE TABLE leases(status TEXT)')
            for path in context.paths(value):con.execute('INSERT INTO issue_editables VALUES (?,?)',('old',path))
            con.execute('INSERT INTO issue_test_commands VALUES (?,?)',('old','pinned-full-suite'))
        calls=[]
        def editables(payload):calls.append(payload)
        def register(b,route):
            with b.db() as con:con.execute('INSERT OR REPLACE INTO delivery_routes VALUES (?,?)',('r1',json.dumps(route)))
        b.register_issue_editables=editables
        with patch.object(context.execution,'register'),patch.object(context.handoff_runtime,'register',side_effect=register):
            first=context.prepare(b,'source')
            self.assertEqual(context.prepare(b,'source'),first)
            self.assertFalse(first['execution_authorized'])
            self.assertFalse(first['dispatch_ready'])
            self.assertEqual(first['writable_paths'],['/workspace/tests/test_new.py'])
            self.assertEqual(first['read_paths'],['/workspace/app.js','/workspace/tests/test_new.py'])
            with b.db() as con:con.execute("INSERT INTO leases VALUES ('running')")
            with self.assertRaises(ValueError):context.prepare(b,'source')
        self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
