import unittest
from product_roadmap import eligible,validate_spec
from product_capabilities import preflight

class RoadmapTests(unittest.TestCase):
    def test_dependencies_need_accepted_work_not_chat_or_worker(self):
        graph={'a':{'parents':[]},'b':{'parents':['a']},'c':{'parents':['a']}}
        self.assertEqual(eligible(graph,[]),['a']);self.assertEqual(eligible(graph,['a']),['b','c'])
    def test_registry_entry_is_not_execution_capability(self):
        with self.assertRaises(PermissionError):preflight('frontend',{'adapter':'lobby-ts','image':'sha256:'+'a'*64})
        self.assertTrue(preflight('frontend',{'adapter':'lobby-ts','image':'sha256:'+'a'*64,'validated_receipt':'proof'}))
    def test_planner_cannot_dispatch_unavailable_or_complete_unfinished(self):
        packet=dict(eligible=['a'],available_capabilities=['backend'],integrated_children={'a':['t1']},busy_parents=['a'])
        with self.assertRaises(PermissionError):validate_spec(packet,'dispatch_work',dict(parent='a',title='Build component',brief='x'*120,capability='frontend',tdd_mode='feature'))
        with self.assertRaises(PermissionError):validate_spec(packet,'accept_work_item',dict(parent='a',deliveries=['t1'],reason='x'*120))
        packet['busy_parents']=[]
        validate_spec(packet,'accept_work_item',dict(parent='a',deliveries=['t1'],reason='x'*120))
