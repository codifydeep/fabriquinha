"""Scope/review trust boundary; synthetic receipts, no live product permissions."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from fabriquinha.maintenance import authorization,reviewed,observer_failures
from fabriquinha.observer_maintenance import PROTOCOL

class MaintenanceAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.project=SimpleNamespace(fingerprint=lambda:'project',technical_roles={'cto':'cto'},coordination_roles={'lead':'lead'})
        self.facts=dict(protocol=PROTOCOL,acceptance='accepted',paths=['tests/acceptance_demo.py'],
            snapshot='snapshot',commit='commit',tests='freeze',brief='business',delivery_approval=False)
        self.records={
            'business':dict(kind='brief_approval',binding={'task':'brief'},payload={}),
            'authorization':dict(kind='maintenance_authorization',binding=dict(actor='operator',release='new',request='once',task='brief'),
                payload=dict(**self.facts,project='project',business_change=False)),
            'plan':dict(kind='work_plan',binding=dict(task='plan',kind='plan',actor='lead',author='lead',reviewing=False,release='new',contract='exact',number=10),
                payload=dict(project='project',approval='authorization',document={'tasks':[{'id':'one'}]})),
            'review':dict(kind='plan_review',binding=dict(task='plan',kind='plan',actor='cto',author='lead',reviewing=True,release='new',contract='exact',number=11),
                payload=dict(project='project',plan='plan',verdict=dict(decision='approve',findings=[])))}
        self.store=Mock()
        def receipt(key,kind=None):
            record=self.records[key]
            if kind and record['kind']!=kind:raise ValueError('kind mismatch')
            return record
        self.store.receipt.side_effect=receipt
        self.enterContext(patch('fabriquinha.maintenance.source',return_value=self.facts))

    def test_operator_scope_is_not_cto_or_test_approval(self):
        self.assertFalse(authorization(self.project,self.store,'authorization')['payload']['delivery_approval'])
        self.assertEqual(reviewed(self.project,self.store,'review')['snapshot'],'snapshot')

    def test_rejects_self_stale_foreign_and_non_cto_reviews(self):
        original=copy.deepcopy(self.records)
        for record,section,key,value in [
            ('review','binding','actor','lead'),('review','binding','actor','qa'),
            ('review','binding','number',10),('review','binding','contract','stale'),
            ('review','binding','release','old'),('plan','binding','actor','cto'),
            ('authorization','binding','actor','agent'),('authorization','binding','task','foreign'),
            ('authorization','payload','business_change',True),('authorization','payload','snapshot','other'),
            ('authorization','payload','paths',['tests/another.py']),('authorization','payload','delivery_approval',True),
            ('authorization','payload','commit','other'),('plan','binding','kind','tests'),
            ('review','payload','verdict',dict(decision='changes',findings=['incomplete']))]:
            self.records=copy.deepcopy(original);self.records[record][section][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):reviewed(self.project,self.store,'review')

    def test_one_package_only(self):
        self.records['plan']['payload']['document']['tasks'].append({'id':'extra'})
        with self.assertRaises(ValueError):reviewed(self.project,self.store,'review')

    def test_control_requires_exact_live_list_assertion_frame(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'tests').mkdir()
            p='tests/acceptance_demo.py'
            (root/p).write_text("class Demo:\n def test_late(self):\n  self.assertEqual(pair['errors'], [])\n  self.assertEqual(state, 'ready')\n")
            self.store.tree.return_value=root
            def report(line,assertion=True):
                return {'failures':[{'assertion':assertion,'frames':[{'file':p,'function':'test_late','line':line}]}]}
            self.assertEqual(observer_failures(self.store,'snapshot',[p],report(3)),{p})
            self.assertEqual(observer_failures(self.store,'snapshot',[p],report(4)),set())
            self.assertEqual(observer_failures(self.store,'snapshot',[p],report(3,False)),set())

    def test_context_names_actual_baseline_files_and_exact_exception(self):
        import tempfile
        from pathlib import Path
        from fabriquinha.maintenance import context
        from test_observer_maintenance import BEFORE
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'tests').mkdir();(root/'tests/acceptance_demo.py').write_text(BEFORE)
            self.store.tree.return_value=root
            result=context(self.project,self.store,'authorization')
            self.assertEqual(set(result['helpers']),{'tests/acceptance_demo.py'})
            self.assertEqual(len(result['helpers']['tests/acceptance_demo.py']),2)
            self.assertIn('ARE the authorized edit targets',result['edit_contract'])
            self.assertIn('Never edit fabriquinha_acceptance',result['edit_contract'])
            self.assertIn('Do not preserve the whole-file hashes',result['edit_contract'])
            self.assertNotIn('edit_contract',self.records['authorization']['payload'])
