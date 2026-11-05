"""A bounded tool error must expose the failure before the suite inventory."""
import copy
import json
import sys
from pathlib import Path
from unittest import TestCase
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.quality import refusal_summary

class RefusalSummary(TestCase):
    def test_large_inventory_cannot_hide_actual_failure(self):
        report={'tests_run':62,'errors':[],'skips':[],'expected_failures':[],'unexpected_successes':[],
                'qa_preview':{'status':'failed','failure_kind':'behavior','cases':['long.case.'+str(i) for i in range(1000)],
                              'errors':["AssertionError: 'creator' != 'A'"]}}
        before=copy.deepcopy(report);summary=refusal_summary(report)
        self.assertIn("creator",json.dumps(summary)[:500])
        self.assertNotIn('cases',summary['qa_preview'])
        self.assertEqual(report,before)
    def test_error_budget_is_bounded_and_inventory_count_retained(self):
        report={'tests_run':62,'errors':['x'*5000]*20,'skips':['skip']*30,
                'qa_preview':{'status':'failed','errors':['y'*5000]*20,'cases':list(range(62))}}
        result=refusal_summary(report)
        self.assertLess(len(json.dumps(result)),6500)
        self.assertEqual(result['errors']['count'],20)
        self.assertEqual(result['qa_preview']['case_count'],62)
        self.assertEqual(result['qa_preview']['error_count'],20)
