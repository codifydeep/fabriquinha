import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from planning_presentation import present,resume


class PlanningPresentationTests(unittest.TestCase):
    def test_only_controller_policy_changes_all_other_bytes_preserved(self):
        before='CEO brief and accepted proposals '+('x'*6000)
        after='\nHistorical recommendations '+('y'*800)
        full='\n\nCONTROLLER-VERIFIED CAPABILITIES:'+('p'*1500)
        compact='\nCONTROLLER CONTRACT: exact runner, scopes and gates'
        context=before+full+after
        result,proof=present(context,full,compact)
        self.assertEqual(result,before+compact+after)
        self.assertLessEqual(len(result),8000)
        self.assertEqual(proof['unchanged_before_sha256'],hashlib.sha256(before.encode()).hexdigest())
        self.assertEqual(proof['unchanged_after_sha256'],hashlib.sha256(after.encode()).hexdigest())
        self.assertTrue(proof['brief_proposals_history_unchanged']);self.assertFalse(proof['delivery_approval'])

    def test_small_context_unchanged_and_unbounded_or_ambiguous_policy_rejected(self):
        self.assertEqual(present('small','',''),('small',None))
        full='\n\nCONTROLLER-VERIFIED CAPABILITIES:'+('p'*1000)
        compact='\nCONTROLLER CONTRACT: bounded'
        for text,original,replacement in [('x'*9000,full,compact),
                ('x'*7000+full+full,full,compact),('x'*9000+full,full,compact),
                ('x'*8000+full,full,'fake policy')]:
            with self.assertRaises(ValueError):present(text,original,replacement)

    def state(self,root):
        brief=root/'brief.md';brief.write_text('Original current brief')
        proposals={
            'product':{'role':'product','stories':[{'title':'Goal','acceptance':['Required']}],'business_questions':[]},
            'cto':{'role':'cto','stack':'Python stdlib','components':['API'],'security':['No credentials'],
                   'technical_decisions':['Keep stack'],'risks':[]}}
        outputs={role:{'task_id':role+'-task','proposal':proposal,
            'content_sha256':hashlib.sha256(json.dumps(proposal).encode()).hexdigest()}
            for role,proposal in proposals.items()}
        ledger={'name':'BRIEFX-1','stage':'blocked','active':'techlead','owner':'techlead',
            'category':'ValueError:planning context exceeds issue limit',
            'configuration_sha256':'a'*64,'base_sha':'b'*40,
            'brief_sha256':hashlib.sha256(brief.read_bytes()).hexdigest(),
            'issues':{'product':'product-issue','cto':'cto-issue'},'outputs':outputs,
            'historical_delivery_context':'UNCHANGED historical data'}
        selection={'configuration_sha256':'a'*64,'base_sha':'b'*40,'brief':brief}
        registry={'agents':{'product':'product-agent','cto':'cto-agent'}}
        def observe(task,agent,namespace,cli):
            role=task.removesuffix('-task');output=json.dumps(proposals[role])
            return {'content_sha256':hashlib.sha256(output.encode()).hexdigest(),
                    'task_id':task,'agent_id':agent},output
        return ledger,selection,registry,observe

    def test_recovery_preserves_inputs_and_requires_independent_native_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger,selection,registry,observe=self.state(Path(temp));original=copy.deepcopy(ledger)
            new=resume(ledger,selection,registry,lambda *args:{'issues':[]},'delivery-kit-port2',observe=observe)
            self.assertEqual(ledger,original);self.assertEqual(new['outputs'],ledger['outputs'])
            self.assertEqual(new['issues'],ledger['issues'])
            self.assertEqual(new['historical_delivery_context'],ledger['historical_delivery_context'])
            self.assertTrue(new['context_presentation_recovery']['no_agent_restarted'])
            self.assertIsNone(resume({**new,'stage':'blocked'},selection,registry,None,'delivery-kit-port2'))
            bad=lambda *args:({'content_sha256':'wrong'},'{}')
            with self.assertRaisesRegex(ValueError,'native source drift'):
                resume(ledger,selection,registry,lambda *args:{'issues':[]},'delivery-kit-port2',observe=bad)

    def test_existing_issue_changed_source_and_other_failures_do_not_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger,selection,registry,observe=self.state(Path(temp))
            for change in ({'stage':'blocked_awaiting_ceo'},{'category':'other'},
                           {'issues':{**ledger['issues'],'techlead':'existing'}}):
                self.assertIsNone(resume({**ledger,**change},selection,registry,None,'delivery-kit-port2'))
            with self.assertRaisesRegex(ValueError,'existing issue'):
                resume(ledger,selection,registry,lambda *args:{'issues':[{'title':'BRIEFX-1 — techlead'}]},
                       'delivery-kit-port2',observe=observe)
            selection['brief'].write_text('Changed brief')
            with self.assertRaisesRegex(ValueError,'source identity drift'):
                resume(ledger,selection,registry,lambda *args:{'issues':[]},'delivery-kit-port2',observe=observe)
