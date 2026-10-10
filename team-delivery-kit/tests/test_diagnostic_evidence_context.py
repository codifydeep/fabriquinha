import copy
import json
import unittest
from broker import diagnostic_evidence_context as memory,bound_failure_context as bound
from broker import frozen_adjudication_spike as spike
import test_frozen_adjudication_spike as prior


class DiagnosticEvidenceTests(unittest.TestCase):
    def test_pre_native_missing_marker_returns_to_standard_intake_only_once(self):
        _,_,row,route,task,binding,decision,reads,context=self.fixture()
        data=memory.prepare_recovery(row,route,task,binding,decision,reads,context,
            active=False,pending=False,consumed=False)
        data.update(control_error="KeyError:'dispatch_marker'",control_error_count=2)
        failed={**row,'data':json.dumps(data)};receipt=data['diagnostic_evidence_recovery']
        repaired=memory.repair_unmarked_intake(failed,receipt,'cto',active=False,pending=False)
        self.assertNotIn('dispatch_stage',repaired);self.assertNotIn('dispatch_marker',repaired)
        self.assertFalse(repaired['context_intake_repair']['native_post_attempted'])
        self.assertEqual(repaired['diagnostic_evidence_context'],context)
        for change in ('active','pending','accepted','marker','error','consumed','receipt'):
            r=copy.deepcopy(failed);d=json.loads(r['data']);rec=copy.deepcopy(receipt);flags=dict(active=False,pending=False)
            if change in flags:flags[change]=True
            if change=='accepted':d['wakeup_id']='accepted'
            if change=='marker':d['dispatch_marker']='e'*64
            if change=='error':d['control_error']='TimeoutError'
            if change=='consumed':d['context_intake_repair']={'used':True}
            if change=='receipt':rec['proof_sha256']='e'*64
            r['data']=json.dumps(d)
            with self.subTest(change=change),self.assertRaises(ValueError):memory.repair_unmarked_intake(r,rec,'cto',**flags)
    def fixture(self):
        sample=prior.AdjudicationSpikeTests();config=spike.qualify(sample.evidence())
        plain,traced=sample.proofs(config);proof=spike.validate_pair(config,plain,traced)
        state=dict(stage='dispatched',plain=plain,traced=traced)
        task=dict(id='diagnosis',agent_id='cto',issue_id=config['issue_id'],status='completed',wakeup_id='wake')
        decision=dict(action='escalate_cto',reason='Measure the missing observation',optional_files=[])
        data=dict(source_task=config['source_task'],validation_failure=config['failure'],artifact_diagnosis=True,
            target='cto',recipient_task=task['id'],wakeup_id='wake',decision=decision,
            unsupported_experiment_recovery=dict(decision_task=task['id']),
            adjudication_spike=dict(proof_sha256=spike.digest(proof)))
        context=memory.context_for(config,state,data)
        row=dict(source_task=config['source_task'],issue_id=config['issue_id'],stage='technical_decision_required',
            owner='cto',data=json.dumps(data))
        route=dict(cto='cto',author='author',enabled=True)
        binding=dict(task_id=task['id'],agent_id='cto',issue_id=config['issue_id'],status='closed',scope='test:planning:'+task['id'])
        reads={'/evidence/candidate/'+p:dict(lines=10,total_lines=10) for p in config['failure']['diagnostic_read_files']}
        return config,state,row,route,task,binding,decision,reads,context

    def test_complete_receipt_roundtrip_and_prompt_expansion_bind_source_hash_and_wakeup(self):
        config,state,row,_,task,_,_,_,context=self.fixture();data=json.loads(row['data'])
        data['diagnostic_evidence_context']=context;row['data']=json.dumps(data)
        full=memory.decode_receipt(context['receipt'])
        self.assertEqual(full,spike.validate_pair(config,state['plain'],state['traced']))
        note='DELIVERY_BOUND_FAILURE_CONTEXT_V1:'+row['source_task']+':'+bound.digest(data['validation_failure'])
        expanded=bound.expand(note,row['issue_id'],task,lambda source:row)
        self.assertIn('CONTROLLER VERIFIED COMPLETE EXPERIMENT RECEIPT',expanded)
        self.assertIn('NOT GREEN OR APPROVAL',expanded)
        self.assertIn(context['proof_sha256'],expanded)
        for change in ('hash','source','count','wakeup'):
            bad=copy.deepcopy(row);value=json.loads(bad['data']);actor=copy.deepcopy(task)
            if change=='hash':value['diagnostic_evidence_context']['proof_sha256']='e'*64
            if change=='source':value['diagnostic_evidence_context']['source_task']='other'
            if change=='count':value['diagnostic_evidence_context']['receipt']['suite']['tests']=1
            if change=='wakeup':actor['wakeup_id']='other'
            bad['data']=json.dumps(value)
            with self.subTest(change=change),self.assertRaises(ValueError):bound.expand(note,row['issue_id'],actor,lambda source:bad)

    def test_once_only_changed_context_never_reruns_jobs_or_grants_test_edits(self):
        _,_,row,route,task,binding,decision,reads,context=self.fixture()
        result=memory.prepare_recovery(row,route,task,binding,decision,reads,context,
            active=False,pending=False,consumed=False)
        self.assertEqual(result['trigger_task'],task['id']);self.assertNotIn('recipient_task',result)
        self.assertFalse(result['diagnostic_evidence_recovery']['jobs_reexecuted'])
        self.assertFalse(result['diagnostic_evidence_recovery']['test_change_authorized'])
        self.assertLess(len(result['instruction']),3500)
        self.assertIn('/evidence/previous/',result['instruction'])
        for change in ('active','pending','consumed','owner','failed','live','partial','mode','already_attached'):
            r=copy.deepcopy(row);t=copy.deepcopy(task);b=copy.deepcopy(binding);rd=copy.deepcopy(reads)
            flags=dict(active=False,pending=False,consumed=False)
            if change in flags:flags[change]=True
            if change=='owner':r['owner']='author'
            if change=='failed':t['status']='failed'
            if change=='live':b['status']='running'
            if change=='partial':rd={}
            if change=='mode':b['scope']='test:implementation:'+task['id']
            if change=='already_attached':data=json.loads(r['data']);data['diagnostic_evidence_context']=context;r['data']=json.dumps(data)
            with self.subTest(change=change),self.assertRaises(ValueError):
                memory.prepare_recovery(r,route,t,b,decision,rd,context,**flags)
