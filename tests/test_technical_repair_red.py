"""Contract-3 quality lifecycle with synthetic executor evidence, never live jobs."""
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from test_delivery_core import configuration

OLD='''class Legacy(TestCase):
    def test_value(self):
        value = wrong_probe()
        self.assertEqual(value, 1)
'''
NEW=OLD.replace('wrong_probe()', 'correct_probe()')
LEGACY='acceptance_old.Legacy.test_value'
FEATURE='acceptance_new.Feature.test_added'


class TechnicalRepairRed(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);self.store=Store(root/'private');self.work=root/'work';(self.work/'tests').mkdir(parents=True)
        (self.work/'app.py').write_text('VALUE = 0\n')
        (self.work/'tests/acceptance_old.py').write_text(OLD)
        self.baseline=self.store.capture(self.work)
        (self.work/'tests/acceptance_new.py').write_text('class Feature(TestCase):\n def test_added(self):\n  self.assertEqual(value(), 2)\n')
        self.original=self.store.capture(self.work)
        self.project=Project.parse(configuration());self.inputs={};self.jobs=[]
        self.board=SimpleNamespace(ensure=lambda r:None,input=lambda r,k,**kw:self.inputs[k])
        self.q=Quality(self.project,self.store,SimpleNamespace(run=self.execute),self.board)
        self.author=Run('tests',1,'backend','tests',False,'backend','r','contract')
        red=self.q.red(self.author,self.baseline,self.original);self.inputs['red']=red
        self.verdict=dict(decision='approve',reason='Synthetic independent review.',findings=[])
        self.freeze=self.q.tests_review(replace(self.author,number=2,actor='lead',reviewing=True),red,self.verdict)
        self.admission=self.store.record('test_repair_admission',dict(actor='controller',release='r'),{})
        self.authority=dict(review=self.admission,controller_admission=True,
            context=dict(repair_kind='fixture',tests=self.freeze,snapshot=self.original,cases=[LEGACY]),
            proposal=dict(classification='test_contract',test_paths=['tests/acceptance_old.py']))
        (self.work/'tests/acceptance_old.py').write_text(NEW);self.candidate=self.store.capture(self.work)
        self.run=replace(self.author,task='replacement',number=5,contract='replacement')
        self.enterContext(patch('fabriquinha.repairs.repair_authority',return_value=self.authority))
        self.enterContext(patch('fabriquinha.repairs.reviewed',return_value=self.authority))

    def execute(self,run,snapshot,phase):
        cases=[LEGACY]+([FEATURE] if 'tests/acceptance_new.py' in self.store.manifest(snapshot) else [])
        failed=[FEATURE] if phase=='red' else []
        self.jobs.append((snapshot,phase))
        return self.store.record('suite_job',run.binding(),dict(exit_code=int(bool(failed)),
            report=dict(version=1,tests_run=len(cases),cases=cases,failures=[dict(case=c,assertion=True,frames=[dict(file='tests/acceptance_new.py',function='test_added')]) for c in failed],errors=[],skips=[],expected_failures=[],unexpected_successes=[]),
            identity=dict(binding=run.binding(),project=self.project.fingerprint(),snapshot=snapshot,phase=phase,image=self.project.validation_image),
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))

    def test_new_red_freeze_and_ci_preserve_legacy_case_as_mandatory_control(self):
        red=self.q.red(self.run,self.original,self.candidate);self.inputs['red']=red
        record=self.store.receipt(red)
        repaired=record['payload']['fixture_revision']['repaired_baseline']
        self.assertNotEqual(repaired,self.baseline)
        self.assertEqual((self.store.tree(self.baseline)/'tests/acceptance_old.py').read_text(),OLD)
        with self.assertRaises(ValueError):self.q.protect(self.baseline,self.candidate,allow_revision=True)
        frozen=self.q.tests_review(replace(self.run,number=6,actor='lead',reviewing=True),red,self.verdict)
        data=self.q.frozen_plan(self.store.receipt(frozen))
        self.assertEqual(set(data['control_cases']),{LEGACY,FEATURE})
        self.q.protect(self.baseline,self.candidate,allow_revision=True)

    def test_wrong_baseline_projection_cannot_be_frozen(self):
        red=self.q.red(self.run,self.original,self.candidate)
        record=self.store.receipt(red);record['payload']['fixture_revision']['repaired_baseline']=self.original
        forged=self.store.record('red',self.run.binding(),record['payload']);self.inputs['red']=forged
        with self.assertRaises(ValueError):
            self.q.tests_review(replace(self.run,number=6,actor='lead',reviewing=True),forged,self.verdict)

    def test_author_cannot_freeze_own_correction(self):
        red=self.q.red(self.run,self.original,self.candidate);self.inputs['red']=red
        with self.assertRaises(ValueError):
            self.q.tests_review(replace(self.run,number=6,reviewing=True),red,self.verdict)
