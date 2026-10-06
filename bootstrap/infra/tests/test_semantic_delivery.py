import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from semantic_delivery import CLAIMS,check_claims,render,verify

class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'score.py').write_text('def winner(a,b): return "A" if a>=12 else "B" if b>=12 else None')
        (self.root/'test_score.py').write_text('test fixture')
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        (self.root/'runner-green.json').write_text(json.dumps(dict(accepted=True,tests_run=6,returncode=0,
            score_sha256=sha(self.root/'score.py'),tests_sha256={'test_score.py':sha(self.root/'test_score.py')})))

    def test_unsupported_claims_rejected(self):
        for content in ['Jogo 3D entregue e deploy saudável',json.dumps(dict(CLAIMS,deployment='homologated')),json.dumps(dict(CLAIMS,ui='3D'))]:
            with self.assertRaises(ValueError): check_claims(content)
        check_claims(json.dumps(CLAIMS))

    def test_only_evidence_bound_document_is_valid(self):
        (self.root/'DELIVERY_NOTES.md').write_text(render(self.root,'t_test'))
        self.assertTrue(verify(self.root,'t_test')['valid'])
        with (self.root/'DELIVERY_NOTES.md').open('a') as out: out.write('\nAll product requirements delivered.')
        with self.assertRaises(ValueError): verify(self.root,'t_test')

    def test_changed_code_or_wrong_card_rejected(self):
        (self.root/'DELIVERY_NOTES.md').write_text(render(self.root,'t_test'))
        with self.assertRaises(ValueError): verify(self.root,'t_other')
        (self.root/'score.py').write_text('def winner(a,b): return None')
        with self.assertRaises(ValueError): verify(self.root,'t_test')
