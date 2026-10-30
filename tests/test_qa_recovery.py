import sys
from pathlib import Path
from unittest import TestCase
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.qa_recovery import empty_state_failure

class CleanQARouting(TestCase):
    def test_only_exact_single_precondition_is_recovered(self):
        case='acceptance_a_empty_list.EmptyList.test_home_shows_empty_state_when_no_waiting_rooms'
        prefix='full acceptance suite failed, skipped or did not run completely: '
        detail=case+': AssertionError: EMPTY_LIST must observe a fresh app with no rooms'
        report=dict(status='failed',failure_kind='behavior',cases=[case],errors=[prefix+repr([detail])])
        self.assertTrue(empty_state_failure(report))
        for changes in (dict(status='passed'),dict(failure_kind='infrastructure'),dict(cases=[]),
                        dict(errors=[prefix+repr([detail,'another test failure'])]),dict(errors=['EMPTY_LIST']),
                        dict(errors=[prefix+'not a literal']),dict(errors=[prefix+repr([detail.replace('AssertionError','TimeoutError')])])):
            with self.subTest(changes=changes):self.assertFalse(empty_state_failure({**report,**changes}))

    def test_recovered_evidence_cannot_claim_foreign_artifact_or_self_review(self):
        from types import SimpleNamespace
        from fabriquinha.qa_recovery import receipt_origin
        project=SimpleNamespace(fingerprint=lambda:'p',reviewers_for=lambda author:['qa'])
        source=dict(task='old',release='r',kind='integration',reviewing=True,actor='qa',author='devops',contract='old',number=1)
        admission=dict(binding=dict(actor='controller',release='r'),payload=dict(project='p',source_binding=source,rollout='rollout',artifact='artifact'))
        store=SimpleNamespace(receipt=lambda *a,**kw:admission)
        record=dict(binding={**source,'task':'new','number':3,'contract':'new'},payload=dict(qa_recovery='admission',rollout='rollout',artifact='artifact'))
        self.assertEqual(receipt_origin(project,store,record)['task'],'old')
        for scope,payload in (({'actor':'devops'},{}),({}, {'artifact':'foreign'}),({'release':'foreign'},{})):
            with self.assertRaises(ValueError):receipt_origin(project,store,{'binding':{**record['binding'],**scope},'payload':{**record['payload'],**payload}})
