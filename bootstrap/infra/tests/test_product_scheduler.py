import sqlite3,unittest
from product_scheduler import candidates

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
    def task(self,tid,profile,mode='ready',scope='product'):
        return dict(task=tid,profile=profile,status=mode,scope=scope)
    def test_two_slots_distinct_profiles_no_reserved_idle_slot(self):
        jobs=[self.task('a','backend_data'),self.task('b','backend_data'),self.task('c','frontend')]
        self.assertEqual([t['task'] for t in candidates(self.db,jobs,[],2,1000)],['a','c'])
        self.assertEqual(candidates(self.db,jobs,[dict(task='active',profile='backend_data')],1,1001),[])
    def test_old_implementation_eventually_beats_new_review(self):
        old=self.task('old','backend_data')
        candidates(self.db,[old],[dict(task='busy',profile='cto')],1,1000)
        new=self.task('review','techlead','review')
        self.assertEqual(candidates(self.db,[old,new],[],1,2000)[0]['task'],'old')
    def test_new_review_has_bounded_preference_and_blocked_is_not_eligible(self):
        jobs=[self.task('a','backend_data'),self.task('b','frontend','blocked'),self.task('r','techlead','review')]
        self.assertEqual(candidates(self.db,jobs,[],1,1000)[0]['task'],'r')
    def test_limit_not_above_two_and_invalid_profile_ignored(self):
        with self.assertRaises(ValueError):candidates(self.db,[],[],3,1000)
        self.assertEqual(candidates(self.db,[self.task('bad','unknown')],[],2,1000),[])
