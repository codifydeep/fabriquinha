import sqlite3,unittest
from unittest.mock import patch
from product_memory import Memory

class CrossReleaseTests(unittest.TestCase):
    def test_only_current_project_lessons_can_be_explicitly_imported(self):
        with sqlite3.connect(':memory:') as db:
            m=Memory(db)
            base=dict(subject='Decision',text='New accepted option; rejected option failed the cited experiment.',sources=['card:t@sha'],scope='project',valid_until=3000,supersedes=None)
            for i,entry in enumerate((base,dict(base,scope='release'),dict(base,valid_until=1500))):
                m.promote('old',entry,dict(proposal_sha256=str(i)*64,author='techlead',reviewer='quality_security',run=1),now=1000)
            with patch('product_memory.time.time',return_value=2000):
                result=m.historical('new','Decision')
            self.assertEqual(len(result['items']),1)
            self.assertIn('requires_current_independent_review',result['items'][0]['validity'])
            self.assertEqual(m.search('new','',now=2000)['items'],[])
            self.assertFalse(result['authority'])
