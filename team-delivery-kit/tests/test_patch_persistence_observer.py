import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from broker import patch_persistence_observer as observer
from broker.patch_receipt_contract import receipt


class PatchObserverTests(unittest.TestCase):
    def test_bounded_regular_test_only_and_links_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'tests').mkdir();target=root/'tests'/'test_new.py';target.write_text('x=1\n')
            self.assertEqual(observer.observe(str(target),d)['sha256'],hashlib.sha256(b'x=1\n').hexdigest())
            link=root/'tests'/'test_link.py';link.symlink_to(target)
            self.assertIsNone(observer.observe(str(link),d))
            (root/'linked').symlink_to(root/'tests',target_is_directory=True)
            self.assertIsNone(observer.observe(str(root/'linked'/'test_new.py'),d))
            hard=root/'tests'/'test_hard.py';os.link(target,hard)
            self.assertIsNone(observer.observe(str(hard),d));hard.unlink()
            target.write_bytes(b'x'*32769);self.assertIsNone(observer.observe(str(target),d))
            self.assertIsNone(observer.observe(str(root/'app.py'),d))
            self.assertIsNone(observer.observe(str(root/'tests'/'..'/'secret.py'),d))

    def test_handler_runs_once_and_its_rejection_is_preserved(self):
        facts=[dict(path='tests/test_new.py',sha256='a'*64),dict(path='tests/test_new.py',sha256='a'*64)]
        calls=[]
        def handler(args,**kw):calls.append((args,kw));return json.dumps({'success':False,'error':'denied'})
        with patch.dict(os.environ,DELIVERY_EXECUTION_MODE='implementation',HERMES_FENCED_INPLACE_WRITES='1'), \
                patch.object(observer,'observe',side_effect=facts):
            raw=observer.observed_call(handler,{'path':'tests/test_new.py'},{'task_id':'author'},lambda *_:'/workspace/tests/test_new.py')
        value=json.loads(raw);self.assertEqual(len(calls),1);self.assertEqual(value['error'],'denied')
        self.assertFalse(receipt('patch',raw)['success'])
        self.assertFalse(receipt('patch',raw)['test_hash_observation']['changed'])

    def test_review_and_nonreplace_are_not_observed(self):
        with patch.dict(os.environ,DELIVERY_EXECUTION_MODE='review',HERMES_FENCED_INPLACE_WRITES='1'), \
                patch.object(observer,'observe') as read:
            self.assertEqual(observer.observed_call(lambda *_args,**kw:'unchanged',{}, {},lambda *_:None),'unchanged')
            read.assert_not_called()

    def test_unknown_or_authorizing_observation_is_not_exposed(self):
        good=dict(operation='handler_test_hash_observation_v1',path='tests/test_new.py',before_sha256='a'*64,
            after_sha256='b'*64,changed=True,evidence_scope='immediate_handler_observation_not_final_snapshot',
            delivery_approval=False,author_retry_authorized=False)
        self.assertEqual(receipt('patch',json.dumps(dict(success=True,_patch_persistence_v1=good)))['test_hash_observation'],good)
        for bad in (dict(good,path='../secret.py'),dict(good,changed=False),dict(good,delivery_approval=True),dict(good,raw='private')):
            self.assertNotIn('test_hash_observation',receipt('patch',json.dumps(dict(success=True,_patch_persistence_v1=bad))))

    def test_unpinned_source_cannot_be_adapted(self):
        with self.assertRaises(ValueError):observer.adapt('def _handle_patch(args, **kw):\n return "mock"\n')
