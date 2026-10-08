import unittest
import json
import sqlite3
import tempfile
import threading
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker.fenced_patch_diagnosis import describe
from broker import fenced_patch_diagnosis as module, handoffs


class FencedPatchDiagnosisTests(unittest.TestCase):
    def messages(self):
        text=('patch failed for /workspace/tests/test_new.py: Failed to write changes: '
            'ValueError: fenced write size exceeds 32768 bytes; received at least 32769 bytes. '
            'Preserve all assertions. No bytes were changed.')
        return [dict(type='tool_result',tool='patch',output=text) for _ in range(2)]

    def test_exact_write_fence_is_not_test_failure_or_retry_authority(self):
        result=describe(self.messages(),'/workspace/tests/test_new.py')
        self.assertEqual(result['structure']['maximum_bytes'],32768)
        self.assertEqual(result['structure']['rejected_writes'],2)
        self.assertFalse(result['write_executed'])
        self.assertFalse(result['tests_executed'])
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(len(result['tool_result_sha256']),2)

    def test_wrong_path_tool_count_or_constraint_cannot_trigger_diagnosis(self):
        self.assertIsNone(describe(self.messages(),'/workspace/tests/other.py'))
        self.assertIsNone(describe(self.messages()[:1],'/workspace/tests/test_new.py'))
        self.assertIsNone(describe(self.messages()*2,'/workspace/tests/test_new.py'))
        messages=self.messages();messages[0]['tool']='read_file'
        self.assertIsNone(describe(messages,'/workspace/tests/test_new.py'))

    def test_one_changed_diagnosis_is_bound_to_failed_source_and_prior_cto(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con)
        con.executescript('CREATE TABLE leases(request_id TEXT,status TEXT);'
            'CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT);'
            'CREATE TABLE grants(request_id TEXT,mode TEXT);'
            'CREATE TABLE failed_execution_snapshots(task_id TEXT,volume TEXT,status TEXT);'
            'CREATE TABLE test_first_red(issue_id TEXT);')
        con.execute('INSERT INTO leases VALUES (?,?)',('request','closed'))
        con.execute('INSERT INTO native_bindings VALUES (?,?,?)',('request','author-task','issue'))
        con.execute('INSERT INTO grants VALUES (?,?)',('request','implementation'))
        con.execute('INSERT INTO failed_execution_snapshots VALUES (?,?,?)',('author-task','frozen','complete'))
        decision=dict(action='escalate_cto',optional_files=[],reason='Need actual cause')
        data=dict(diagnostic=None,error='test_first_cto_requires_replanning',decision=decision,
            cto_task='cto-task',test_first_cto_wakeup='cto-wake')
        handoffs.save(con,'author-task','issue','test_first_blocked','cto',data,0)
        prior=handoffs.load(con,'author-task')
        source=dict(id='author-task',agent_id='author',issue_id='issue',status='failed',created_at='1')
        cto=dict(id='cto-task',agent_id='cto',wakeup_id='cto-wake',status='completed')
        route=dict(issue_id='issue',author='author',cto='cto',enabled=True,test_first=True,
            test_first_files=['tests/test_new.py'])
        @contextmanager
        def db():yield con
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);(state/'native.json').write_text('{}')
            b=SimpleNamespace(db=db,LOCK=threading.RLock(),STATE=state,OWNER='owner',
                docker=lambda *args:dict(Labels={'delivery-kit.owner':'owner','delivery-kit.source-task':'author-task'}))
            fx=SimpleNamespace(decision=lambda _:decision)
            with patch.object(module.native,'task_messages',return_value=self.messages()):
                self.assertTrue(module.enrich(b,route,[source,cto],source,prior,fx))
                self.assertFalse(module.enrich(b,route,[source,cto],source,prior,fx))
        row=handoffs.load(con,'author-task');updated=json.loads(row['data'])
        self.assertEqual(row['stage'],'technical_decision_required')
        self.assertNotIn('test_first_cto_wakeup',updated)
        self.assertFalse(updated['fenced_patch_diagnosis']['author_retry_authorized'])
        self.assertTrue(module.qualified(con,'issue','author-task',updated))
        self.assertFalse(module.qualified(con,'issue','other-task',updated))
        changed={**updated,'diagnostic':{}}
        self.assertFalse(module.qualified(con,'issue','author-task',changed))
        messages=self.messages();messages[0]['output']=messages[0]['output'].replace('32769','90000')
        self.assertIsNone(describe(messages,'/workspace/tests/test_new.py'))
