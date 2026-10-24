import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fabriquinha.quality import review_decision


class ReviewDecisionBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'app.py').write_text('line one\nline two\n')
        self.manifest = {'app.py': {}}

    def parse(self, **updates):
        value = dict(decision='approve', reason='Contract satisfied', findings=[])
        return review_decision({**value, **updates}, self.manifest, self.root)

    def test_change_request_requires_concrete_findings(self):
        with self.assertRaises(ValueError):
            self.parse(decision='changes')

    def test_ambiguous_duplicate_keys_are_rejected(self):
        value = '{"decision":"changes","decision":"approve","reason":"ok","findings":[]}'
        with self.assertRaises(ValueError):
            review_decision(value, self.manifest, self.root)

    def test_approval_cannot_hide_unresolved_findings(self):
        with self.assertRaises(ValueError):
            self.parse(findings=[dict(path='app.py', line=1, detail='broken')])

    def test_changed_or_external_file_is_not_a_valid_finding(self):
        for path, line in [('../outside.py', 1), ('app.py', 3), ('app.py', True)]:
            with self.subTest(path=path, line=line), self.assertRaises(ValueError):
                self.parse(decision='changes', findings=[dict(path=path, line=line, detail='broken')])

    def test_real_snapshot_finding_is_accepted_without_reading_entire_repository(self):
        value = self.parse(decision='changes', findings=[dict(path='app.py', line=2, detail='contract differs')])
        self.assertEqual(value['decision'], 'changes')


if __name__ == '__main__':
    unittest.main()
