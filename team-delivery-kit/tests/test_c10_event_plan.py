import copy
import json
import unittest
from broker import c10_event_plan as event
import test_c10_queue_recovery as queue_tests


class EventPlanTests(unittest.TestCase):
    def setUp(self):
        fixture=queue_tests.QueueRecoveryTests();fixture.setUp()
        self.output=fixture.output;self.trace=fixture.trace
        self.state=fixture.feedback()
        self.state=event.recovery.reject(self.state,'a'*64,'remaining identity contradicts trace')
        self.plan={'schema':'queue-event-plan-v1','test_sha256':'f'*64,
            'trace_sha256':self.state['c10_queue_trace_feedback']['trace_sha256'],
            'scope':[534,536],
            'before_negative':['/feedback?q=beta','/feedback?q=gamma','/feedback?q=delta'],
            'before_status':['/feedback?q=gamma','/feedback?status=open?q=delta','/feedback?status=completed?q=delta'],
            'remaining':['/feedback?q=gamma'],'phase':'after_stale_status_observation',
            'drain':{'operation':'resolveOldest','expected_url':'/feedback?q=gamma','response':{'items':[]}},
            'after':['flush','measure_pending_length'],
            'preserve':['QUERY','C09','current_status_dom','stale_status_dom']}

    def report(self,state,plan=None):
        decision={'action':'request_test_revision','optional_files':[],
            'reason':'DRIVER_OBSERVATION: '+json.dumps(self.plan if plan is None else plan,separators=(',',':'))}
        return {'classification':'DRIVER_OBSERVATION','decision':decision,
            'certificate':{'task_id':'event-cto','snapshot':'atomic','test_sha256':'f'*64,
                'decision_sha256':event.sha(decision)}}

    def test_intake_archives_rejected_attempt_without_authority(self):
        revised=event.prepare(self.state,self.output,self.trace)
        self.assertEqual(revised['c10_checkpoints'],self.state['c10_checkpoints'])
        self.assertFalse(revised['c10_event_plan_intake']['author_scope_authorized'])
        self.assertNotIn('functional_diagnosis_receipt',revised)
        self.assertIn('strict JSON',revised['functional_diagnosis']['note'])
        with self.assertRaises(ValueError):event.prepare(revised,self.output,self.trace)

    def test_valid_plan_is_data_not_execution_or_green(self):
        state=event.prepare(self.state,self.output,self.trace)
        report=self.report(state)
        result=event.validate(state,report)
        self.assertEqual(result['remaining_after_simulation'],[])
        self.assertFalse(result['functional_green']);self.assertFalse(result['author_authorized'])
        self.assertLessEqual(len(report['decision']['reason']),1200)
        revised=event.assess(state,report)
        self.assertEqual(revised['category'],'c10_event_plan_verified')
        self.assertFalse(revised['delivery_approval'])

    def test_wrong_queue_identity_scope_faked_counters_or_extra_commands_rejected(self):
        state=event.prepare(self.state,self.output,self.trace)
        for mutation in ('remaining','negative','status','scope','fake','await','response','extra','hash','phase'):
            plan=copy.deepcopy(self.plan)
            if mutation=='remaining':plan['remaining']=['/feedback?status=open?q=delta']
            if mutation=='negative':plan['before_negative'].reverse()
            if mutation=='status':plan['before_status']=plan['before_status'][1:]
            if mutation=='scope':plan['scope']=[526,553]
            if mutation=='fake':plan['after']=['set_pending_zero']
            if mutation=='await':plan['after']=['await_held_promise','flush','measure_pending_length']
            if mutation=='response':plan['drain']['response']=[]
            if mutation=='extra':plan['shell']='anything'
            if mutation=='hash':plan['trace_sha256']='e'*64
            if mutation=='phase':plan['phase']='before_status'
            with self.assertRaises(ValueError):event.validate(state,self.report(state,plan))

    def test_freeform_duplicate_keys_stale_cert_and_approval_are_rejected(self):
        state=event.prepare(self.state,self.output,self.trace)
        for mutation in ('prose','duplicate','snapshot','task','decision','approve'):
            report=self.report(state)
            if mutation=='prose':report['decision']['reason']='DRIVER_OBSERVATION: gamma is pending; resolve it.'
            if mutation=='duplicate':report['decision']['reason']='DRIVER_OBSERVATION: {"schema":"x","schema":"y"}'
            if mutation=='snapshot':report['certificate']['snapshot']='other'
            if mutation=='task':report['certificate']['task_id']='new-cto'
            if mutation=='decision':report['certificate']['decision_sha256']='x'*64
            if mutation=='approve':report['decision']['action']='approve_test_revision'
            with self.assertRaises(ValueError):event.validate(state,report)

    def test_assessment_keeps_invalid_decision_and_no_automatic_retry(self):
        state=event.prepare(self.state,self.output,self.trace)
        report=self.report(state);report['decision']['reason']='DRIVER_OBSERVATION: wrong prose'
        report['certificate']['decision_sha256']=event.sha(report['decision'])
        revised=event.assess(state,report)
        self.assertEqual(revised['functional_diagnosis_receipt'],report)
        self.assertEqual(revised['category'],'c10_event_plan_rejected')
        self.assertFalse(revised['c10_event_plan_intake']['verification']['author_authorized'])
        with self.assertRaises(ValueError):event.assess(revised,report)

    def test_json_prefix_whitespace_is_not_semantic_authority(self):
        state=event.prepare(self.state,self.output,self.trace)
        report=self.report(state)
        report['decision']['reason']=report['decision']['reason'].replace('DRIVER_OBSERVATION: ','DRIVER_OBSERVATION:',1)
        report['certificate']['decision_sha256']=event.sha(report['decision'])
        self.assertEqual(event.validate(state,report)['status'],'verified_as_plan_only')
        wrong=copy.deepcopy(report)
        plan=copy.deepcopy(self.plan);plan['before_negative']=['/feedback?q=alpha','/feedback?q=beta']
        wrong['decision']['reason']='DRIVER_OBSERVATION:'+json.dumps(plan,separators=(',',':'))
        wrong['certificate']['decision_sha256']=event.sha(wrong['decision'])
        with self.assertRaisesRegex(ValueError,'observation_or_scope'):event.validate(state,wrong)

    def test_parser_reassessment_preserves_prior_verdict_and_never_replays_agent(self):
        state=event.prepare(self.state,self.output,self.trace)
        plan=copy.deepcopy(self.plan);plan['before_status']=plan['before_status'][0:2]
        report=self.report(state,plan)
        report['decision']['reason']=report['decision']['reason'].replace('DRIVER_OBSERVATION: ','DRIVER_OBSERVATION:',1)
        report['certificate']['decision_sha256']=event.sha(report['decision'])
        state=event.assess(state,report)
        state['c10_event_plan_intake']['verification']['error']='event_plan_structured_data_required'
        revised=event.reassess_parser(state)
        self.assertEqual(revised['functional_diagnosis_receipt'],report)
        self.assertEqual(revised['c10_event_plan_intake']['prior_parser_verdict']['error'],'event_plan_structured_data_required')
        self.assertEqual(revised['c10_event_plan_intake']['verification']['error'],'event_plan_observation_or_scope_mismatch')
        self.assertFalse(revised['c10_event_plan_intake']['verification']['author_authorized'])
        with self.assertRaises(ValueError):event.reassess_parser(revised)

    def fixed_state(self):
        state=event.prepare(self.state,self.output,self.trace)
        bad=copy.deepcopy(self.plan);bad['before_negative']=['/feedback?q=alpha','/feedback?q=beta']
        return event.assess(state,self.report(state,bad))

    def choice_report(self,state,operation='resolveOldest'):
        decision={'action':'request_test_revision','optional_files':[],
            'reason':'DRIVER_OBSERVATION:'+json.dumps({'schema':'queue-recovery-choice-v2',
                'trace_sha256':state['c10_event_plan_intake']['trace_sha256'],'operation':operation},separators=(',',':'))}
        return {'classification':'DRIVER_OBSERVATION','decision':decision,
            'certificate':{'task_id':'choice-cto','snapshot':'atomic','test_sha256':'f'*64,'decision_sha256':event.sha(decision)}}

    def test_fixed_facts_intake_preserves_invalid_plan_and_compiles_explicit_choice_only(self):
        prior=self.fixed_state();state=event.prepare_fixed_facts(prior,self.output,self.trace)
        self.assertEqual(state['c10_fixed_facts']['prior_intake'],prior['c10_event_plan_intake'])
        self.assertEqual(state['c10_fixed_facts']['prior_receipt'],prior['functional_diagnosis_receipt'])
        self.assertNotIn('before_negative=<',state['functional_diagnosis']['note'])
        for operation in ('resolveOldest','resolveNewest'):
            report=self.choice_report(state,operation);proof=event.validate(state,report)
            self.assertEqual(proof['plan']['before_negative'],self.plan['before_negative'])
            self.assertEqual(proof['plan']['drain']['operation'],operation)
            self.assertTrue(proof['controller_compiled_facts'])
            self.assertFalse(proof['functional_green']);self.assertFalse(proof['author_authorized'])
        with self.assertRaises(ValueError):event.prepare_fixed_facts(state,self.output,self.trace)

    def test_fixed_facts_never_accept_prose_commands_fabricated_facts_or_old_contract(self):
        state=event.prepare_fixed_facts(self.fixed_state(),self.output,self.trace)
        for mutation in ('operation','hash','facts','prose','legacy'):
            report=self.choice_report(state)
            choice=json.loads(report['decision']['reason'].split(':',1)[1])
            if mutation=='operation':choice['operation']='pending.length=0'
            if mutation=='hash':choice['trace_sha256']='b'*64
            if mutation=='facts':choice['remaining']=['open']
            if mutation=='legacy':choice=self.plan
            report['decision']['reason']='DRIVER_OBSERVATION:'+json.dumps(choice)
            if mutation=='prose':report['decision']['reason']='DRIVER_OBSERVATION: resolve gamma'
            report['certificate']['decision_sha256']=event.sha(report['decision'])
            with self.assertRaises(ValueError):event.validate(state,report)

    def test_explicit_author_admission_requires_verified_plan_reserve_and_distinct_scope(self):
        from broker import c10_event_author as author
        state=event.prepare(self.state,self.output,self.trace)
        state=event.assess(state,self.report(state))
        revised=author.prepare({'author':'author','cto':'cto'},state,48)
        cp=revised['c10_checkpoints']
        self.assertNotEqual(cp['scope_id'],state['c10_checkpoints']['scope_id'])
        self.assertEqual(cp['seed'],state['c10_checkpoints']['seed'])
        self.assertEqual(cp['query_receipt'],state['c10_checkpoints']['query_receipt'])
        self.assertEqual(revised['c10_event_author']['failed_snapshot'],state['snapshot'])
        self.assertFalse(revised['delivery_approval'])
        self.assertTrue(author.binding(revised,cp['seed']))
        with self.assertRaises(ValueError):author.prepare({'author':'author','cto':'cto'},state,47)
        with self.assertRaises(ValueError):author.prepare({'author':'author','cto':'author'},state,48)
        with self.assertRaises(ValueError):author.prepare({'author':'author','cto':'cto'},revised,48)

    def test_policy_selects_only_exact_event_scope_and_preserves_atomic_fences(self):
        from broker import c10_event_author as author,c10_status_admission as status
        state=event.prepare(self.state,self.output,self.trace)
        state=author.prepare({'author':'author','cto':'cto'},event.assess(state,self.report(state)),48)
        state.update(stage='awaiting_author',wakeup_id='event-wake')
        proof=state['c10_checkpoints']['qualification']
        proof['atomic_status']={'schema':'surgical-status-atomic-probe-v1','status':'passed',
            'uid':10000,'network':'none','model_calls':0,'delivery_approval':False,
            **{flag:True for flag in status.ATOMIC_FLAGS}}
        state['staged']['driver_guard']['qualification']=copy.deepcopy(proof)
        state['c10_event_author']['checkpoint']=copy.deepcopy(state['c10_checkpoints'])
        task={'id':'event-author','agent_id':'author','issue_id':'issue','wakeup_id':'event-wake',
            'handoff_note':status.author_note(state)}
        state['c10_checkpoints']['note_sha256']=event.recovery.status.gates.sha(task['handoff_note'].encode())
        state['c10_event_author']['checkpoint']=copy.deepcopy(state['c10_checkpoints'])
        grant=status.select({'author':'author'},state,task)
        self.assertEqual(grant['surgical']['atomic_contract'],'c10-status-observations-v1')
        self.assertIn('/feedback?q=gamma',task['handoff_note'])
        with self.assertRaises(ValueError):status.select({'author':'author'},state,dict(task,wakeup_id='old'))
