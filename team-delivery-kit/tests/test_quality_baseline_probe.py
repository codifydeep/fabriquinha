"""Compatibility diagnostics cannot become native quality approvals."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import quality_baseline_probe as probe
import test_quality_node_baseline as fixtures


class BaselineProbeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NodeBaselineTests();self.fixture.setUp();self.fixture.prepare()
        self.addCleanup(self.fixture.doCleanups)

    def run_probe(self,result,node=None):
        with patch.object(probe,'node_baseline',return_value=node or dict(status='passed',tests_run=2)),\
                patch.object(probe.subprocess,'run',return_value=result) as call:
            value=probe.run(self.fixture.root,self.fixture.manifest,self.fixture.tests)
        return value,call

    def test_both_suites_required_but_even_passing_diagnostic_approves_nothing(self):
        result,call=self.run_probe(SimpleNamespace(returncode=0,stdout=b'',stderr=b'Ran 7 tests in 0.1s\nOK\n'))
        self.assertEqual(result['status'],'passed');self.assertEqual(result['python']['tests_run'],7)
        self.assertFalse(result['native_qualification']);self.assertFalse(result['green_approved'])
        self.assertFalse(result['red_approved']);self.assertFalse(result['delivery_approval'])
        self.assertEqual(call.call_args.args[0][1:],['-m','unittest','discover','-s','.','-q'])

    def test_python_failure_skips_empty_or_ambiguous_counts_never_pass(self):
        for code,output in ((1,b'Ran 7 tests in 1s\nFAILED PRIVATE_DETAIL'),
                (0,b'Ran 7 tests in 1s\nOK (skipped=1)'),(0,b'Ran 0 tests in 1s\nOK'),
                (0,b'Ran 7 tests in 1s\nRan 9 tests in 1s\nOK')):
            with self.subTest(code=code,output=output):
                result,_=self.run_probe(SimpleNamespace(returncode=code,stdout=b'',stderr=output))
                self.assertEqual(result['status'],'rejected');self.assertNotIn('PRIVATE_DETAIL',json.dumps(result))

    def test_node_failure_cannot_be_overridden_by_passing_python(self):
        result,_=self.run_probe(SimpleNamespace(returncode=0,stdout=b'',stderr=b'Ran 7 tests in 1s\nOK'),dict(status='rejected'))
        self.assertEqual(result['status'],'rejected')


if __name__=='__main__':unittest.main()
