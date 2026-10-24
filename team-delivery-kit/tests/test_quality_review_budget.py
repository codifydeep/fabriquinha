"""Bounded review transport only; never a read or approval receipt."""
from dataclasses import dataclass,replace
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch
import quality_review_budget as budget
import quality_review_paging as paging
from install_quality_review_stop import adapt_tool_budget,TOOL_BUDGET_ANCHOR
import test_quality_review_stop as fixtures


@dataclass(frozen=True)
class FixtureBudget:
    default_result_size:int=100000
    turn_budget:int=200000
    preview_size:int=1500
    mcp_result_size:int=50000
    tool_overrides:dict|None=None


class QualityReviewBudgetTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityReviewStopTests();f.setUp();self.env=f.env;self.request=f.request

    def test_review_preserves_bounded_pages_not_global_tool_or_model_limits(self):
        original=FixtureBudget(tool_overrides={'other':123})
        actual=budget.for_review(original,self.env)
        self.assertEqual(actual.turn_budget,paging.MAX_BYTES)
        self.assertEqual(replace(actual,turn_budget=original.turn_budget),original)
        self.assertEqual(original.turn_budget,200000)
        self.assertIs(actual.tool_overrides,original.tool_overrides)

    def test_legacy_and_implementation_budgets_remain_identical(self):
        original=FixtureBudget()
        self.assertIs(budget.for_review(original,{}),original)
        phase=dict(version=2,phase='implementation_v2',request_id=self.request,
            editable_paths=['/workspace/app.py'],read_paths=['/workspace/app.py'])
        import json
        env={**self.env,'DELIVERY_EXECUTION_MODE':'implementation','DELIVERY_QUALITY_PHASE_JSON':json.dumps(phase)}
        self.assertIs(budget.for_review(original,env),original)

    def test_invalid_identity_bool_or_unbounded_budget_fails_closed(self):
        for base in (FixtureBudget(turn_budget=True),FixtureBudget(turn_budget=0),
                FixtureBudget(turn_budget=paging.MAX_BYTES+1),SimpleNamespace(turn_budget=200000)):
            with self.assertRaises(ValueError):budget.for_review(base,self.env)
        with self.assertRaises(ValueError):budget.for_review(FixtureBudget(),{**self.env,'DELIVERY_MODEL_EXECUTION_ID':'foreign'})

    def test_installed_executor_hook_preserves_fallback_and_rejects_drift(self):
        source='def _budget_for_agent(agent):\n'+TOOL_BUDGET_ANCHOR
        namespace=dict(budget_for_context_window=lambda n:FixtureBudget(),DEFAULT_BUDGET=FixtureBudget())
        exec(compile(adapt_tool_budget(source),'tool_budget_fixture','exec'),namespace)
        with patch.dict(os.environ,self.env,clear=True):
            actual=namespace['_budget_for_agent'](SimpleNamespace(context_compressor=SimpleNamespace(context_length=200000)))
            self.assertEqual(actual.turn_budget,paging.MAX_BYTES)
            namespace['budget_for_context_window']=lambda n:1/0
            self.assertEqual(namespace['_budget_for_agent'](SimpleNamespace()).turn_budget,paging.MAX_BYTES)
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(namespace['_budget_for_agent'](SimpleNamespace()).turn_budget,200000)
        for changed in (source+TOOL_BUDGET_ANCHOR,source.replace(TOOL_BUDGET_ANCHOR,''),adapt_tool_budget(source)):
            with self.assertRaises(ValueError):adapt_tool_budget(changed)


if __name__=='__main__':unittest.main()
