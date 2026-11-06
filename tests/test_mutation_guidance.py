from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.control_submission import retained_edit

class RetainedEdit(unittest.TestCase):
    def test_preserves_duplicate_lines_and_exact_whitespace(self):
        old='a\nremove()\nb\nremove()\nc\n'
        for new in (old.replace('b\nremove()', 'b\ncontinue_play()'), old+'added\n', old[2:]):
            edit=retained_edit(old,new)
            self.assertEqual(old.count(edit['before']),1)
            self.assertEqual(old.replace(edit['before'],edit['after'],1),new)
    def test_oversize_edit_omitted(self):
        self.assertIsNone(retained_edit('a'*5000,'b'*5000))
