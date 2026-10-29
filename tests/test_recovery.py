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
from fabriquinha.quality import Quality, suite_report
from fabriquinha.effects import EffectBlocked
from fabriquinha.recovery import Diagnostic, Recovery, guidance_context
from test_delivery_core import configuration


class TechnicalRecovery(unittest.TestCase):
    def test_review_probe_feedback_uses_same_admission_before_terminal_decision(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        diagnostic.experiment='new-observation'
        task=SimpleNamespace(body=json.dumps(dict(review_experiment=dict(handoff='original-red'))))
        kb=SimpleNamespace(get_task=lambda *args:task)
        api=(kb,SimpleNamespace(connect_closing=lambda:nullcontext(None)),None)
        with patch('fabriquinha.recovery.native',return_value=api),patch('fabriquinha.repairs.review_reassessment') as gate:
            gate.side_effect=ValueError('new observed outcome required')
            result=diagnostic.review_probe_feedback()['review_reassessment']
            self.assertFalse(result['eligible'])
            self.assertIn('Do not repeat',result['next_action'])
            self.assertFalse(result['delivery_approval'])
            self.assertEqual(gate.call_args.args[-2:],('original-red','new-observation'))
            gate.side_effect=None;gate.return_value={}
            result=diagnostic.review_probe_feedback()['review_reassessment']
            self.assertTrue(result['eligible'])
            self.assertFalse(result['delivery_approval'])
            self.assertIn('independent delivery review',result['next_action'])

    def test_guidance_projection_preserves_failures_and_authority(self):
        failures=[dict(case='new.test',detail='complete assertion and evidence',frames=[{'line':12}])]
        guide=[dict(receipt='decision',verdict={'action':'resume','reason':'exact finding'},
            experiment=dict(job='suite-receipt',snapshot='snapshot',hypothesis='hypothesis',
                report=dict(tests_run=2,cases=['old.test','new.test'],failures=failures,
                    errors=['runtime error'],skips=['skip'],unexpected_successes=['unexpected'],
                    qa_preview=dict(cases=['new.test'],checks=['JOIN'],errors=['browser error'],status='failed'))))]
        before=json.dumps(guide,sort_keys=True)
        view=guidance_context(guide);report=view[0]['experiment']['report']
        self.assertEqual(view[0]['verdict'],guide[0]['verdict'])
        self.assertEqual(view[0]['receipt'],'decision')
        self.assertEqual(view[0]['experiment']['job'],'suite-receipt')
        self.assertEqual(report['failures'],failures)
        for key in ('errors','skips','unexpected_successes'):
            self.assertEqual(report[key],guide[0]['experiment']['report'][key])
        self.assertNotIn('cases',report)
        self.assertEqual(report['case_inventory'],{'receipt':'suite-receipt','count':2})
        self.assertEqual(report['qa_preview']['errors'],['browser error'])
        self.assertEqual(report['qa_preview']['checks'],['JOIN'])
        self.assertEqual(json.dumps(guide,sort_keys=True),before)
        view[0]['experiment']['report']['failures'][0]['detail']='changed'
        self.assertEqual(json.dumps(guide,sort_keys=True),before)

    def test_previous_diagnosis_is_evidence_history_not_inherited_instructions(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        prior=Run('old-cto',9,'cto','diagnostic',False,'cto','v1','old-contract')
        report=dict(tests_run=18,failures=[],errors=[])
        experiment=self.store.record('diagnostic_experiment',prior.binding(),dict(incident=self.incident,snapshot=self.snapshot,job='job',report=report))
        receipt=self.store.record('diagnostic_decision',prior.binding(),dict(project=self.project.fingerprint(),incident=self.incident,
            action='hold',experiment=experiment,verdict=dict(reason='Never replace the old container. Demand another name.',findings=[])))
        current=SimpleNamespace(body=json.dumps(dict(escalated_from=prior.task)))
        kb=SimpleNamespace(get_task=lambda *args:current,latest_run=lambda *args:SimpleNamespace(id=9,summary='old instruction',error=None,metadata={'diagnosis':receipt}))
        with patch('fabriquinha.recovery.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:nullcontext(None)),None)):
            history=diagnostic.evidence()['previous_diagnosis']
        self.assertTrue(history.get('historical_only'))
        self.assertFalse(history['grants_authority'])
        self.assertEqual(history['receipt'],receipt)
        self.assertEqual(history['action'],'hold')
        self.assertEqual(history['experiment']['report'],report)
        self.assertNotIn('Never replace',json.dumps(history))
        self.assertEqual(self.store.receipt(receipt)['payload']['verdict']['reason'],'Never replace the old container. Demand another name.')
        for change in ({'incident':'wrong-incident'},{'project':'foreign'}):
            original=self.store.receipt(receipt)
            bad=self.store.record('diagnostic_decision',prior.binding(),{**original['payload'],**change})
            kb.latest_run=lambda *args:SimpleNamespace(id=9,metadata={'diagnosis':bad})
            with self.subTest(change=change),patch('fabriquinha.recovery.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:nullcontext(None)),None)):
                with self.assertRaisesRegex(ValueError,'scoped predecessor'):diagnostic.evidence()

    def test_integration_experiment_records_current_deployment_facts(self):
        diagnostic=Diagnostic(self.sandbox,self.quality);diagnostic.original={**diagnostic.original,'kind':'integration'}
        self.quality.observe=Mock(return_value=('job',dict(tests_run=18,failures=[],errors=[])))
        observed=dict(current_is_previous_homologation=True,delivery_approval=False)
        with patch.object(diagnostic,'deployment_observation',create=True,return_value=observed):
            result=diagnostic.validate(dict(hypothesis='Check current integration preconditions without modifying code'))
        self.assertEqual(result.get('deployment_observation'),observed)
        self.assertEqual(self.store.receipt(result['experiment'])['payload']['deployment_observation'],observed)

    def test_lead_hold_escalates_without_unblocking_but_cto_hold_stays_terminal(self):
        recovery=Recovery(self.project,self.store,self.board);recovery.create=Mock();kb=Mock()
        for stage,actor in (('lead','lead'),('cto','cto')):
            body=dict(version=1,kind='diagnostic',release='v1',stage=stage,inputs={'incident':self.incident})
            task=SimpleNamespace(id='held-'+stage,assignee=actor,body=json.dumps(body))
            run=Run(task.id,10,actor,'diagnostic',False,actor,'v1',digest(body))
            decision=self.store.record('diagnostic_decision',run.binding(),dict(project=self.project.fingerprint(),incident=self.incident,action='hold'))
            kb.latest_run.return_value=SimpleNamespace(id=10,outcome='completed',metadata={'diagnosis':decision})
            recovery.create.reset_mock()
            conn=Mock()
            with patch('fabriquinha.recovery.native',return_value=(kb,None,None)):
                recovery.apply(conn,task)
            if stage=='lead':recovery.create.assert_called_once_with(conn,self.incident,'cto',previous=task.id)
            else:recovery.create.assert_not_called()
            kb.unblock_task.assert_not_called()

    def test_integration_diagnosis_has_fixed_safe_deployment_observation(self):
        from dataclasses import replace
        diagnostic=Diagnostic(self.sandbox,self.quality)
        diagnostic.original={**diagnostic.original,'kind':'integration'}
        diagnostic.q=SimpleNamespace(project=replace(self.project,delivery_roles={'tests':'backend','integration':'lead'}))
        kb=SimpleNamespace(get_task=lambda *args:SimpleNamespace(body='{}'))
        current=dict(container='container',image='image',artifact='artifact',url='http://127.0.0.1:1234',healthy=True,network='qa')
        with patch('fabriquinha.recovery.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:nullcontext(None)),None)), \
             patch('fabriquinha.deployment.Deployment') as deployment,patch('fabriquinha.intake.Intake') as intake:
            deployment.return_value.continuity_observation.return_value=dict(current=current,delivery_approval=False)
            intake.return_value.previous.return_value={'historical_only':True,'acceptance':'prior'}
            observed=diagnostic.evidence()['deployment_observation']
            self.assertEqual(observed['current'],current);self.assertFalse(observed['delivery_approval'])
            self.assertEqual(observed['group'],self.project.namespace+'-homologation')
            intake.return_value.previous.assert_called_once_with(self.run.release)
            deployment.return_value.continuity_observation.side_effect=EffectBlocked('foreign sandbox')
            unavailable=diagnostic.evidence()['deployment_observation']
            self.assertEqual(unavailable['state'],'unavailable');self.assertNotIn('current',unavailable)

    def test_forbidden_diagnostic_write_identifies_phase_and_next_permitted_operation(self):
        diagnostic=Diagnostic(self.sandbox,self.quality);self.quality.observe=Mock(return_value=('observed',dict(failures=[])))
        with self.assertRaises(ValueError) as error:
            diagnostic.validate(dict(hypothesis='Attempt a test change',replacements={'tests/test_existing.py':'weakened'}))
        self.assertIn('operation_forbidden',str(error.exception));self.assertIn('without replacements',str(error.exception))
        self.quality.observe.assert_not_called()
        records=[self.store.receipt(p.stem) for p in (self.store.root/'receipts').glob('*.json')]
        refusal=next(r for r in records if r['kind']=='diagnostic_refusal')
        self.assertEqual(refusal['payload']['next_operation'],'diagnostic_validate_without_replacements')
        self.assertFalse(refusal['payload']['delivery_approval'])
        diagnostic.validate(dict(hypothesis='Observe the current immutable suite'))
        self.quality.observe.assert_called_once_with(self.run,self.snapshot,'diagnostic')
        self.assertEqual((self.work/'tests/test_existing.py').read_text(),'baseline test\n')

    def test_qa_correction_diagnosis_executes_the_preview_and_cannot_direct_product_writes(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        diagnostic.repair=dict(proposal=dict(classification='test_contract',test_paths=['tests/qa.json']))
        self.quality.observe=Mock(return_value=('observed-job',dict(qa_preview={'status':'failed','errors':['AC2 exact text mismatch']})))
        diagnostic.validate(dict(hypothesis='Reproduce the current QA mismatch without changing source'))
        self.quality.observe.assert_called_once_with(self.run,self.snapshot,'green')
        with self.assertRaisesRegex(ValueError,'outside'):
            diagnostic.decide(dict(action='resume',reason='Change product wording',findings=[dict(path='app.py',line=1,detail='Edit the app')]))
        self.assertEqual((self.work/'app.py').read_text(),'VALUE = 1\n')

    def test_controller_test_repair_diagnosis_reads_original_plan_for_brief(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        proposed=self.store.record('work_plan',self.run.binding(),{'approval':'business-approval'})
        plan=self.store.record('plan_review',self.run.binding(),{'plan':proposed})
        admission=self.store.record('test_repair_admission',self.run.binding(),{})
        body=dict(release=self.run.release,release_plan=plan)
        diagnostic.original={**diagnostic.original,'contract':digest(body)}
        diagnostic.repair=dict(review=admission,context=dict(repair_kind='fixture'),
                              proposal=dict(classification='test_contract',test_paths=['tests/acceptance_sample.py']))
        kb=SimpleNamespace(get_task=lambda *args:SimpleNamespace(body=json.dumps(body)))
        api=(kb,SimpleNamespace(connect_closing=lambda:nullcontext(None)),None)
        with patch('fabriquinha.recovery.native',return_value=api),patch('fabriquinha.repairs.context_view',return_value={}),\
             patch('fabriquinha.intake.Intake.approved',return_value=({},dict(payload=dict(document={'goal':'same brief'})))):
            self.assertEqual(diagnostic.evidence()['approved_brief'],{'goal':'same brief'})
            diagnostic.original['contract']='changed'
            with self.assertRaisesRegex(ValueError,'exact corrective source'):
                diagnostic.evidence()

    def test_fixture_diagnosis_uses_diagnostic_phase_and_never_rewrites_candidate(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        diagnostic.repair=dict(context=dict(repair_kind='fixture'),
            proposal=dict(classification='test_contract',test_paths=['tests/test_existing.py']))
        self.quality.observe=Mock(return_value=('observed-job',dict(failures=[{'case':'new behavior'}])))
        diagnostic.validate(dict(hypothesis='Observe expected Red on the original product base'))
        self.quality.observe.assert_called_once_with(self.run,self.snapshot,'diagnostic')
        with self.assertRaisesRegex(ValueError,'operation_forbidden'):
            diagnostic.validate(dict(hypothesis='Do not rewrite the fixture',replacements={'tests/test_existing.py':'changed'}))
        experiment=diagnostic.validate(dict(hypothesis='Probe product feasibility on a disposable copy',replacements={'app.py':'VALUE = 2\n'}))
        data=self.store.receipt(experiment['experiment'],kind='diagnostic_experiment')['payload']
        self.assertEqual(data['source_snapshot'],self.snapshot)
        self.assertNotEqual(data['snapshot'],self.snapshot)
        self.assertEqual((self.work/'app.py').read_text(),'VALUE = 1\n')
        self.assertEqual((self.store.tree(data['snapshot'])/'tests/test_existing.py').read_text(),'baseline test\n')
        self.assertFalse(experiment['delivery_approval'])
        self.assertEqual(self.quality.observe.call_count,2)
        self.assertIn('fresh Red',diagnostic.correction_expectation())
        self.assertIn('original product baseline',diagnostic.correction_expectation())
        self.assertNotIn('not a new feature Red',diagnostic.correction_expectation())

    def test_implementation_diagnosis_keeps_product_experiments_and_frozen_tests(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        diagnostic.original={**diagnostic.original,'kind':'implementation'}
        diagnostic.repair=dict(proposal=dict(classification='test_contract',test_paths=['tests/qa.json']))
        self.quality.observe=Mock(return_value=('observed-job',dict(failures=[])))
        diagnostic.validate(dict(hypothesis='Check a product-only negative control',replacements={'app.py':'VALUE = -1\n'}))
        self.assertEqual(self.quality.observe.call_args.args[2],'diagnostic')
        self.assertEqual((self.work/'app.py').read_text(),'VALUE = 1\n')
        self.assertEqual((self.work/'tests/test_existing.py').read_text(),'baseline test\n')

    def setUp(self):
        kb=SimpleNamespace(get_task=lambda *args:SimpleNamespace(body='{}'))
        native_patch=patch('fabriquinha.recovery.native',return_value=(kb,SimpleNamespace(connect_closing=lambda:nullcontext(None)),None))
        native_patch.start();self.addCleanup(native_patch.stop)
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

    def test_deployed_qa_failure_retains_real_error_and_rejects_foreign_jobs(self):
        from fabriquinha.recovery import browser_refusal_context
        from fabriquinha.deployment import BrowserValidationFailed
        project=replace(self.project,browser_image='sha256:'+'b'*64)
        run=Run('integration',9,'qa','integration',True,'devops','v1','qa-contract')
        payload=dict(identity=dict(binding=run.binding(),project=project.fingerprint(),snapshot=self.snapshot,
            phase='browser',image=project.browser_image,commit='c'*40),exit_code=1,infrastructure_error=None,
            report=dict(version=1,status='failed',source_sha='c'*40,checks=[],errors=['Expected exact Ana; actual Hello, Ana!'],failure_kind='behavior'),
            screenshot_sha256=None,sandbox=dict(network=project.namespace+'-homologation_qa',snapshot='readonly',user='10000:10000'))
        key=self.store.record('browser_job',run.binding(),payload)
        context=browser_refusal_context(self.store,project,run.binding(),key)
        self.assertEqual(context['report']['errors'],payload['report']['errors'])
        self.assertEqual(context['classification'],'behavior');self.assertFalse(context['delivery_approval'])
        error=BrowserValidationFailed(key,payload['report'])
        self.assertIn('actual Hello',str(error));self.assertEqual(error.browser_job,key)
        with self.assertRaises(ValueError):browser_refusal_context(self.store,project,replace(run,number=10).binding(),key)

    def test_unconfigured_author_cannot_assume_a_technical_role(self):
        self.sandbox.run=replace(self.run,actor='backend')
        with self.assertRaises(ValueError):Diagnostic(self.sandbox,self.quality)

    def test_resume_needs_an_actual_current_experiment_not_a_pass_flag(self):
        diagnostic=Diagnostic(self.sandbox,self.quality)
        decision=dict(action='resume',reason='Concrete technical guidance',findings=[dict(path='app.py',line=1,detail='Add behavior test')])
        with self.assertRaises(ValueError):diagnostic.decide(decision)
        with self.assertRaises(ValueError):diagnostic.validate(dict(passed=True,hypothesis='invented'))
        self.sandbox.close.assert_not_called()

    def test_diagnostic_retains_test_errors_without_qualifying_delivery(self):
        report=dict(version=1,tests_run=2,cases=['existing','new'],failures=[],errors=['new'],
                    skips=[],expected_failures=[],unexpected_successes=[])
        value=dict(exit_code=1,report=report)
        with self.assertRaises(ValueError):suite_report(value)
        self.assertEqual(suite_report(value,diagnostic=True),report)
        with self.assertRaises(ValueError):suite_report({**value,'exit_code':0},diagnostic=True)
        with self.assertRaises(ValueError):suite_report({**value,'report':{**report,'errors':['foreign']}},diagnostic=True)
        identity=dict(binding=self.run.binding(),snapshot=self.snapshot,phase='diagnostic',
                      project=self.project.fingerprint(),image=self.project.validation_image)
        job=self.store.record('suite_job',self.run.binding(),dict(**value,identity=identity,
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))
        self.quality.runner=Mock();self.quality.runner.run.return_value=job
        diagnostic=Diagnostic(self.sandbox,self.quality)
        result=diagnostic.validate(dict(hypothesis='The new test errors before asserting; return to its author, not implementation'))
        self.assertEqual(result['report']['errors'],['new'])
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(self.store.receipt(result['experiment'])['payload']['job'],job)
        # The phase string alone cannot grant relaxed observation to an author.
        author_identity={**identity,'binding':self.original.binding()}
        author_job=self.store.record('suite_job',self.original.binding(),dict(**value,identity=author_identity,
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))
        self.quality.runner.run.return_value=author_job
        with self.assertRaises(ValueError):self.quality.observe(self.original,self.snapshot,'diagnostic')
        # The author sees concrete cases; its rejected job survives as negative
        # diagnostic context without changing Red or independent review rules.
        author_identity['phase']='red'
        author_job=self.store.record('suite_job',self.original.binding(),dict(**value,identity=author_identity,
            sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))
        self.quality.runner.run.return_value=author_job
        with self.assertRaisesRegex(ValueError,'red suite rejected.*new'):
            self.quality.observe(self.original,self.snapshot,'red')
        self.assertEqual(self.quality.suite_refusal,author_job)
        from fabriquinha.recovery import suite_refusal_context
        context=suite_refusal_context(self.store,self.project,self.original.binding(),author_job,self.snapshot)
        self.assertEqual(context['report']['errors'],['new']);self.assertFalse(context['delivery_approval'])
        self.assertFalse(suite_refusal_context(self.store,self.project,self.original.binding(),author_job,'other')['matches_current_snapshot'])
        with self.assertRaises(ValueError):
            suite_refusal_context(self.store,self.project,replace(self.original,number=99).binding(),author_job,self.snapshot)

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
        task=SimpleNamespace(id='diagnostic',status='done',assignee='lead',body=json.dumps(dict(kind='diagnostic',
            stage='lead',source='source',inputs={'incident':self.incident})))
        recovery.cards=lambda conn:[task]
        kb=Mock();kb.get_task.return_value=SimpleNamespace(id='source',status='running',assignee='backend')
        with patch('fabriquinha.recovery.native',return_value=(kb,None,None)):
            status=recovery.status(Mock())
        self.assertEqual(status[0]['state'],'revalidating');self.assertFalse(status[0]['delivery_approval'])

    def test_native_done_without_delivery_evidence_does_not_resolve_incident(self):
        recovery=Recovery(self.project,self.store,self.board)
        task=SimpleNamespace(id='diagnostic',status='done',assignee='lead',body=json.dumps(dict(kind='diagnostic',
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


    def test_reassessment_spike_keeps_exact_tests_and_never_replaces_author_snapshot(self):
        from fabriquinha.repairs import review_reassessment
        scope=replace(self.run,actor='cto',author='cto').binding()
        prior=self.store.record('diagnostic_experiment',scope,dict(incident=self.incident,snapshot=self.snapshot,report={'cases':['case'],'failures':[dict(case='case',assertion=True,frames=[dict(file='tests/test_a.py',function='test_a',line=2)])]}))
        hold=self.store.record('diagnostic_decision',scope,dict(experiment=prior))
        facts=dict(snapshot=self.snapshot,delivery_approval=False)
        def candidate(changes):
            with tempfile.TemporaryDirectory(dir=self.root) as folder:
                work=Path(folder);self.store.checkout(self.snapshot,work)
                for path,value in changes.items():(work/path).write_text(value)
                return self.store.capture(work)
        def evidence(snapshot,source=None):
            report={'cases':['case'],'failures':[]}
            job=self.store.record('suite_job',scope,dict(report=report,identity=dict(snapshot=snapshot,project=self.project.fingerprint())))
            return self.store.record('diagnostic_experiment',scope,dict(project=self.project.fingerprint(),incident=self.incident,
                snapshot=snapshot,source_snapshot=source or self.snapshot,report=report,job=job))
        product=candidate({'app.py':'VALUE = 2\n'})
        with patch('fabriquinha.repairs.review_failure',return_value=facts):
            result=review_reassessment(self.project,self.store,self.incident,hold,'original-handoff',evidence(product))
            self.assertEqual(result['snapshot'],self.snapshot)
            self.assertFalse(result['delivery_approval'])
            for changes in ({'tests/test_existing.py':'weakened'},{'pytest.ini':'[pytest]\naddopts=-k nothing'}):
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    review_reassessment(self.project,self.store,self.incident,hold,'original-handoff',evidence(candidate(changes)))
            with self.assertRaisesRegex(ValueError,'scoped CTO'):
                review_reassessment(self.project,self.store,self.incident,hold,'original-handoff',evidence(product,source='foreign'))
        self.assertEqual((self.work/'app.py').read_text(),'VALUE = 1\n')
        self.assertEqual((self.store.tree(self.snapshot)/'app.py').read_text(),'VALUE = 1\n')


if __name__=='__main__':unittest.main()
