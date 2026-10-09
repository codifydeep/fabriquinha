import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from decision_memory import nominate,curate
from decision_context import context

SOURCE='33333333-3333-4333-8333-333333333333';AUTHOR='11111111-1111-4111-8111-111111111111';TASK='44444444-4444-4444-8444-444444444444';REVIEWER='22222222-2222-4222-8222-222222222222'

class DecisionContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.native='{"technical_decisions":["Use SQLite"]}'
        self.source={'task_id':SOURCE,'agent_id':AUTHOR,'status':'completed','mode':'planning','lease_status':'closed','content_sha256':hashlib.sha256(self.native.encode()).hexdigest()}
        self.key=nominate(self.root,'https://github.com/acme/example','delivery-kit-one',
            {'subject':'Local storage','decisions':['Use SQLite'],'commit':'a'*40,'source_release':'TEST-1','expires':1000,'supersedes':None},self.source,now=100)
        self.answer={'role':'techlead','decision':'approve','entry_sha256':self.key,'reason':'Supported'}
        self.output=json.dumps(self.answer)
        self.review={**self.source,'task_id':TASK,'agent_id':REVIEWER,'content_sha256':hashlib.sha256(self.output.encode()).hexdigest()}
    def read(self,role='cto'):
        return context(self.root,'https://github.com/acme/example','delivery-kit-one',role=role,
            base_sha='b'*40,is_ancestor=lambda a,b:True,cli=None,now=102)
    def test_unreviewed_memory_never_enters_context(self):
        self.assertEqual(self.read(),'')
    def test_cross_profile_context_revalidates_both_exact_native_proofs(self):
        curate(self.root,'https://github.com/acme/example','delivery-kit-one',self.key,self.answer,self.review,now=101)
        for role in ('product','cto','techlead','frontend'):
            with patch('decision_context.observe',side_effect=[(self.source,self.native),(self.review,self.output)]) as observe:
                value=self.read(role)
            self.assertEqual(observe.call_count,2)
            self.assertIn('Use SQLite',value);self.assertIn('not current requirements',value)
            self.assertLessEqual(len(value),1200)
    def test_changed_native_output_cannot_be_reused(self):
        curate(self.root,'https://github.com/acme/example','delivery-kit-one',self.key,self.answer,self.review,now=101)
        with patch('decision_context.observe',return_value=({**self.source,'content_sha256':'f'*64},self.native)):
            with self.assertRaises(ValueError):self.read()
