import copy
import hashlib
import json
import sqlite3
import unittest
from broker import calibration_objection_runtime as runtime,generic_calibration_workflow as workflow,handoffs
from generic_harness_calibration import digest


class ObjectionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        workflow.initialize(self.con);handoffs.initialize(self.con);runtime.initialize(self.con)
        self.c=dict(issue_id='issue',author_task='author',cto='cto',reviewer='lead',test_files=['tests/test.py'],
            prepared=dict(manifest_sha256='a'*64,test_sha256={'tests/test.py':'b'*64}),calibration_engine='unittest_path_fixtures_v2')
        self.s=dict(stage='blocked',category='bundle_technical_objection',owner='lead',execution_authorized=False,delivery_approval=False,
            objection=dict(operation='calibration_technical_objection_v1',reason='Verify Node path',source_sha256=digest(self.c)))
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',('issue','author',json.dumps(self.c),json.dumps(self.s)))
        handoffs.save(self.con,'author','issue','test_first_blocked','lead',dict(calibration_prerequisite=self.s),0)
        runtime.register(self.con,self.c,self.s);self.runs=[];self.effects=[];self.uncertain=False;self.action='refer_to_cto';parent=self
        proof=dict(operation='fixed_node_path_seam_v1',candidate_manifest_sha256='a'*64,test_sha256=self.c['prepared']['test_sha256'],
            paths={'tests/test.py':{'APP_JS':'app/app.js','INDEX_HTML':'app/index.html'}},
            bindings={'tests/test.py':dict(template_sha256='c'*64,line=10,attribute='APP_JS',product_path='app/app.js',
                reads={k:hashlib.sha256(('node-path-'+k+'\n').encode()).hexdigest() for k in ('positive','negative')})},
            snapshot_unchanged=True,template_unchanged=True,model_calls=0,product_tests_executed=False,calibration_approved=False,
            red_approved=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
        out=json.dumps(proof);self.probe=dict(approval=False,exit_code=0,output=out,output_sha256=hashlib.sha256(out.encode()).hexdigest(),container_id='probe')
        class Effects:
            def verify(_,cfg):parent.assertEqual(cfg['source'],parent.c)
            def issue(_,cfg,first):parent.effects.append(('issue',first));return dict(id='spike',identifier='EVAL-SPIKE')
            def probe(_,cfg):parent.effects.append(('probe',));return parent.probe
            def reserve(_):return True
            def wake(_,cfg,s,first):
                parent.effects.append(('wake',first,s['marker']))
                if parent.uncertain:parent.uncertain=False;raise TimeoutError()
                return dict(id='review-wake')
            def runs(_,cfg,s):return parent.runs
            def decision(_,cfg,s,task):
                value={**runtime.review_context(cfg,s), 'action':parent.action,'reason':'Path seam measured; full calibration remains required',
                    'author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}
                return dict(task_id=task['id'],agent_id='lead',value=value,execution_id='review-execution')
            def verify_decision(_,cfg,s):parent.effects.append(('revalidate',))
        self.fx=Effects()

    def advance(self,now=1):return runtime.advance(self.con,'issue','author',self.fx,now=now)
    def completed(self):self.runs=[dict(id='lead-task',agent_id='lead',issue_id='spike',wakeup_id='review-wake',status='completed')]

    def test_real_flow_requires_fixed_probe_and_independent_referral_before_one_data_submission(self):
        self.advance();self.advance();self.advance();self.completed();self.advance();state=self.advance()
        self.assertEqual(state['stage'],'referred');self.assertTrue(state['submission_consumed'])
        s=json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])
        self.assertEqual(s['stage'],'bundle_dispatch');self.assertEqual(runtime.qualified(self.con,self.c,s)['submission_limit'],1)
        before=list(self.effects);self.advance();self.assertEqual(self.effects,before)
        runtime.register(self.con,self.c,{**self.s,'objection':{**self.s['objection'],'reason':'Another wording'}})
        self.assertEqual(self.advance()['category'],'repeated_objection_requires_new_experiment');self.assertEqual(self.effects,before)

    def test_lost_wakeup_ack_observes_same_marker_without_second_create(self):
        self.advance();self.advance();self.uncertain=True;self.advance();self.advance()
        wakes=[x for x in self.effects if x[0]=='wake']
        self.assertEqual([x[1] for x in wakes],[True,False]);self.assertEqual(wakes[0][2],wakes[1][2])

    def test_failed_probe_and_technical_hold_cannot_rearm_or_approve(self):
        self.advance();self.probe['output_sha256']='0'*64
        self.assertEqual(self.advance()['stage'],'blocked');before=list(self.effects);self.advance();self.assertEqual(before,self.effects)

    def test_human_decision_or_changed_source_cannot_stand_in_for_independent_review(self):
        self.advance();self.advance();self.advance();self.completed();self.runs[0]['agent_id']='ceo'
        self.assertEqual(self.advance()['category'],'objection_review_invalid')

    def test_parent_projection_wait_is_bounded_without_repeating_review(self):
        self.advance();self.advance();self.advance();self.completed();self.advance()
        self.con.execute("UPDATE delivery_handoffs SET data='{}'");self.con.commit()
        self.assertEqual(self.advance(2)['stage'],'resume_pending')
        self.assertEqual(self.advance(602)['category'],'objection_projection_deadline')
