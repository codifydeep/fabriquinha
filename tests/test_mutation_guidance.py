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

    def test_compact_repair_retains_order_and_refuses_omitted_survivors_or_stale_source(self):
        from unittest.mock import Mock
        from fabriquinha.control_submission import repair_proposals
        store=Mock();targets=[{'a':'refusal'},{'b':'turn'}]
        store.receipt.return_value={'payload':{'snapshot':'s','freeze':'f','green':'g','mutants':['one','two'],'targets':targets}}
        old_edit={'app.py':{'before':'old','after':'bad'}}
        replacement={'app.py':{'before':'next','after':'wrong'}}
        prior={'submission':'sealed','green':'g','freeze':'f','controls':[
            dict(index=1,survived=False,edits=old_edit,observed=['a'],targets=targets[0]),
            dict(index=2,survived=True,edits={},observed=[],targets=targets[1])]}
        self.assertEqual(repair_proposals(store,prior,'s','f',{'2':replacement}),
                         dict(mutations=[old_edit,replacement],targets=targets))
        for source,freeze,edits in [('s','other',{'2':replacement}),('other','f',{'2':replacement}),
                                    ('s','f',{}),('s','f',{'1':replacement,'2':replacement})]:
            with self.assertRaises(ValueError):repair_proposals(store,prior,source,freeze,edits)
