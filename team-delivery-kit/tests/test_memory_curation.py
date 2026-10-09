import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from decision_memory import nominate
from memory_curation import tick

TASK='33333333-3333-4333-8333-333333333333';AUTHOR='11111111-1111-4111-8111-111111111111';REVIEWER='22222222-2222-4222-8222-222222222222'

class MemoryCurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source={'task_id':TASK,'agent_id':AUTHOR,'status':'completed','mode':'planning','lease_status':'closed','content_sha256':'b'*64}
        self.key=nominate(self.root,'https://github.com/acme/example','delivery-kit-one',
            {'subject':'Local storage','decisions':['Use SQLite'],'commit':'a'*40,'source_release':'TEST-1','expires':1000,'supersedes':None},self.source,now=100)
        self.created=[];self.runs=[]
    def create(self,*args,**kwargs):self.created.append((args,kwargs));return 'issue'
    def call(self):
        with patch('memory_curation.observe',return_value=(self.source,'{"technical_decisions":["Use SQLite"]}')):
            return tick(self.root,'https://github.com/acme/example','delivery-kit-one',self.key,REVIEWER,
                cli=lambda *a:self.runs,create=self.create,now=101)
    def test_restart_observes_same_issue_without_recreating(self):
        first=self.call();second=self.call()
        self.assertEqual(first,second);self.assertEqual(len(self.created),1)
        self.assertEqual(first['stage'],'awaiting_native_review')
        self.assertIn(self.key,self.created[0][0][1])
        self.assertFalse(first['delivery_approval'])
    def test_native_failure_is_visible_and_does_not_retry_dispatch(self):
        self.runs=[{'id':'failed','agent_id':REVIEWER,'status':'failed'}]
        self.assertEqual(self.call()['stage'],'blocked')
        self.assertEqual(self.call()['category'],'native_curator_failed')
        self.assertEqual(len(self.created),1)
    def test_ambiguous_native_runs_fail_closed(self):
        self.runs=[{'id':'one','agent_id':REVIEWER,'status':'running'},
                   {'id':'two','agent_id':REVIEWER,'status':'running'}]
        self.assertEqual(self.call()['category'],'ambiguous_native_review')

    def test_failure_is_published_without_starting_another_native_execution(self):
        from memory_curation_cli import publish_terminal
        calls=[]
        publish_terminal({'stage':'blocked','issue_id':'issue','category':'native_curator_failed'},
                         lambda *a:calls.append(a))
        self.assertEqual(calls[-1],('status','issue','blocked','--no-start'))
        self.assertTrue(any('memory_curation_error' in c for c in calls))
