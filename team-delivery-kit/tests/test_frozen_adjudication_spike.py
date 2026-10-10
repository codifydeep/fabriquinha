import copy
import hashlib
import json
import unittest
from broker import frozen_adjudication_spike as r
import test_frozen_diagnosis_format_recovery as prior


class AdjudicationSpikeTests(unittest.TestCase):
    def evidence(self):
        e=prior.FrozenDiagnosisFormatTests().evidence();data=json.loads(e['row']['data'])
        data['decision']=dict(action='escalate_cto',reason='One observed disagreement requires adjudication',optional_files=[])
        e['row']['data']=json.dumps(data)
        e['task']={**e['failed'],'status':'completed'};e['native_decision']=data['decision']
        e['reads']['/evidence/previous/tests/test_new.py']=dict(lines=10,total_lines=10)
        e['red']=dict(red=dict(test_sha256={'tests/test_new.py':'b'*64}))
        output='FAIL: test_x (tests.test_new.Case.test_x)\nAssertionError: 2 not greater than or equal to 3\n'
        sha=hashlib.sha256(output.encode()).hexdigest();data['validation_failure']['output_sha256']=sha
        e['row']['data']=json.dumps(data);e['job']['result'].update(output=output,output_sha256=sha)
        raw=json.dumps(dict(manifest_sha256='a'*64,baseline_tests_intact=True,new_test_sha256=e['red']['red']['test_sha256']))
        e['structure']=dict(stage='complete',result=dict(exit_code=0,approval=False,output=raw,
                            output_sha256=hashlib.sha256(raw.encode()).hexdigest()))
        e['image']='sha256:'+'c'*64
        return e

    def proofs(self,config):
        plain=dict(operation='frozen_python_suite_assertion_observations_v2',approval=False,
            status='experiment_only_not_green_or_approval',manifest_sha256=config['manifest_sha256'],
            output_sha256=config['failure']['output_sha256'],runtime_observations=[dict(operands=[2,3])],
            suite=dict(tests=4,failures=1,errors=0,skipped=0))
        traced=copy.deepcopy(plain);traced.update(operation='frozen_js_event_order_experiment_v1',
            event_reports=[dict(events=[],total_events=0,truncated=False)])
        return plain,traced

    def test_qualification_keeps_original_tests_and_records_hypotheses_not_defect_certainty(self):
        e=self.evidence();before=copy.deepcopy(e);config=r.qualify(e)
        self.assertEqual(e,before);self.assertEqual(config['hashes'],e['red']['red']['test_sha256'])
        self.assertEqual(config['previous_handoff'],e['row']);self.assertEqual(len(config['hypotheses']),2)
        self.assertFalse(config['test_change_authorized']);self.assertFalse(config['author_retry_authorized'])
        self.assertFalse(config['delivery_approval'])

    def test_wrong_owner_changed_test_or_actual_job_evidence_never_qualifies(self):
        for group,key,value in [('route','enabled',False),('task','status','failed'),('row','owner','author'),
                ('source','status','failed'),('binding','status','running'),('snapshot','volume','other')]:
            e=self.evidence();e[group][key]=value
            with self.subTest(group=group,key=key),self.assertRaises(ValueError):r.qualify(e)
        for key,value in [('active',True),('pending',True),('consumed',True),('reads',{}),('native_decision',{}),
                          ('latest_author','other'),('red',{})]:
            e=self.evidence();e[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):r.qualify(e)
        e=self.evidence();e['job']['result']['output']='different actual failure'
        with self.assertRaises(ValueError):r.qualify(e)
        e=self.evidence();e['structure']['result']['output_sha256']='d'*64
        with self.assertRaises(ValueError):r.qualify(e)

    def test_tracing_must_preserve_failure_counts_observations_manifest_and_complete_events(self):
        config=r.qualify(self.evidence());plain,traced=self.proofs(config)
        proof=r.validate_pair(config,plain,traced);self.assertTrue(proof['tracing_observations_equal'])
        self.assertFalse(proof['delivery_approval'])
        for key,value in [('manifest_sha256','d'*64),('runtime_observations',[dict(operands=[3,3])]),
                ('suite',dict(tests=4,failures=0,errors=0,skipped=0)),('approval',True),
                ('event_reports',[dict(truncated=True)]),('output_sha256','d'*64)]:
            bad={**traced,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):r.validate_pair(config,plain,bad)

    def test_recipe_mounts_only_frozen_input_without_socket_credentials_network_or_writes(self):
        config=r.qualify(self.evidence());body=r.payload(config,True)
        self.assertEqual(body['Cmd'],['/runtime_assertion_probe.py'])
        self.assertTrue(body['NetworkDisabled']);self.assertTrue(body['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(body['HostConfig']['NetworkMode'],'none')
        self.assertEqual(body['HostConfig']['Mounts'],[dict(Type='volume',Source='snapshot',Target='/delivery',ReadOnly=True)])
        self.assertNotIn('docker.sock',json.dumps(body));self.assertNotIn('API_KEY',json.dumps(body))

    def test_unknown_issue_creation_is_observed_without_second_post_and_jobs_are_stable(self):
        config=r.qualify(self.evidence());plain,traced=self.proofs(config);calls=[];jobs=[];handoffs=[];saved=[]
        class Effects:
            def issue(self,config,*,allow_create):
                calls.append(allow_create)
                return None if len(calls)==1 else dict(id='spike-card',identifier='SPIKE-1')
            def job(self,task,payload):
                jobs.append(task)
                if len(jobs)==1:raise TimeoutError('running original handle')
                proof=traced if 'EVENT_ORDER_TRACE=1' in payload['Env'] else plain
                raw=json.dumps(proof)
                return dict(exit_code=0,output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest())
            def handoff(self,config,proof,spike):handoffs.append((proof,spike))
        fx=Effects();state=dict(stage='registered')
        for _ in range(5):state=r.advance(config,state,fx,saved.append)
        self.assertEqual(calls,[True,False]);self.assertEqual(jobs[0],jobs[1])
        self.assertEqual(len(set(jobs)),2);self.assertEqual(state['stage'],'dispatched');self.assertEqual(len(handoffs),1)
        self.assertFalse(state['delivery_approval'])

    def test_contaminated_trace_is_visible_blocked_without_handoff_or_repeated_jobs(self):
        config=r.qualify(self.evidence());plain,traced=self.proofs(config);traced['runtime_observations']=[]
        class Effects:
            calls=0
            def job(self,task,payload):
                self.calls+=1;raw=json.dumps(traced)
                return dict(exit_code=0,output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest())
            def handoff(self,*args):raise AssertionError('must not transfer contaminated evidence')
        fx=Effects();saved=[];state=dict(stage='traced',plain=plain,spike_issue='spike')
        state=r.advance(config,state,fx,saved.append)
        self.assertEqual(state['stage'],'blocked');self.assertEqual(state['category'],'trace_contamination_or_incomplete_evidence')
        r.advance(config,state,fx,saved.append);self.assertEqual(fx.calls,1)
