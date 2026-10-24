import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.browser import contract


def scenario():
    return dict(version=1,checks=[dict(id='greeting',path='/',actions=[
        dict(action='fill',selector='#name',value='Ada'),dict(action='click',selector='#greet')],
        selector='#result',text='Hello, Ada')])


class FrozenBrowserContract(unittest.TestCase):
    def test_declarative_actions_are_accepted(self):
        self.assertEqual(contract(scenario())[0]['id'],'greeting')

    def test_shell_script_external_url_or_empty_check_is_not_a_contract(self):
        for change in ({'path':'https://example.org'}, {'path':'//example.org'},
                       {'actions':[dict(action='evaluate',code='anything')]}, {'text':''}):
            value=scenario();value['checks'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):contract(value)
        for value in (dict(version=1,checks=[]),{**scenario(),'command':'anything'}):
            with self.assertRaises(ValueError):contract(value)

    def test_duplicate_case_ids_or_unbounded_actions_are_rejected(self):
        value=scenario();value['checks']*=2
        with self.assertRaises(ValueError):contract(value)
        value=scenario();value['checks'][0]['actions']*=20
        with self.assertRaises(ValueError):contract(value)


if __name__=='__main__':unittest.main()
