import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import start_u3_delivery_review as start


class DeliveryReviewAdmissionTests(unittest.TestCase):
    def fixture(self):
        bundle=dict(contract=dict(manifest_sha256='a'*64),receipt=dict(task='review'))
        binding=dict(target_base=start.review.BASE)
        published=dict(stage='pr_open',pr_number=36,head_sha=start.review.HEAD,base_sha=start.review.BASE,
            git_binding=binding,manifest_sha256='a'*64,review_receipt_sha256=start.publication.digest(bundle['receipt']))
        pr=dict(state='open',merged=False,
            head=dict(sha=start.review.HEAD,ref=start.publication.BRANCH,repo=dict(full_name=start.publication.REPOSITORY)),
            base=dict(sha=start.review.BASE,ref='main',repo=dict(full_name=start.publication.REPOSITORY)))
        return bundle,binding,published,pr

    def run_bridge(self, changed=None, ci_error=None):
        bundle,binding,published,pr=self.fixture()
        if changed:published.update(changed)
        with tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
            receipt=Path(tmp)/'receipt.json';receipt.write_text(json.dumps(published))
            stack.enter_context(patch.object(start.publication,'RECEIPT',receipt))
            for name,result in (('load_bundle',bundle),('validate_bundle',None),
                    ('publication_base',(start.review.BASE,binding)),('export_snapshot',None),
                    ('preflight',{'test':b'preserved'}),('verify_commit',None)):
                stack.enter_context(patch.object(start.publication,name,return_value=result))
            stack.enter_context(patch.object(start.gates,'api',side_effect=[pr,{},{}]))
            stack.enter_context(patch.object(start.gates,'protection_ok'))
            stack.enter_context(patch.object(start.gates,'exact_ci',side_effect=ci_error))
            dispatch=stack.enter_context(patch.object(start.publication,'run',return_value=b'{"stage":"awaiting_budget"}'))
            output=io.StringIO()
            try:
                with contextlib.redirect_stdout(output):start.main()
            except ValueError:
                dispatch.assert_not_called()
                raise
            self.assertEqual(dispatch.call_args.args[:4],('docker','exec','-e','PYTHONPATH=/'))
            self.assertEqual(json.loads(output.getvalue()),dict(stage='awaiting_budget'))

    def test_exact_verified_publication_reaches_fixed_controller_admission(self):
        self.run_bridge()

    def test_changed_sha_snapshot_or_git_binding_does_not_dispatch(self):
        for changed in (dict(head_sha='b'*40),dict(manifest_sha256='b'*64),
                        dict(git_binding={}),dict(review_receipt_sha256='b'*64)):
            with self.assertRaises(ValueError):self.run_bridge(changed)

    def test_pending_or_failed_ci_does_not_dispatch_a_reviewer(self):
        for error in (start.gates.CIWaiting('pending'),ValueError('failed')):
            with self.assertRaises(ValueError):self.run_bridge(ci_error=error)
