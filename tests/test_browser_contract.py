import sys
import unittest
import tempfile
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.browser import contract, load_contract,author_protocol
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project,execution_context
from fabriquinha.quality import Quality
from test_delivery_core import configuration


def scenario():
    return dict(version=1,checks=[dict(id='greeting',path='/',actions=[
        dict(action='fill',selector='#name',value='Ada'),dict(action='click',selector='#greet')],
        selector='#result',text='Hello, Ada')])


class FrozenBrowserContract(unittest.TestCase):
    def test_author_receives_actual_protocol_fields_not_a_feature_implementation(self):
        value=author_protocol();schema=value['schema']
        self.assertEqual(set(schema['required']),{'version','checks'})
        item=schema['properties']['checks']['items']
        self.assertEqual(set(item['required']),set(scenario()['checks'][0]))
        actions=item['properties']['actions']['items']['oneOf']
        self.assertEqual([action['properties']['action']['const'] for action in actions],['fill','click'])
        self.assertEqual(schema['properties']['checks']['maxItems'],20)
        self.assertNotIn('Hello, Ada',json.dumps(value))
        self.assertEqual(contract(scenario())[0]['id'],'greeting')
        schema['properties']['checks']['maxItems']=100
        self.assertEqual(author_protocol()['schema']['properties']['checks']['maxItems'],20)
        context=execution_context(Project.parse(configuration()))['http_contract']
        self.assertEqual(context['health']['json'],{'status':'ok'})
        self.assertEqual(context['identity']['json_fields'],['source_sha'])
        self.assertIn('FABRIQUINHA_SOURCE_SHA',context['identity']['source_sha'])

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


class BrowserBeforeFreeze(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.work=self.root/'work';(self.work/'tests').mkdir(parents=True)
        (self.work/'app.py').write_text('VALUE = 1\n')
        (self.work/'tests/test_existing.py').write_text('baseline\n')
        self.store=Store(self.root/'private');self.baseline=self.store.capture(self.work)
        (self.work/'tests/test_new.py').write_text('new test body\n')
        value=configuration();value.update(coordination_roles={'product':'product','lead':'lead'},
            delivery_roles={'tests':'qa','integration':'devops'},browser_image='sha256:'+'b'*64,
            reviewers={'backend':'lead','lead':'cto','qa':'lead','devops':'qa'})
        self.project=Project.parse(value)
        self.run=Run('task',1,'qa','tests',False,'qa','release','contract')
        self.board=SimpleNamespace(ensure=lambda run:None,criteria=lambda run:('greeting',))
        self.quality=Quality(self.project,self.store,None,self.board);self.quality.observe=Mock()

    def test_malformed_or_uncovered_browser_contract_is_rejected_before_red_jobs(self):
        for document in ({'version':1,'checks':[]},dict(version=1,checks=[{**scenario()['checks'][0],'id':'foreign'}])):
            (self.work/'tests/qa.new.json').write_text(json.dumps(document))
            with self.subTest(document=document),self.assertRaises(ValueError):
                self.quality.red(self.run,self.baseline,self.store.capture(self.work))
            self.quality.observe.assert_not_called()
        (self.work/'tests/qa.new.json').write_text(json.dumps(scenario()))
        self.quality.browser_tests(self.run,self.store.capture(self.work))

    def test_old_invalid_red_cannot_freeze_but_reviewer_can_request_correction(self):
        snapshot=self.store.capture(self.work)
        red=self.store.record('red',self.run.binding(),dict(project=self.project.fingerprint(),snapshot=snapshot,
            baseline=self.baseline,cases=['existing','new'],new_cases=['new']))
        self.board.input=lambda *args,**kwargs:red
        reviewer=replace(self.run,number=2,actor='lead',reviewing=True)
        with self.assertRaises(ValueError):
            self.quality.tests_review(reviewer,red,dict(decision='approve',reason='Cannot approve invalid QA',findings=[]))
        self.assertFalse(any(self.store.receipt(path.stem)['kind']=='tests_frozen' for path in (self.store.root/'receipts').glob('*.json')))
        result=self.quality.tests_review(reviewer,red,dict(decision='changes',reason='Add the required QA contract',
            findings=[dict(path='tests/test_new.py',line=1,detail='No browser acceptance contract was delivered')]))
        self.assertEqual(self.store.receipt(result)['kind'],'test_review')


if __name__=='__main__':unittest.main()
