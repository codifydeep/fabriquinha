"""The controller, not model text, derives reviewer conflicts from receipts."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from test_delivery_core import configuration
from fixtures.control_evidence import frozen_evidence


class ReviewerConflicts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name)/'private')
        self.project = Project.parse({**configuration(), 'reviewers': {'backend':['lead','cto']}})
        self.run = Run('implementation',1,'backend','implementation',False,'backend','v1','contract')
        source = Path(folder.name)/'source'; source.mkdir()
        (source/'app.py').write_text('VALUE = 1\n')
        snapshot=self.store.capture(source)
        test_author=Run('tests',1,'lead','tests',False,'lead','v1','test-contract')
        self.frozen=frozen_evidence(self.store,self.project,test_author,snapshot,snapshot,'cto')
        self.green = self.store.record('green', self.run.binding(), dict(
            project=self.project.fingerprint(), freeze=self.frozen))
        self.controls = self.store.record('controls', self.run.binding(), dict(
            project=self.project.fingerprint(), green=self.green))
        self.calls = []
        board = SimpleNamespace(ensure=lambda run:None, input=lambda run,name:self.frozen,
            review=lambda *args, **kwargs:self.calls.append((args,kwargs)))
        self.quality = Quality(self.project,self.store,None,board)

    def test_test_author_is_excluded_from_implementation_handoff(self):
        self.quality.handoff(self.run, 'Review delivery', {'green':self.green,'controls':self.controls})
        self.assertEqual(self.calls[0][1], {'exclude':('lead',)})

    def test_old_run_or_controls_for_another_green_cannot_be_handed_off(self):
        for kind, binding, payload in (
                ('green', {**self.run.binding(), 'number':0}, dict(project=self.project.fingerprint(),freeze=self.frozen)),
                ('controls', self.run.binding(), dict(project=self.project.fingerprint(),green='other'))):
            receipt = self.store.record(kind,binding,payload)
            evidence = {'green':self.green,'controls':self.controls,kind:receipt}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.quality.handoff(self.run,'Review delivery',evidence)
        self.assertEqual(self.calls,[])
