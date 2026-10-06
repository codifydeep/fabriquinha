import copy
import unittest
from broker.harness_selector_spike import validate_reports,HypothesisRejected


class SelectorExperimentTests(unittest.TestCase):
    def setUp(self):
        empty=dict(executed=True,error=None,total_search=0,outside_form=0,inside_form=0,type=None,name=None)
        positive=dict(executed=True,error=None,total_search=1,outside_form=1,inside_form=0,type='search',name='Search feedback')
        names=['original_quoted','equivalent_unquoted','wrong_type_control','inside_form_control','wrong_label_control','nonexistent_type_control']
        self.reports={n:dict(empty) for n in names+['adapted_'+n for n in names]}
        for n in ('all_inputs_diagnostic','adapted_original_quoted','adapted_equivalent_unquoted'):
            self.reports[n]=dict(positive)
        self.reports['adapted_inside_form_control'].update(total_search=1,inside_form=1)

    def test_complete_positive_and_negative_controls_qualify_experiment_not_delivery(self):
        before=copy.deepcopy(self.reports)
        self.assertIsNone(validate_reports(self.reports))
        self.assertEqual(before,self.reports)

    def test_missing_control_false_execution_or_false_positive_is_rejected(self):
        for name,key,value in [('adapted_wrong_type_control','total_search',1),
            ('adapted_nonexistent_type_control','total_search',1),
            ('adapted_inside_form_control','outside_form',1),
            ('adapted_wrong_label_control','name','Search feedback'),
            ('adapted_original_quoted','executed',False),
            ('adapted_equivalent_unquoted','error','runtime failure')]:
            reports=copy.deepcopy(self.reports);reports[name][key]=value
            with self.assertRaises(HypothesisRejected):validate_reports(reports)
        missing=copy.deepcopy(self.reports);missing.pop('wrong_type_control')
        with self.assertRaises(HypothesisRejected):validate_reports(missing)
