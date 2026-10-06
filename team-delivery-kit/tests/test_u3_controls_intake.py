import copy
import unittest
from broker import u3_controls_intake as intake,test_decomposition as plans
from types import SimpleNamespace
from unittest.mock import Mock


class ControlsIntakeTests(unittest.TestCase):
    def setUp(self):
        self.state={'stage':'maintenance_review_approved','delivery_approval':False,'author_task':'author-task',
            'validation':{'test_sha256':'t','manifest_sha256':'m'},
            'suite_receipt':{'exit_code':0,'tests':259,'source_task':'author-task','test_sha256':'t','manifest_sha256':'m'},
            'maintenance_review_receipt':{'source_task':'author-task','reviewer':'reviewer','author':'author',
                'manifest_sha256':'m','decision':{'action':'approve_test_revision'}}}
        self.proof={'schema':'u3-negative-controls-v1','inputs_unchanged':True,'delivery_approval':False,
            'valid_red_green_receipt':False,'test_sha256':'t','manifest_sha256':'m','network':'none',
            'model_calls':0,'controls_complete':False,'invalid':[],'killed':['allow_stale_query'],
            'survived':['retain_query','allow_stale_status'],
            'reports':{mode:{'tests':4,'errors':0,'skipped':0,'test_sha256':'t',
                'successful':mode!='allow_stale_query','failures':int(mode=='allow_stale_query')}
                for mode in ('baseline','retain_query','allow_stale_query','allow_stale_status')}}

    def test_exact_approved_baseline_and_real_kill_survivors_required(self):
        intake.qualify(self.state,self.proof)
        for mutation in ('approval','hash','errors','skips','missing','counter','network','selfreview','green'):
            state=copy.deepcopy(self.state);proof=copy.deepcopy(self.proof)
            if mutation=='approval':state['delivery_approval']=True
            if mutation=='hash':proof['test_sha256']='old'
            if mutation=='errors':proof['reports']['retain_query']['errors']=1
            if mutation=='skips':proof['reports']['baseline']['skipped']=1
            if mutation=='missing':proof['reports'].pop('baseline')
            if mutation=='counter':proof['reports']['allow_stale_status']['failures']=1
            if mutation=='network':proof['network']='host'
            if mutation=='selfreview':state['maintenance_review_receipt']['reviewer']='author'
            if mutation=='green':state['suite_receipt']['exit_code']=1
            with self.assertRaises(ValueError):intake.qualify(state,proof)

    def test_planning_note_is_current_nonexecuting_and_two_units_only(self):
        cfg={'kind':'verified_controls_v1','source_task':'source','issue_id':'issue','cto':'cto',
            'diagnostic_sha256':'d','diagnostic':self.proof,'required_files':['tests/test_incremental_u3.py'],
            'criteria':{'C01':'clearing','C02':'stale status'}}
        effects=SimpleNamespace(remaining_calls=Mock(return_value=60),ensure_planning_start=Mock(return_value={'id':'wake'}))
        state=plans.advance(cfg,{'stage':'pending','deterministic_reads':True},[],effects,now=1)
        self.assertEqual(state['wakeup_id'],'wake')
        note=effects.ensure_planning_start.call_args.args[4]
        self.assertIn('APPROVED HARNESS',note);self.assertIn('No product edits',note)
        decision={'action':'propose_test_decomposition','reason':'Two scoped tests','optional_files':[],
            'units':[{'id':'U1','depends_on':[],'criteria':['C01'],'objective':'Clear the search field'},
                {'id':'U2','depends_on':['U1'],'criteria':['C02'],'objective':'Inspect post-stale DOM'}]}
        cert=plans.validate_result(cfg,{'agent_id':'cto','status':'completed','id':'cto-task'},decision,
            {'/evidence/candidate/tests/test_incremental_u3.py':{'lines':699,'total_lines':699}})
        self.assertFalse(cert['execution_authorized'])
