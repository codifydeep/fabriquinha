from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.repairs import reviewed

class ReviewAncestry(unittest.TestCase):
    def test_shared_ancestor_checked_once_per_operation_and_again_next_time(self):
        store,project=Mock(),Mock()
        observations=[]
        def verify(p,s,key):
            observations.append(key)
            if key=='root':
                first=reviewed(p,s,'ancestor')
                first['paths'].append('local modification')
                return reviewed(p,s,'ancestor')
            return {'paths':['verified']}
        with patch('fabriquinha.repairs._verify_review',side_effect=verify):
            for _ in range(2):
                self.assertEqual(reviewed(project,store,'root'),{'paths':['verified']})
        self.assertEqual(observations,['root','ancestor','root','ancestor'])
