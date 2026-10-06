import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from product_recovery_approval import approved_maintenance

class ApprovalTests(unittest.TestCase):
    def test_exact_approved_target_and_no_ambiguity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'team-packets').mkdir()
            c=SimpleNamespace(root=root,cfg={'cards':{'new':{'scope':'coordination'}}})
            (root/'team-packets/new.json').write_text(json.dumps(dict(target_task='original',draft_sha256='sha')))
            c.decision=lambda tid:(dict(action='maintain_tests',head='base',specification=dict(target_task='original',draft_sha256='sha')),dict(decision='approve'))
            self.assertEqual(approved_maintenance(c,'original',dict(base='base'),'sha'),'new')
            self.assertIsNone(approved_maintenance(c,'original',dict(base='base'),'changed'))
            self.assertIsNone(approved_maintenance(c,'original',dict(base='different'),'sha'))
            c.cfg['cards']['duplicate']={'scope':'coordination'}
            (root/'team-packets/duplicate.json').write_text((root/'team-packets/new.json').read_text())
            with self.assertRaises(PermissionError):approved_maintenance(c,'original',dict(base='base'),'sha')
