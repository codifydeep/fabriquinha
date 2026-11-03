"""Incomplete diagnostic output must never become delivery evidence."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.suite import Result
from fabriquinha.validation_trace import traced_result
from fabriquinha.executor import validation_output, job_failure
from fabriquinha.quality import Quality


class ValidationProgress(unittest.TestCase):
    def test_http_observation_keeps_case_origin_but_not_query_or_headers(self):
        context=Mock()
        class Acceptance:
            def new_context(self):return context
        fake=SimpleNamespace(AcceptanceTest=Acceptance)
        output=io.StringIO()
        with patch.dict(sys.modules,{'fabriquinha_acceptance':fake}),patch('sys.__stdout__',output):
            result=traced_result(Result)();case=unittest.FunctionTestCase(lambda:None)
            result.startTest(case);Acceptance().new_context()
            callback=next(c.args[1] for c in context.on.call_args_list if c.args[0]=='response')
            callback(SimpleNamespace(status=404,url='http://user:password@local/api/rooms/id?token=secret'))
            result.stopTest(case)
        _,events=validation_output(output.getvalue());event=next(e for e in events if e['event']=='http_error')
        self.assertEqual(event['path'],'/api/rooms/id')
        self.assertEqual(event['context_created_in'],event['case'])
        self.assertNotIn('secret',output.getvalue());self.assertNotIn('password',output.getvalue())

    def test_successful_join_and_failed_transport_are_observed_without_payloads(self):
        context=Mock()
        class Acceptance:
            def new_context(self):return context
        output=io.StringIO()
        with patch.dict(sys.modules,{'fabriquinha_acceptance':SimpleNamespace(AcceptanceTest=Acceptance)}),patch('sys.__stdout__',output):
            result=traced_result(Result)();case=unittest.FunctionTestCase(lambda:None)
            result.startTest(case);Acceptance().new_context()
            callbacks={c.args[0]:c.args[1] for c in context.on.call_args_list}
            request=SimpleNamespace(url='http://local/api/rooms/123/join?secret=hidden',method='POST',post_data='private nickname')
            callbacks['request'](request)
            callbacks['response'](SimpleNamespace(url=request.url,status=200))
            callbacks['requestfailed'](request)
            callbacks['request'](SimpleNamespace(url='https://external/private',method='GET'))
        _,events=validation_output(output.getvalue())
        self.assertEqual([e['event'] for e in events],['test_started','room_request','room_response','room_request_failed'])
        self.assertEqual(events[2]['status'],200)
        self.assertEqual(events[1]['context_id'],events[2]['context_id'])
        self.assertNotIn('hidden',output.getvalue());self.assertNotIn('nickname',output.getvalue());self.assertNotIn('external',output.getvalue())

    def test_resource_counters_are_allowlisted_and_missing_files_are_tolerated(self):
        from fabriquinha.validation_trace import resource_observation
        values=['128','128','1234','536870912','max 7']
        with patch('fabriquinha.validation_trace.Path.read_text',side_effect=values):
            result=resource_observation()
        self.assertEqual(result['pids.current'],'128')
        self.assertEqual(result['pids_limit_hits'],7)
        with patch('fabriquinha.validation_trace.Path.read_text',side_effect=OSError):
            self.assertEqual(resource_observation(),{})

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
