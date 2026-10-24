import sys
import unittest
import tempfile
import json
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.browser import contract, load_contract


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

    def test_new_increment_adds_contract_without_editing_existing_regressions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);original=json.dumps(scenario())
            (root/'qa.json').write_text(original)
            additional=scenario();additional['checks'][0]['id']='another'
            (root/'qa.join.json').write_text(json.dumps(additional))
            self.assertEqual([item['id'] for item in load_contract(root)['checks']],['greeting','another'])
            self.assertEqual((root/'qa.json').read_text(),original)
            (root/'qa.duplicate.json').write_text(original)
            with self.assertRaises(ValueError):load_contract(root)


if __name__=='__main__':unittest.main()
