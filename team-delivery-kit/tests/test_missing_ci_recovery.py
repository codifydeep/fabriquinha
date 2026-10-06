import json
from pathlib import Path
import tempfile
import unittest
from missing_ci_recovery import recover


class MissingCiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve();self.state='open';self.calls=[];self.suites=0;self.runs=0
        self.head='a'*40;self.base='b'*40
    def api(self,path,method='GET',state=None):
        if method=='PATCH':self.calls.append(state);self.state=state;return {}
        if '/check-suites' in path:return {'total_count':self.suites}
        if '/actions/runs?' in path:return {'total_count':self.runs}
        if '/workflows/' in path:return {'state':'active','path':'.github/workflows/ci.yml'}
        return dict(state=self.state,merged=False,draft=False,
            head=dict(sha=self.head,ref='codex/trial',repo=dict(full_name='owner/repo')),
            base=dict(sha=self.base,ref='main',repo=dict(full_name='owner/repo')))
    def run_recovery(self,api=None):return recover(self.home,'owner/repo',42,'a'*40,'b'*40,api=api or self.api)
    def test_once_same_sha_no_approval(self):
        self.assertTrue(self.run_recovery());self.assertFalse(self.run_recovery())
        self.assertEqual(self.calls,['closed','open'])
        receipt=json.loads(next((self.home/'missing-ci-recovery').glob('*.json')).read_text())
        self.assertFalse(receipt['ci_approval']);self.assertEqual(receipt['phase'],'reopened')
    def test_existing_suite_or_run_never_retriggered(self):
        for attribute in ('suites','runs'):
            setattr(self,attribute,1);self.assertFalse(self.run_recovery());setattr(self,attribute,0)
        self.assertEqual(self.calls,[])
    def test_drift_never_writes(self):
        self.head='c'*40
        with self.assertRaises(ValueError):self.run_recovery()
        self.assertEqual(self.calls,[])
    def test_uncertain_close_not_repeated(self):
        def api(path,method='GET',state=None):
            if method=='PATCH':raise TimeoutError('uncertain')
            return self.api(path,method,state)
        with self.assertRaises(TimeoutError):self.run_recovery(api)
        with self.assertRaisesRegex(ValueError,'uncertain'):self.run_recovery()
        self.assertEqual(self.calls,[])
    def test_ack_lost_after_close_adopts_state_without_second_close(self):
        def api(path,method='GET',state=None):
            result=self.api(path,method,state)
            if state=='closed':raise TimeoutError('ack lost')
            return result
        with self.assertRaises(TimeoutError):self.run_recovery(api)
        self.assertTrue(self.run_recovery());self.assertEqual(self.calls,['closed','open'])
    def test_ack_lost_after_reopen_only_observed(self):
        def api(path,method='GET',state=None):
            result=self.api(path,method,state)
            if state=='open':raise TimeoutError('ack lost')
            return result
        with self.assertRaises(TimeoutError):self.run_recovery(api)
        self.assertFalse(self.run_recovery());self.assertEqual(self.calls,['closed','open'])
