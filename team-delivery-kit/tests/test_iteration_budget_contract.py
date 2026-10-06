import unittest
from unittest.mock import patch

from broker.iteration_budget_contract import bounded_failure
from broker.install_iteration_budget_contract import adapt
from broker.acp_result_contract import require_success

SOURCE = '''import os
def finalize_turn():
    iteration_limit_fallback = False
    preserved_verification_fallback = False
    if continuation_budget_exhausted:
        final_response = "pending"
    elif budget_fallback_eligible:
        final_response = agent._handle_max_iterations(messages, api_call_count)
    cleanup()
    result = {"failed":failed}
    return result
'''


class IterationBudgetContractTests(unittest.TestCase):
    def test_only_controller_exhausted_fallback_is_failed(self):
        for mode in ('implementation','review','diagnostic'):
            self.assertTrue(bounded_failure(mode,True))
            self.assertFalse(bounded_failure(mode,False))
        for mode in (None,'chat','unknown'):
            self.assertFalse(bounded_failure(mode,True))

    def test_installer_preserves_cleanup_and_legacy_summary(self):
        changed=adapt(SOURCE)
        self.assertIn('cleanup()',changed)
        self.assertIn('agent._handle_max_iterations(messages, api_call_count)',changed)
        self.assertIn('result["failure_reason"] = "iteration_budget_exhausted"',changed)
        compile(changed,'<fixture>','exec')

    def test_unknown_or_already_installed_sources_refused(self):
        for source in (SOURCE.replace('    return result','    return other'),
                SOURCE+SOURCE,adapt(SOURCE)):
            with self.assertRaises(ValueError):adapt(source)

    def test_acp_surfaces_exhaustion_not_success(self):
        with self.assertRaisesRegex(RuntimeError,'hermes_run_failed:iteration_budget_exhausted'):
            require_success({'failed':True,'completed':False,
                             'failure_reason':'iteration_budget_exhausted'})

    def test_guard_does_not_call_model_and_marks_failure(self):
        import ast,os
        changed=adapt(SOURCE);tree=ast.parse(changed)
        function=tree.body[1]
        # Execute the actual injected branch through the unchanged cleanup boundary.
        prefix=function.body[:next(i for i,n in enumerate(function.body)
            if isinstance(n,ast.Expr))]
        code=compile(ast.fix_missing_locations(ast.Module(body=prefix,type_ignores=[])),
                     '<guard>','exec')
        from types import SimpleNamespace
        from unittest.mock import Mock
        summary=Mock(side_effect=AssertionError('must not call model'))
        state={'continuation_budget_exhausted':False,'budget_fallback_eligible':True,
               'failed':False,'messages':[],'api_call_count':40,
               'agent':SimpleNamespace(_handle_max_iterations=summary),'os':os}
        with patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'implementation'}), \
                patch.dict('sys.modules',{'iteration_budget_contract':__import__(
                    'broker.iteration_budget_contract',fromlist=['bounded_failure'])}):
            exec(code,state)
        summary.assert_not_called()
        self.assertTrue(state['failed']);self.assertEqual(state['final_response'],'')
        self.assertTrue(state['iteration_limit_fallback'])
