import copy
import unittest
from service_mode_harness_observation import facts,instrument


class ObservationTests(unittest.TestCase):
    def reports(self):
        original=dict(executed=True,error=None,after_ok={'calls':1},pending_observed={'calls':1},
            pending_issued=1,timer_count=0,interval_count=1,pending_timer_count=0,
            pending_interval_count=1,mode_request_total=9,unrelated={'unchanged':True})
        measured=copy.deepcopy(original)
        measured['controller_observation']=dict(captures=[dict(kind='interval',load_id=1,slice_start=0,total=1)],
            timers=[dict(ms=2000,load_id=1,stack=['    at /delivery/app/static/app.js:686:1'])])
        return original,measured

    def test_original_failure_values_are_preserved_not_filtered(self):
        a,b=self.reports();r=facts(a,b)
        self.assertEqual(r['original_report']['interval_count'],1)
        self.assertTrue(r['instrumentation_preserved_report'])
        self.assertIn('unrelated',a);self.assertIn('controller_observation',b)

    def test_any_original_field_change_rejects_observation(self):
        a,b=self.reports();b['unrelated']['unchanged']=False
        with self.assertRaises(ValueError):facts(a,b)

    def test_reject_raw_source_arbitrary_trace_or_unbounded_data(self):
        for change in ('source','count','extra'):
            a,b=self.reports()
            if change=='source':b['controller_observation']['timers'][0]['stack']=['secret or arbitrary source']
            elif change=='count':b['controller_observation']['captures']*=129
            else:b['controller_observation']['timers'][0]['code']='untrusted'
            with self.subTest(change=change),self.assertRaises(ValueError):facts(a,b)

    def test_unknown_template_is_rejected_without_partial_execution(self):
        with self.assertRaises(ValueError):instrument('some source')
