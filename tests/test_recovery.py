"""Technical recovery cannot replace delivery gates or mutate the author work."""
from dataclasses import replace
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store, digest
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.quality import Quality
from fabriquinha.effects import EffectBlocked
from fabriquinha.recovery import Diagnostic, Recovery
from test_delivery_core import configuration


class TechnicalRecovery(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.store=Store(self.root/'private')
        self.work=self.root/'work';(self.work/'tests').mkdir(parents=True)
        (self.work/'app.py').write_text('VALUE = 1\n');(self.work/'tests/test_existing.py').write_text('baseline test\n')
        self.snapshot=self.store.capture(self.work)
        settings=configuration();settings['technical_roles']=dict(lead='lead',cto='cto')
        self.project=Project.parse(settings)
        self.original=Run('source',1,'backend','tests',False,'backend','v1','source-contract')
        self.incident=self.store.record('incident',self.original.binding(),dict(project=self.project.fingerprint(),
            snapshot=self.snapshot,source='source',source_run=1,block_event=3,cause='stable-cause',failure='protocol failure'))
        self.run=Run('diagnostic',2,'lead','diagnostic',False,'lead','v1','diagnostic-contract')
        self.board=SimpleNamespace(ensure=lambda run:None,input=lambda *args,**kwargs:self.incident)
        self.quality=Quality(self.project,self.store,None,self.board)
        self.sandbox=SimpleNamespace(project=self.project,store=self.store,board=self.board,run=self.run,
            workspace=self.store.tree(self.snapshot),close=Mock())

    def test_technical_roles_are_optional_immutable_and_independent(self):
        original=configuration();before=Project.parse(original).fingerprint()
        with_roles={**original,'technical_roles':dict(lead='lead',cto='cto')}
        parsed=Project.parse(with_roles);with_roles['technical_roles']['lead']='changed'
        self.assertEqual(parsed.technical_roles['lead'],'lead')
        self.assertEqual(Project.parse(original).fingerprint(),before)
        with self.assertRaises(ValueError):Project.parse({**original,'technical_roles':dict(lead='same',cto='same')})

    def test_review_failure_goes_directly_to_cto_not_ceo_or_the_failed_lead(self):
        recovery=Recovery(self.project,self.store,self.board)
        self.assertEqual(recovery.stage_for(True,'reviewer'),'cto')
        self.assertEqual(recovery.stage_for(False,'lead'),'cto')
        self.assertEqual(recovery.stage_for(False,'backend'),'lead')

    def test_unconfigured_author_cannot_assume_a_technical_role(self):
        self.sandbox.run=replace(self.run,actor='backend')
        with self.assertRaises(ValueError):Diagnostic(self.sandbox,self.quality)

    def test_resume_needs_an_actual_current_experiment_not_a_pass_flag(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        decision=dict(action='resume',reason='Concrete technical guidance',findings=[dict(path='app.py',line=1,detail='Add behavior test')])
        with self.assertRaises(ValueError):diagnostic.decide(decision)
        with self.assertRaises(ValueError):diagnostic.validate(dict(passed=True,hypothesis='invented'))
        self.sandbox.close.assert_not_called()

    def test_spike_mutation_is_disposable_and_cannot_weaken_tests(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        self.quality.observe=Mock(return_value=('real-job',{'cases':['baseline'],'failures':[]}))
        with self.assertRaises(ValueError):diagnostic.validate(dict(hypothesis='cheat',replacements={'tests/test_existing.py':'weakened'}))
        result=diagnostic.validate(dict(hypothesis='Can the baseline detect product change?',replacements={'app.py':'VALUE = 2\n'}))
        receipt=self.store.receipt(result['experiment'],kind='diagnostic_experiment')
        changed=self.store.tree(receipt['payload']['snapshot'])
        self.assertEqual((changed/'app.py').read_text(),'VALUE = 2\n')
        self.assertEqual((self.work/'app.py').read_text(),'VALUE = 1\n')
        self.assertFalse(result['delivery_approval'])

    def test_cto_cannot_escalate_recursively_or_send_technical_decision_to_ceo(self):
        self.sandbox.run=replace(self.run,actor='cto')
        diagnostic=Diagnostic(self.sandbox,self.quality)
        for action in ('escalate','ceo','approve_delivery'):
            with self.subTest(action=action),self.assertRaises(ValueError):
                diagnostic.decide(dict(action=action,reason='technical',findings=[]))

    def test_valid_diagnosis_only_completes_its_own_card_not_the_source(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        self.quality.observe=Mock(return_value=('job',{'cases':['baseline'],'failures':[]}))
        diagnostic.validate(dict(hypothesis='Check original baseline'))
        kb=Mock();kb.complete_task.return_value=True
        with patch('fabriquinha.recovery.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:nullcontext(Mock())),None)):
            result=diagnostic.decide(dict(action='resume',reason='Add the missing behavior test',
                findings=[dict(path='app.py',line=1,detail='Value is not yet tested')]))
        self.assertEqual(kb.complete_task.call_args.args[1],'diagnostic')
        kb.unblock_task.assert_not_called()
        self.assertFalse(result['delivery_approval']);self.sandbox.close.assert_called_once()

    def test_respawn_is_revalidating_not_incident_resolution(self):
        recovery=Recovery(self.project,self.store,self.board)
        task=SimpleNamespace(id='diagnostic',assignee='lead',body=json.dumps(dict(kind='diagnostic',
            stage='lead',source='source',inputs={'incident':self.incident})))
        recovery.cards=lambda conn:[task]
        kb=Mock();kb.get_task.return_value=SimpleNamespace(id='source',status='running',assignee='backend')
        with patch('fabriquinha.recovery.native',return_value=(kb,None,None)):
            status=recovery.status(Mock())
        self.assertEqual(status[0]['state'],'revalidating');self.assertFalse(status[0]['delivery_approval'])

    def test_native_done_without_delivery_evidence_does_not_resolve_incident(self):
        recovery=Recovery(self.project,self.store,self.board)
        task=SimpleNamespace(id='diagnostic',assignee='lead',body=json.dumps(dict(kind='diagnostic',
            stage='lead',source='source',inputs={'incident':self.incident})))
        recovery.cards=lambda conn:[task]
        kb=Mock();kb.get_task.return_value=SimpleNamespace(id='source',status='done',assignee='backend')
        kb.latest_run.return_value=SimpleNamespace(metadata={})
        with patch('fabriquinha.recovery.native',return_value=(kb,None,None)):
            self.assertEqual(recovery.status(Mock())[0]['state'],'evidence_missing')

    def test_third_resume_without_changed_evidence_is_not_an_identical_retry_loop(self):
        recovery=Recovery(self.project,self.store,self.board);tasks=[];runs={}
        for index in range(3):
            original=replace(self.original,number=10+index)
            incident=self.store.record('incident',original.binding(),dict(project=self.project.fingerprint(),
                source='source',source_run=original.number,block_event=20+index,cause='same',snapshot=self.snapshot,failure='same'))
            body=dict(version=1,kind='diagnostic',release='v1',stage='lead',source='source',cause='same',inputs={'incident':incident})
            task=SimpleNamespace(id='diag-'+str(index),assignee='lead',body=json.dumps(body));tasks.append(task)
            run=Run(task.id,30+index,'lead','diagnostic',False,'lead','v1',digest(body))
            experiment=self.store.record('diagnostic_experiment',run.binding(),dict(incident=incident))
            decision=self.store.record('diagnostic_decision',run.binding(),dict(project=self.project.fingerprint(),
                incident=incident,action='resume',experiment=experiment))
            runs[task.id]=SimpleNamespace(id=run.number,outcome='completed',metadata={'diagnosis':decision})
            if index<2:
                identity=dict(diagnosis=decision,source='source',block_event=20+index)
                recovery.journal.do(digest(identity)+':resume',identity,lambda:{'event':99},lambda:None)
        recovery.cards=lambda conn:tasks
        kb=Mock();kb.latest_run.side_effect=lambda conn,ident:runs[ident]
        with patch('fabriquinha.recovery.native',return_value=(kb,None,None)):
            with self.assertRaisesRegex(EffectBlocked,'two recoveries'):recovery.apply(Mock(),tasks[-1])
        kb.unblock_task.assert_not_called()


if __name__=='__main__':unittest.main()
