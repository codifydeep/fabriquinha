import copy
import unittest
from broker.harness_candidate_probe import preserve_assertions, validate_reports,selector_template,SELECTOR,validate_internal_negatives


class CandidateProbeTests(unittest.TestCase):
    def test_internal_negatives_reject_broken_parser_and_missing_containment(self):
        controls=[{'name':name,'canonical_match':canonical,'accepted':False,
                   'rejected_by_predicate':True} for name,canonical in
                  [('wrong_type_text',False),('wrong_type_number',False),
                   ('wrong_label',True),('blank_label',True),('inside_form',True)]]
        self.assertIsNone(validate_internal_negatives(controls))
        for key,value in [('canonical_match',False),('accepted',True),('rejected_by_predicate',False)]:
            altered=copy.deepcopy(controls);altered[-1][key]=value
            with self.assertRaises(ValueError):validate_internal_negatives(altered)
        for invalid in [None,controls[:-1],controls+[controls[0]],controls[:-1]+[controls[0]]]:
            with self.assertRaises(ValueError):validate_internal_negatives(invalid)

    def setUp(self):
        positive = dict(executed=True, error=None, total_search=1, outside_form=1,
                        inside_form=0, type='search', name='Search feedback')
        empty = dict(executed=True, error=None, total_search=0, outside_form=0,
                     inside_form=0, type=None, name=None)
        self.reports = dict(quoted=dict(positive), unquoted=dict(positive), wrong_type=dict(empty),
            nonexistent_type=dict(empty), inside_form=dict(empty,total_search=1,inside_form=1),
            wrong_label=dict(empty))
        self.old = 'class FeedbackSearchClientTests:\n def test_search(self):\n  self.assertEqual(value, 1)\n'
        self.new = self.old+' def test_negative(self):\n  self.assertEqual(other, 0)\n'

    def test_actual_controls_are_required_and_not_mutated(self):
        before = copy.deepcopy(self.reports)
        self.assertIsNone(validate_reports(self.reports))
        self.assertEqual(before, self.reports)

    def test_false_positive_missing_execution_and_mistyped_counts_rejected(self):
        for name, key, value in [('quoted','total_search',0), ('unquoted','executed',False),
            ('wrong_type','total_search',1), ('nonexistent_type','outside_form',1),
            ('inside_form','outside_form',1), ('wrong_label','name','Search feedback'),
            ('quoted','total_search',True), ('quoted','error','failed')]:
            reports = copy.deepcopy(self.reports); reports[name][key] = value
            with self.assertRaises(ValueError): validate_reports(reports)
        reports = copy.deepcopy(self.reports); reports.pop('wrong_type')
        with self.assertRaises(ValueError): validate_reports(reports)

    def test_existing_methods_and_assertion_expressions_must_survive(self):
        self.assertIsNone(preserve_assertions(self.old,self.new))
        for source in [self.old,self.new.replace('value, 1','value, 0'),
            self.new.replace('test_search','test_renamed'),self.new.replace('self.assertEqual(value, 1)','pass')]:
            with self.assertRaises(ValueError): preserve_assertions(self.old,source)

    def test_duplicate_methods_cannot_hide_replaced_assertions(self):
        with self.assertRaises(ValueError):
            preserve_assertions(self.old,self.new+' def test_search(self):\n  self.assertTrue(True)\n')

    def test_repeated_selector_is_not_a_behavioral_failure(self):
        template=('query '+SELECTOR+'; negative-control '+SELECTOR+'; ')*4
        self.assertEqual(selector_template(template,SELECTOR),template)
        changed=selector_template(template,'input[type=not-real]')
        self.assertNotIn(SELECTOR,changed)
        self.assertEqual(changed.count('input[type=not-real]'),8)
        reports=copy.deepcopy(self.reports);reports['nonexistent_type']['total_search']=1
        with self.assertRaises(ValueError):validate_reports(reports)

    def test_absent_selector_or_non_template_rejected(self):
        for template in ('unrelated',None,[],''):
            with self.assertRaises(ValueError):selector_template(template,SELECTOR)
