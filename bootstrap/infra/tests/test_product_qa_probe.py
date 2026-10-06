import unittest
from product_qa_probe import validate,CASES

class QATests(unittest.TestCase):
    def test_all_cases_and_exact_commit(self):
        def fetch(path):
            _,status,value=next(c for c in CASES if c[0]==path)
            return status,dict(commit='a'*40,status='ok',capacity=value)
        self.assertTrue(validate(fetch,'a'*40)['passed'])
        self.assertFalse(validate(fetch,'b'*40)['passed'])
    def test_wrong_capacity_fails(self):
        def fetch(path):return 200,dict(commit='a'*40,status='ok',capacity=True)
        self.assertFalse(validate(fetch,'a'*40)['passed'])
