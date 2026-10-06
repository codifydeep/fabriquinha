import json
from test_product_tdd import TDDTests
from product_controller import ProductController


class ProductControllerTests(TDDTests):
    def setUp(self):
        super().setUp()
        self.c = ProductController(self.w, self.t, self.runner)

    def call(self, operation, **kwargs):
        return self.c.handle(dict(self.req, operation='product_' + operation, **kwargs))

    def prepare(self):
        self.call('test', phase='red'); self.change()
        self.call('test', phase='green'); self.call('test', phase='suite')

    def test_submit_without_suite_rejected(self):
        with self.assertRaises(PermissionError): self.call('submit', version=0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM product_submissions').fetchone()[0], 0)

    def test_atomic_idempotent_envelope(self):
        self.prepare()
        result = self.call('submit', version=1)
        self.assertEqual(result, self.call('submit', version=1))
        self.assertFalse(result['handed_off'])
        stored = self.db.execute('SELECT envelope FROM product_handoffs').fetchone()[0]
        self.assertEqual(json.loads(stored), result)
        self.assertEqual(self.db.execute('SELECT count(*) FROM product_submissions').fetchone()[0], 1)

    def test_transaction_failure_rolls_back_snapshot(self):
        self.prepare()
        self.db.execute("CREATE TRIGGER fail_handoff BEFORE INSERT ON product_handoffs BEGIN SELECT RAISE(ABORT,'injected crash'); END")
        with self.assertRaises(Exception): self.call('submit', version=1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM product_submissions').fetchone()[0], 0)

    def test_other_run_cannot_reuse_suite(self):
        self.prepare(); self.claim['run'] = 2; self.req['run'] = 2
        with self.assertRaises(PermissionError): self.call('submit', version=1)

    def test_agent_cannot_supply_command_or_runner(self):
        with self.assertRaises(PermissionError): self.call('test', phase='red', command='touch /tmp/x')
        with self.assertRaises(PermissionError): self.call('freeze', version=0)

    def test_reviewer_cannot_submit_or_test(self):
        self.prepare(); result = self.call('submit', version=1)
        self.claim.update(mode='review', profile='techlead')
        self.assertIn('src/a.mjs', self.call('inspect', revision=result['revision'])['files'])
        with self.assertRaises(PermissionError): self.call('submit', version=1)
        with self.assertRaises(PermissionError): self.call('test', phase='red')

    def test_paged_author_read_preserves_edit_identity(self):
        draft=self.call('read');page=self.call('read_file',path='src/a.mjs',offset=0,revision='')
        self.assertEqual(page['content'],draft['files']['src/a.mjs'])
        self.assertEqual(page['delivery'],{k:draft[k] for k in ('version','sha256')})
        with self.assertRaises(PermissionError):self.call('read_file',path='/etc/passwd',offset=0,revision='')

    def test_author_status_exposes_durable_review_findings(self):
        envelope=dict(decision='request_changes',reason='Missing real server-to-shared consumption; do not submit a comment-only stub.',revision='old',review_run=9)
        self.db.execute('INSERT INTO product_verdicts VALUES(?,?,?,?,?)',('trial','t_one',9,json.dumps(envelope),'DELIVERED'));self.db.commit()
        self.assertEqual(self.call('status')['latest_review'],envelope)

    def test_reviewer_pages_snapshot_not_mutable_author_draft(self):
        revision=self.reviewer()
        page=self.call('read_file',path='src/a.mjs',offset=0,revision=revision)
        self.assertEqual(page['content'],'green')
        with self.assertRaises(ValueError):self.call('read_file',path='src/a.mjs',offset=0,revision='wrong')
        with self.assertRaises(PermissionError):self.call('read')

    def test_submitted_execution_is_sealed(self):
        self.prepare(); self.call('submit', version=1)
        draft=self.call('read')
        with self.assertRaises(PermissionError):
            self.call('edit',version=1,sha256=draft['sha256'],replacements={'src/a.mjs':'changed'})

    def test_service_disabled_by_default(self):
        from review_controller import Controller
        service=Controller.__new__(Controller)
        with self.assertRaises(PermissionError): service.handle(dict(self.req,operation='product_read'))

    def test_registered_product_cannot_use_legacy_handler(self):
        from review_controller import Controller
        self.w.claim.cards={'t_one':{}}
        service=Controller.__new__(Controller);service.product=self.c
        with self.assertRaises(PermissionError):service.handle(dict(self.req,operation='freeze'))

    def reviewer(self):
        self.prepare(); result=self.call('submit',version=1)
        self.db.execute("UPDATE product_handoffs SET state='DELIVERED'");self.db.commit()
        self.claim.update(mode='review',profile='techlead',run=2);self.req['run']=2
        return result['revision']

    def test_independent_validation_is_not_approval(self):
        revision=self.reviewer()
        result=self.call('review_test',revision=revision)
        self.assertTrue(result['passed']);self.assertFalse(result['approved'])
        calls=self.calls
        self.assertEqual(result,self.call('review_test',revision=revision));self.assertEqual(calls,self.calls)

    def test_review_requires_delivered_handoff(self):
        revision=self.reviewer()
        self.db.execute("UPDATE product_handoffs SET state='PREPARED'");self.db.commit()
        with self.assertRaises(PermissionError):self.call('review_test',revision=revision)

    def test_review_rejects_runner_tampering(self):
        revision=self.reviewer()
        def bad(files,image):
            result=self.runner(files,image);result['snapshot']={};return result
        self.c.runner=bad
        with self.assertRaises(PermissionError):self.call('review_test',revision=revision)

    def test_review_rejects_revoked_claim(self):
        revision=self.reviewer()
        def bad(files,image):
            result=self.runner(files,image);self.claim['claim']='revoked';return result
        self.c.runner=bad
        with self.assertRaises(PermissionError):self.call('review_test',revision=revision)
        self.assertEqual(self.db.execute('SELECT count(*) FROM product_review_tests').fetchone()[0],0)

    def test_review_ignored_tests_fail(self):
        revision=self.reviewer()
        def bad(files,image):
            result=self.runner(files,image);result['output']+='\n# skipped 1\n';return result
        self.c.runner=bad
        self.assertFalse(self.call('review_test',revision=revision)['passed'])

    def test_approval_requires_independent_test(self):
        revision=self.reviewer()
        with self.assertRaises(PermissionError):
            self.call('verdict',revision=revision,decision='approve',reason='Reviewed implementation and regression coverage.')

    def test_approval_bound_and_idempotent(self):
        revision=self.reviewer();self.call('review_test',revision=revision)
        result=self.call('verdict',revision=revision,decision='approve',reason='Reviewed implementation and regression coverage.')
        self.assertFalse(result['release_homologated'])
        self.assertEqual(result,self.call('verdict',revision=revision,decision='approve',reason='Reviewed implementation and regression coverage.'))
        with self.assertRaises(PermissionError):
            self.call('verdict',revision=revision,decision='request_changes',reason='A conflicting verdict in the same execution.')

    def test_changes_need_no_successful_test_but_require_reason(self):
        revision=self.reviewer()
        with self.assertRaises(ValueError):self.call('verdict',revision=revision,decision='request_changes',reason='')
        result=self.call('verdict',revision=revision,decision='request_changes',reason='Missing zero-player acceptance coverage in the submission.')
        self.assertEqual(result['author'],'backend_data')

    def test_author_cannot_approve(self):
        self.prepare();submission=self.call('submit',version=1)
        with self.assertRaises(PermissionError):
            self.call('verdict',revision=submission['revision'],decision='approve',reason='Author attempts to approve own work.')
