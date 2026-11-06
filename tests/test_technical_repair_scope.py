import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.technical_repair import validate_scope


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.project=SimpleNamespace(technical_roles={'cto':'cto'},fingerprint=lambda:'project',tests_dir='tests')
        self.binding=dict(actor='cto',kind='diagnostic',reviewing=False,release='v2')
        self.scope=dict(tests='freeze',test_paths=['tests/acceptance_cancel.py'],cases=['acceptance_cancel.Cancel.test_full'])
        self.records={
            'incident':dict(binding=dict(task='source',number=3,kind='implementation',reviewing=False,release='v2'),
                            payload=dict(project='project',source='source',source_run=3,source_state='blocked',controller_effects=[],snapshot='implementation')),
            'experiment':dict(binding=self.binding.copy(),payload=dict(project='project',incident='incident',snapshot='implementation')),
            'freeze':dict(binding=dict(release='v2'),payload={})}
        self.store=Mock()
        self.store.receipt.side_effect=lambda key,kind=None:self.records[key]
        self.quality=Mock()
        self.quality.frozen_plan.return_value=dict(snapshot='frozen',baseline='base',tests={'tests/acceptance_cancel.py':{}},cases=self.scope['cases'])

    def validate(self):
        with patch('fabriquinha.quality.Quality',return_value=self.quality):
            return validate_scope(self.project,self.store,'incident',self.binding,'experiment',self.scope)

    def test_blocked_source_needs_no_synthetic_retry(self):
        result=self.validate()
        self.assertFalse(result['delivery_approval'])
        self.assertTrue(result['independent_freeze_required'])
        self.quality.protect.assert_called_once_with('frozen','implementation',exact_tests=True)

    def test_triage_also_supported(self):
        self.records['incident']['payload']['source_state']='triage'
        self.validate()

    def test_rejects_stale_identity_and_effects(self):
        original=copy.deepcopy(self.records)
        for record,section,key,value in (
            ('incident','payload','source_run',4),('incident','payload','controller_effects',['pending']),
            ('incident','payload','source_state','running'),('experiment','payload','snapshot','other'),
            ('experiment','binding','actor','lead'),('freeze','binding','release','other')):
            self.records=copy.deepcopy(original)
            self.records[record][section][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate()

    def test_rejects_unknown_cases_and_unscoped_files(self):
        for changes in ({'cases':['acceptance_cancel.Cancel.test_other']},
                        {'test_paths':['tests/../acceptance_cancel.py']},
                        {'test_paths':['tests/conftest.py']}, {'test_paths':[]}):
            original=copy.deepcopy(self.scope)
            self.scope.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.validate()
            self.scope=original

    def test_unchanged_tests_are_mandatory(self):
        self.quality.protect.side_effect=ValueError('frozen tests changed')
        with self.assertRaises(ValueError):self.validate()

    def test_strengthening_is_explicit_and_old_authority_stays_strict(self):
        self.assertEqual(self.validate()['protocol'],'technical-test-repair-1')
        self.store.manifest.return_value={'app.py':{}}
        self.scope.update(mode='strengthen',product_imports=['app'])
        result=self.validate()
        self.assertEqual(result['protocol'],'technical-test-strengthening-1')
        self.assertEqual(result['product_imports'],['app'])
        for imports in (['os'],['app','app'],[],['../app']):
            self.scope['product_imports']=imports
            with self.subTest(imports=imports),self.assertRaises(ValueError):self.validate()

    def test_stateful_authority_requires_a_local_public_class_and_declared_methods(self):
        from tempfile import TemporaryDirectory
        from fabriquinha.technical_repair import scope_input
        self.store.manifest.return_value={'app.py':{}}
        with TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'app.py').write_text('from pathlib import Path\nclass Game:\n    def play(self): pass\n')
            self.store.tree.return_value=path
            self.scope.update(mode='strengthen',product_imports=['app'],
                              stateful_api={'module':'app','class':'Game','methods':['play']})
            result=self.validate()
            self.assertEqual(scope_input(result)['stateful_api'],self.scope['stateful_api'])
            for bad in ({'class':'Path'},{'methods':['clear']},{'methods':['__init__']},{'module':'os'}):
                self.scope['stateful_api']={'module':'app','class':'Game','methods':['play'],**bad}
                with self.subTest(bad=bad),self.assertRaises(ValueError):self.validate()

    def test_instance_repair_is_offered_only_for_exact_refused_author_snapshot(self):
        from fabriquinha.technical_repair import refused_instance_candidate
        incident=self.records['incident'];incident['binding']['kind']='tests'
        incident['payload']['submission_refusal']='refusal'
        parent=dict(snapshot='frozen',test_paths=['tests/acceptance_cancel.py'])
        refusal=dict(project='project',phase='tests',operation='delivery_submit',delivery_approval=False,
            error='only explicit product calls and local literal setup allowed',snapshot='implementation',baseline='frozen')
        self.records['refusal']=dict(binding=incident['binding'].copy(),payload=refusal)
        before={'app.py':'same','tests/acceptance_cancel.py':'old'}
        self.store.manifest.side_effect=lambda key:before if key=='frozen' else {**before,'tests/acceptance_cancel.py':'candidate'}
        self.assertTrue(refused_instance_candidate(self.store,self.project,incident,parent))
        incident['payload']['snapshot']='frozen'
        self.assertTrue(refused_instance_candidate(self.store,self.project,incident,parent))
        incident['payload']['snapshot']='unrelated'
        self.assertFalse(refused_instance_candidate(self.store,self.project,incident,parent))
        incident['payload']['snapshot']='implementation'
        for field,value in [('baseline','foreign'),('phase','implementation'),('delivery_approval',True)]:
            self.records['refusal']['payload']={**refusal,field:value}
            self.assertFalse(refused_instance_candidate(self.store,self.project,incident,parent))
        self.records['refusal']['payload']=refusal
        self.store.manifest.side_effect=lambda key:before if key=='frozen' else {**before,'app.py':'changed'}
        self.assertFalse(refused_instance_candidate(self.store,self.project,incident,parent))

    def test_test_author_successor_requires_exact_prior_strict_authority(self):
        self.records['incident']['binding']['kind']='tests'
        self.scope.update(mode='strengthen',product_imports=['app'],parent_repair='parent')
        self.records['parent']=dict(binding={'release':'v2'})
        self.store.manifest.return_value={'app.py':{}}
        authority=dict(context=dict(protocol='technical-test-repair-1',tests='freeze',implementation_snapshot='preserved-product'),proposal=dict(classification='test_contract'))
        with patch('fabriquinha.repairs.reviewed',return_value=authority):
            self.assertEqual(self.validate()['parent_repair'],'parent')
            authority['context']['protocol']='technical-test-strengthening-1'
            with self.assertRaises(ValueError):self.validate()

    def test_review_coverage_keeps_current_candidate_and_parent_scope(self):
        self.records['incident']['binding'].update(kind='tests',reviewing=True)
        self.records['incident']['payload'].update(source_state='triage',review_escalation='escalation')
        self.scope.update(mode='strengthen',product_imports=['app'],parent_repair='parent')
        self.records['parent']=dict(binding={'release':'v2'})
        self.records['escalation']=dict(binding=self.records['incident']['binding'].copy(),payload={'snapshot':'implementation'})
        self.store.manifest.return_value={'app.py':{}}
        authority=dict(review='parent',context=dict(protocol='technical-test-strengthening-1',tests='freeze',implementation_snapshot='preserved-product',cases=self.scope['cases'],test_paths=self.scope['test_paths'],product_imports=['app']),proposal=dict(classification='test_contract'))
        with patch('fabriquinha.repairs.reviewed',return_value=authority),patch('fabriquinha.test_revision.revision_context') as check:
            result=self.validate()
            self.assertEqual(result['preserve_snapshot'],'implementation')
            self.assertEqual(result['implementation_snapshot'],'preserved-product')
            check.assert_called_once()
            self.quality.protect.assert_not_called()
