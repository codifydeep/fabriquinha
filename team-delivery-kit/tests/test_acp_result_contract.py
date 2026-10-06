import unittest
from broker.acp_result_contract import require_success
from broker.install_acp_result_contract import adapt, RESULT, EXCEPTION, EXECUTOR


class ACPResultContractTests(unittest.TestCase):
    def test_structured_failure_is_not_completed_even_with_plausible_previous_text(self):
        for result in ({'failed':True,'completed':False,'final_response':'I will continue now.'},
                       {'completed':False,'final_response':'Done'},
                       {'failed':True,'failure_reason':'timeout','error':'PRIVATE PROVIDER BODY'}):
            with self.subTest(result=result),self.assertRaisesRegex(RuntimeError,'hermes_run_failed') as error:
                require_success(result)
            self.assertNotIn('PRIVATE',str(error.exception))

    def test_success_and_cancellation_do_not_depend_on_prose_keywords(self):
        success=dict(completed=True,failed=False,final_response='Test the error and timeout branches.')
        self.assertIs(require_success(success),success)
        self.assertIs(require_success({'completed':False,'interrupted':True},interrupted=True).__class__,dict)
        with self.assertRaises(RuntimeError):require_success({'failed':True},interrupted=True)
        with self.assertRaises(RuntimeError):require_success(None)

    def source(self):
        return ('class Server:\n    async def prompt(self, state, result):\n'+RESULT+
                '        def run_agent():\n'
                '            try:\n                pass\n'
                '            except Exception as e:\n'+EXCEPTION+
                '        try:\n            pass\n        except Exception:\n'+EXECUTOR)

    def test_patch_is_exact_and_cannot_silently_drift_or_double_install(self):
        source=self.source();patched=adapt(source)
        self.assertIn('require_success(result',patched)
        self.assertIn('hermes_executor_failed',patched)
        self.assertNotIn('f"Error: {e}"',patched)
        for changed in (source+RESULT,source.replace(EXCEPTION,'                return {}\n'),patched):
            with self.assertRaises(ValueError):adapt(changed)
