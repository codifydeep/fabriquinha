import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from hermes_cli import kanban_db as kb
from product_autonomy import Coordinator
from product_workspace import Workspace,digest
from product_fairness import ordered,claimed
from product_tdd_contract import red_mismatch,rejection

class LivenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);board=root/'board';board.mkdir();control=root/'control';control.mkdir()
        self.c=Coordinator.__new__(Coordinator);self.c.root=control;self.c.board=board
        self.c.native=kb.connect(board/'kanban.db');self.addCleanup(self.c.native.close)
        self.c.db=sqlite3.connect(control/'autonomy.db');self.addCleanup(self.c.db.close)
        self.c.db.execute('CREATE TABLE records(key TEXT PRIMARY KEY,value TEXT)')
        self.c.private=sqlite3.connect(control/'controller.db');self.addCleanup(self.c.private.close)
        self.c.private.execute('CREATE TABLE product_test_receipts(task TEXT,receipt TEXT)')
        self.c.private.execute('CREATE TABLE product_verdicts(task TEXT,envelope TEXT,state TEXT,review_run INTEGER)')
        self.task=kb.create_task(self.c.native,title='Implementation needing diagnosis',assignee='backend_data',initial_status='blocked')
        kb.unblock_task(self.c.native,self.task)
        run=kb.claim_task(self.c.native,self.task,claimer='test')
        self.assertTrue(kb.block_task(self.c.native,self.task,reason='Red rejected: generic exception is not an assertion',kind='capability',expected_run_id=run.current_run_id))
        self.files={'server/a.ts':'preserved','tests/a.test.ts':'baseline'}
        self.card=dict(author='backend_data',reviewer='techlead',autonomous=True,base='a'*40,brief='Original work scope',files=self.files,protected=['tests/a.test.ts'])
        self.c.cfg=dict(attempt='test',cards={self.task:self.card})
        for path in (control/'config.json',board/'product-adapter.json'):path.write_text(json.dumps(self.c.cfg))
        Workspace(self.c.private,Mock()).seed('test',self.task,'backend_data','a'*40,self.files,['tests/a.test.ts'])
        self.c.decision=Mock(return_value=None)
    def test_block_without_pr_creates_exactly_one_executable_diagnosis(self):
        self.c.reconcile_work();self.c.reconcile_work()
        tasks=self.c.native.execute('SELECT id,status,assignee FROM tasks WHERE id!=?',(self.task,)).fetchall()
        self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['status'],'ready');self.assertEqual(tasks[0]['assignee'],'techlead')
        packet=json.loads((self.c.root/'team-packets'/f'{tasks[0]["id"]}.json').read_text())
        self.assertEqual(packet['draft_sha256'],digest(self.files));self.assertEqual(packet['allowed_actions'],['resume_author'])
        self.assertEqual(kb.get_task(self.c.native,self.task).status,'blocked')
    def test_independent_approval_resumes_original_card_preserving_draft(self):
        self.c.reconcile_work()
        self.c.decision.return_value=(dict(action='resume_author',head='a'*40,specification=dict(target_task=self.task,draft_sha256=digest(self.files),brief='Diagnose rejected Red; use loadable scaffold and behavioral assertions. Preserve baseline tests and generate fresh valid receipts.')),dict(decision='approve'))
        self.c.reconcile_work();self.c.reconcile_work()
        self.assertEqual(kb.get_task(self.c.native,self.task).status,'ready')
        self.assertEqual(json.loads(self.c.private.execute('SELECT files FROM product_drafts').fetchone()[0]),self.files)
        self.assertEqual(self.c.native.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='unblocked'",(self.task,)).fetchone()[0],2)
    def test_restart_does_not_duplicate_diagnosis(self):
        self.c.reconcile_work();count=self.c.native.execute('SELECT count(*) FROM tasks').fetchone()[0]
        self.c.cfg=json.loads((self.c.root/'config.json').read_text());self.c.reconcile_work()
        self.assertEqual(count,self.c.native.execute('SELECT count(*) FROM tasks').fetchone()[0])
    def test_restart_after_unblock_before_ack_does_not_repeat_transition(self):
        self.c.reconcile_work()
        self.c.decision.return_value=(dict(action='resume_author',head='a'*40,specification=dict(target_task=self.task,draft_sha256=digest(self.files),brief='Preserve baseline tests, diagnose actual rejected assertion evidence and resume original author with fresh valid receipts.')),dict(decision='approve'))
        put=self.c.put;fail=[True]
        def interrupted(key,value):
            if key.startswith('blocked-work:') and value.get('state')=='RESUMED' and fail[0]:
                fail[0]=False;raise RuntimeError('injected crash after native unblock')
            put(key,value)
        with patch.object(self.c,'put',side_effect=interrupted):self.c.reconcile_work()
        self.c.reconcile_work()
        self.assertEqual(kb.get_task(self.c.native,self.task).status,'ready')
        self.assertEqual(self.c.native.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='unblocked'",(self.task,)).fetchone()[0],2)
    def test_publication_error_does_not_skip_later_cards(self):
        cfg=dict(self.c.cfg,cards={'first':{},'second':{}})
        (self.c.root/'config.json').write_text(json.dumps(cfg))
        self.c.publish_one=Mock(side_effect=[PermissionError('first failed'),None])
        self.c.publish_completed()
        self.assertEqual([c.args[0] for c in self.c.publish_one.call_args_list],['first','second'])
    def test_stale_draft_approval_does_not_unblock(self):
        self.c.reconcile_work();self.c.decision.return_value=(dict(action='resume_author',head='a'*40,specification=dict(target_task=self.task,draft_sha256='wrong',brief='x'*120)),dict(decision='approve'))
        self.c.reconcile_work()
        self.assertEqual(kb.get_task(self.c.native,self.task).status,'blocked')
        self.assertEqual(self.c.get('fault:work:'+self.task)['state'],'OPEN')
    def test_one_failure_does_not_starve_next_item(self):
        success=Mock()
        self.c.isolate('bad',Mock(side_effect=PermissionError('bad item')));self.c.isolate('good',success)
        success.assert_called_once();self.assertEqual(self.c.get('fault:bad')['owner'],'cto')
    def test_dispatch_round_robin_survives_restart(self):
        cards={'a':{},'b':{},'c':{}}
        self.assertEqual([k for k,_ in ordered(self.c.board,cards)],['a','b','c'])
        claimed(self.c.board,'a');self.assertEqual([k for k,_ in ordered(self.c.board,cards)],['b','c','a'])
        claimed(self.c.board,'b');self.assertEqual([k for k,_ in ordered(self.c.board,cards)],['c','a','b'])

    def test_two_change_requests_stop_dispatch_until_new_checkpoint(self):
        from product_review_feedback import contain
        kb.unblock_task(self.c.native,self.task)
        for index in range(2):
            run=kb.claim_task(self.c.native,self.task,claimer='test')
            self.assertTrue(kb.request_review(self.c.native,self.task,reviewer='techlead',expected_run_id=run.current_run_id,summary='fixture submission'))
            review=kb.claim_review_task(self.c.native,self.task,claimer='test')
            self.assertTrue(kb.request_changes(self.c.native,self.task,expected_run_id=review.current_run_id,reason='Acceptance criterion not met')[0])
            if index==0:self.assertFalse(contain(self.c.native,self.task,self.card))
        self.assertTrue(contain(self.c.native,self.task,self.card))
        self.assertIn(kb.get_task(self.c.native,self.task).status,('blocked','triage'))
        self.assertFalse(contain(self.c.native,self.task,self.card))
        if kb.get_task(self.c.native,self.task).status=='triage':kb.specify_triage_task(self.c.native,self.task,author='cto')
        else:kb.unblock_task(self.c.native,self.task)
        self.assertFalse(contain(self.c.native,self.task,dict(self.card,review_checkpoint=review.current_run_id)))

    def test_coordination_reviews_have_same_loop_containment(self):
        from product_review_feedback import contain
        self.c.reconcile_work()
        tid=next(t for t in self.c.cfg['cards'] if t!=self.task);card=self.c.cfg['cards'][tid]
        for _ in range(2):
            run=kb.claim_task(self.c.native,tid,claimer='test')
            kb.request_review(self.c.native,tid,reviewer='cto',expected_run_id=run.current_run_id,summary='Diagnosis proposal')
            review=kb.claim_review_task(self.c.native,tid,claimer='test')
            kb.request_changes(self.c.native,tid,expected_run_id=review.current_run_id,reason='The diagnosis still lacks an executable remedy')
        self.assertTrue(contain(self.c.native,tid,card))
        self.assertIn(kb.get_task(self.c.native,tid).status,('blocked','triage'))

    def test_triage_diagnosis_escalates_once_across_callers(self):
        self.c.reconcile_work()
        tid=next(t for t in self.c.cfg['cards'] if t!=self.task)
        for _ in range(5):
            current=kb.get_task(self.c.native,tid)
            if current.status=='triage':break
            if current.status=='blocked':kb.unblock_task(self.c.native,tid)
            run=kb.claim_task(self.c.native,tid,claimer='test')
            kb.block_task(self.c.native,tid,reason='Same capability unavailable',kind='capability',expected_run_id=run.current_run_id)
        self.assertEqual(kb.get_task(self.c.native,tid).status,'triage')
        first=self.c.escalate(tid,'caller-one');second=self.c.escalate(tid,'caller-two')
        self.assertNotEqual(first,tid);self.assertEqual(first,second)
        self.assertEqual(kb.get_task(self.c.native,first).assignee,'cto')

    def test_no_exception_is_not_evidence_of_recovery(self):
        self.c.isolate('waiting',Mock(side_effect=PermissionError('base changed')))
        self.c.isolate('waiting',Mock(return_value=None))
        self.assertNotEqual(self.c.get('fault:waiting')['state'],'RECOVERED')

    def test_escalation_reference_does_not_break_recovery_scan(self):
        self.c.put('blocked-work:historical:12:escalation','t_linked_cto')
        self.c.reconcile_work()
        self.assertEqual(self.c.get('blocked-work:historical:12:escalation'),'t_linked_cto')

class TDDDiagnosticTests(unittest.TestCase):
    def test_generic_throw_is_not_silently_accepted(self):
        self.assertEqual(rejection('red',False,'Error: not implemented',1,True,3)['code'],'RED_NOT_BEHAVIORAL_ASSERTION')
    def test_rejected_red_is_distinct_from_changed_tests(self):
        red=dict(accepted=False,tests_sha256='tests',base='base',image='image')
        self.assertEqual(red_mismatch(red,'tests','base','image'),'RED_NOT_ACCEPTED')
        red['accepted']=True
        self.assertEqual(red_mismatch(red,'different','base','image'),'RED_TESTS_CHANGED')
        self.assertIsNone(red_mismatch(red,'tests','base','image'))
