"""Incomplete diagnostic output must never become delivery evidence."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.suite import Result
from fabriquinha.validation_trace import traced_result
from fabriquinha.executor import validation_output, job_failure
from fabriquinha.quality import Quality


class ValidationProgress(unittest.TestCase):
    def test_events_flush_outside_redirected_test_output(self):
        class Cases(unittest.TestCase):
            def runTest(self):self.fail('behavior missing')
        output=io.StringIO()
        with patch('sys.__stdout__',output):
            result=traced_result(Result)();Cases().run(result)
        report,events=validation_output(output.getvalue())
        self.assertIsNone(report)
        self.assertEqual([e['event'] for e in events],['test_started','test_finished'])
        self.assertGreaterEqual(events[-1]['elapsed_seconds'],0)
        self.assertEqual(len(result.failures),1)

    def test_legacy_and_instrumented_reports_match(self):
        raw=json.dumps({'version':1,'tests_run':2,'failures':[]})
        old,_=validation_output(raw)
        new,events=validation_output('FABRIQUINHA_PROGRESS {"event":"stage"}\n'+raw)
        self.assertEqual(old,new);self.assertEqual(len(events),1)

    def test_partial_or_fake_progress_never_creates_report(self):
        report,events=validation_output('FABRIQUINHA_PROGRESS {"status":"passed"}\n')
        self.assertIsNone(report)
        report,_=validation_output('unexpected output\n{"version":1}')
        self.assertIsNone(report)
        _,events=validation_output('FABRIQUINHA_PROGRESS {"event":"stage"}\n'*300)
        self.assertEqual(len(events),256)

    def test_quality_remembers_underlying_job_even_if_agent_catches_error(self):
        quality=Quality.__new__(Quality);quality.board=Mock();quality.runner=Mock()
        error=job_failure('persistent runtime','a'*64)
        quality.runner.run.side_effect=error
        with self.assertRaisesRegex(Exception,'validation job receipt'):
            quality.observe(Mock(),'snapshot','red')
        self.assertEqual(quality.suite_refusal,'a'*64)
