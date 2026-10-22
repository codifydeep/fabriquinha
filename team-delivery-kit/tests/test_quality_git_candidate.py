"""Resumable first candidates in real local Git; no GitHub publication or model."""
import copy
import json
import unittest
from unittest.mock import patch
import quality_git_candidate as candidate
import test_quality_git_binding as fixtures


class GitCandidateTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.GitBindingTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.plan={**f.plan,'run_id':'a0000000-0000-4000-8000-000000000001',
            'issue_id':'a0000000-0000-4000-8000-000000000002'}
        self.request='a0000000-0000-4000-8000-000000000003';self.task='a0000000-0000-4000-8000-000000000004'
        self.frozen={**f.f.plan['baseline_tests'],**f.f.prepared['test_sha256']}
        self.private=f.f.root/'private';self.private.mkdir(mode=0o700)

    def call(self):
        return candidate.materialize(self.f.repo,self.f.snapshot,self.f.sha,self.plan,self.frozen,
            self.request,self.task,self.private)

    def test_local_candidate_is_exact_and_does_not_touch_checkout_index_or_main(self):
        before=(self.f.git('rev-parse','HEAD'),self.f.git('status','--porcelain'),self.f.git('write-tree'))
        report=self.call()
        self.assertEqual(report['stage'],'ready');self.assertFalse(report['merge_authorized'])
        self.assertFalse(report['delivery_approval']);self.assertFalse(report['execution_authorized'])
        self.assertTrue(report['ref'].startswith('refs/delivery-kit/quality/'))
        self.assertEqual(self.f.git('rev-parse',report['ref']),report['commit_sha'])
        self.assertEqual(before,(self.f.git('rev-parse','HEAD'),self.f.git('status','--porcelain'),self.f.git('write-tree')))
        self.assertEqual(report['git_proof']['manifest_sha256'],self.f.sha)

    def test_repeat_uses_the_same_candidate_and_journal_not_a_new_timestamp(self):
        with patch.object(candidate.time,'time',return_value=1000):first=self.call()
        with patch.object(candidate.time,'time',return_value=2000):second=self.call()
        self.assertEqual(first,second)
        self.assertEqual(self.f.git('rev-list','--count',first['ref']),self.f.git('rev-list','--count',first['commit_sha']))

    def test_changed_frozen_input_cannot_reuse_original_request_or_ref(self):
        first=self.call();self.frozen['tests/test_new.py']='f'*64
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.f.git('rev-parse',first['ref']),first['commit_sha'])

    def test_snapshot_or_protected_policy_change_is_rejected_before_publication(self):
        (self.f.snapshot/'AGENTS.md').write_bytes(b'changed\n');self.f.manifest()
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.f.git('for-each-ref','--format=%(refname)','refs/delivery-kit/quality/'),'')

    def test_different_existing_ref_is_never_overwritten(self):
        ref=candidate.ref_name(self.plan,self.task)
        self.f.git('update-ref',ref,self.f.base)
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.f.git('rev-parse',ref),self.f.base)

    def test_lost_ref_ack_observes_expected_ref_without_another_update(self):
        original=candidate.write_git
        def uncertain(repo,*args,**kwargs):
            value=original(repo,*args,**kwargs)
            if args[0]=='update-ref':raise TimeoutError('local ref acknowledgement lost')
            return value
        with patch.object(candidate,'write_git',side_effect=uncertain):
            with self.assertRaises(candidate.Pending):self.call()
        with patch.object(candidate,'write_git',side_effect=AssertionError('no second ref update')):
            report=self.call()
        self.assertEqual(report['stage'],'ready')

    def test_restart_before_publication_attempt_can_perform_the_first_cas_once(self):
        original=candidate.binding.verify
        with patch.object(candidate.binding,'verify',side_effect=TimeoutError('before ref attempt')):
            with self.assertRaises(candidate.Pending):self.call()
        with patch.object(candidate.binding,'verify',side_effect=original),\
                patch.object(candidate,'write_git',wraps=candidate.write_git) as writes:
            report=self.call()
        self.assertEqual(report['stage'],'ready')
        self.assertEqual(sum(c.args[1]=='update-ref' for c in writes.call_args_list),1)

    def test_symbolic_ref_race_never_writes_a_user_branch(self):
        original=candidate.write_git;ref=candidate.ref_name(self.plan,self.task)
        def interfere(repo,*args,**kwargs):
            if args[0]=='update-ref':self.f.git('symbolic-ref',ref,'refs/heads/never-touch')
            return original(repo,*args,**kwargs)
        with patch.object(candidate,'write_git',side_effect=interfere):
            try:self.call()
            except ValueError:pass  # Ref conflict is allowed; another branch write is not.
        self.assertEqual(self.f.git('for-each-ref','--format=%(refname)','refs/heads/never-touch'),'')

    def test_dirty_and_staged_user_files_are_preserved_byte_for_byte(self):
        (self.f.repo/'app.py').write_bytes(b'USER_WORK=99\n');self.f.git('add','app.py')
        (self.f.repo/'notes.txt').write_bytes(b'untracked user notes\n')
        index=self.f.repo/'.git/index'
        before=(index.read_bytes(),self.f.git('status','--porcelain'),(self.f.repo/'app.py').read_bytes())
        self.assertEqual(self.call()['stage'],'ready')
        self.assertEqual(before,(index.read_bytes(),self.f.git('status','--porcelain'),(self.f.repo/'app.py').read_bytes()))

    def test_ready_receipt_does_not_depend_on_ephemeral_export_directory(self):
        first=self.call()
        self.f.snapshot=self.f.snapshot.parent/'export-already-retired'
        self.assertEqual(self.call(),first)


if __name__=='__main__':unittest.main()
