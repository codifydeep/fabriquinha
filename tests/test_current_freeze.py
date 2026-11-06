from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.releases import implementation_fixture_context

class CurrentFreeze(unittest.TestCase):
    def test_backend_sees_current_freeze_hashes_and_prior_scope_only_as_provenance(self):
        prior={'review':'authority','context':dict(snapshot='old',tests='old-freeze',cases=['C.t']),
               'proposal':dict(classification='test_contract',test_paths=['tests/c.py'])}
        current=dict(snapshot='new',tests={'tests/c.py':{'sha256':'current'}},control_cases=['C.t'])
        data=implementation_fixture_context(prior,'new-freeze',current)
        self.assertEqual(data['protected_tests'],dict(receipt='new-freeze',snapshot='new',files=current['tests']))
        self.assertNotIn('old-freeze',str(data))
        self.assertEqual(data['review'],'authority')

    def test_replay_starts_with_survivor_and_refuses_drift(self):
        from unittest.mock import Mock
        from fabriquinha.quality import DeliveryTools
        tool=DeliveryTools.__new__(DeliveryTools);tool.run=Mock()
        tool.quality=Mock();tool.quality.project.fingerprint.return_value='project';tool.quality.project.tests_dir='tests'
        tool.sandbox=Mock();tool.board=Mock();tool.board.input.return_value='new-freeze'
        tool.store=Mock();tool.store.capture.return_value='current'
        tool.store.receipt.return_value={'payload':dict(freeze='old-freeze',project='project',snapshot='prior')}
        files={'app.py':'product','tests/test_a.py':'new'}
        tool.store.manifest.side_effect=lambda k:files if k=='current' else {'app.py':'product','tests/test_a.py':'old'}
        tool.quality.fixture_replay=({'submission':'plan','controls':[
            dict(survived=False,edits={'app.py':'first'},targets={'a':'first'}),
            dict(survived=True,edits={'app.py':'second'},targets={'b':'second'})]},'new-freeze')
        tool.submit=Mock(return_value={'scheduled':True})
        self.assertEqual(tool.replay_controls({}),{'scheduled':True})
        tool.submit.assert_called_once_with(dict(mutations=[{'app.py':'second'},{'app.py':'first'}],
                                                targets=[{'b':'second'},{'a':'first'}]))
        for args in ({'receipt':'prior'},None):
            with self.assertRaises(ValueError):tool.replay_controls(args)
        files['app.py']='changed'
        with self.assertRaises(ValueError):tool.replay_controls({})
        files['app.py']='product';tool.board.input.return_value='old-freeze'
        with self.assertRaises(ValueError):tool.replay_controls({})
        self.assertEqual(tool.submit.call_count,1)
