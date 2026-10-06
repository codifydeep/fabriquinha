import ast
from pathlib import Path
import unittest


class BrowserFailureTelemetryTests(unittest.TestCase):
    def helpers(self):
        source=Path(__file__).resolve().parents[1]/'browser_feedback_acceptance.py'
        tree=ast.parse(source.read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.Import) and any(a.name=='json' for a in n.names)
               or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='LAST_ERRORS' for t in n.targets)
               or isinstance(n,ast.FunctionDef) and n.name in ('record_browser_error','failure_output')]
        ns={};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
        return ns

    def test_locator_failure_preserves_real_runtime_exception_first(self):
        ns=self.helpers();ns['record_browser_error']("Cannot read properties of undefined (reading 'toggle')")
        result=ns['failure_output'](AssertionError('status remained empty'))
        self.assertEqual(result['status'],'failed')
        self.assertIn('toggle',result['error'])
        self.assertIn('status remained empty',result['error'])
        self.assertLess(result['error'].index('toggle'),result['error'].index('status remained empty'))

    def test_runtime_collection_is_bounded_and_never_invents_events(self):
        ns=self.helpers()
        self.assertNotIn('Browser runtime errors',ns['failure_output'](ValueError('locator'))['error'])
        for _ in range(10):ns['record_browser_error']('x'*1000)
        self.assertEqual(len(ns['LAST_ERRORS']),8)
        self.assertTrue(all(len(s)==500 for s in ns['LAST_ERRORS']))

    def test_actual_error_stack_is_kept_without_unbounded_data(self):
        ns=self.helpers()
        class Error:
            stack='TypeError: toggle\n at setStatus (http://fixture:8080/static/app.js:24:20)'
            def __str__(self):return 'toggle'
        ns['record_browser_error'](Error())
        self.assertIn('app.js:24:20',ns['failure_output'](AssertionError('status'))['error'])
