"""Administrative seed cannot rewrite an existing branch or resume agents."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.effects import Pending,EffectBlocked
from test_preparation import project

spec=importlib.util.spec_from_file_location('bootstrap_branch',ROOT/'scripts/bootstrap_hermes_branch.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)


class BranchBootstrap(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.project=Project.parse({**project(),'local_ci':dict(context='fabriquinha-local-ci',publisher='fixture')})
        self.runtime=SimpleNamespace(project=self.project,store=Store(Path(temp.name)/'private'),
            control=SimpleNamespace(read=lambda:dict(paused=True)),
            status=lambda:dict(cards=[],control=dict(drained=True)))
        self.head=None;self.pushes=0;self.puts=0;self.lost=False;self.protection=None
        self.main=dict(required_status_checks={'contexts':['ci']})
        self.repo=SimpleNamespace(git=lambda *a:b'',remote_head=lambda branch:'a'*40 if branch=='main' else self.head,
            propose=lambda *a:'b'*40,push=self.push,_manifest=lambda head:{})
        self.github=SimpleNamespace(repo='example/product',cli=self.cli)
        self.repo_patch=patch.object(bootstrap,'Repository',return_value=self.repo);self.repo_patch.start();self.addCleanup(self.repo_patch.stop)
        self.gh_patch=patch.object(bootstrap,'GitHub',return_value=self.github);self.gh_patch.start();self.addCleanup(self.gh_patch.stop)

    def push(self,branch,head):
        self.pushes+=1;self.head=head
        if self.lost:raise TimeoutError('accepted; lost ACK')

    def cli(self,*args,data=None):
        if args==('api','user'):return json.dumps({'login':'fixture'})
        if '/branches/main/protection' in args[-1]:return json.dumps(self.main)
        if 'PUT' in args:
            self.puts+=1;value=json.loads(data)
            self.protection={**value,'enforce_admins':{'enabled':True},'allow_force_pushes':{'enabled':False},
                'allow_deletions':{'enabled':False},'required_conversation_resolution':{'enabled':True}}
        return json.dumps(self.protection)

    def test_new_branch_retains_parent_and_does_not_claim_delivery_or_repeat_mutations(self):
        result=bootstrap.bootstrap(self.runtime)
        self.assertEqual(result['parent'],'a'*40);self.assertTrue(result['main_unchanged'])
        self.assertFalse(result['product_delivery']);self.assertFalse(result['delivery_approval'])
        self.assertEqual(bootstrap.bootstrap(self.runtime),result)
        self.assertEqual((self.pushes,self.puts),(1,1))

    def test_lost_push_ack_is_observed_without_a_second_push(self):
        self.lost=True
        with self.assertRaises(Pending):bootstrap.bootstrap(self.runtime)
        bootstrap.bootstrap(self.runtime);self.assertEqual((self.pushes,self.puts),(1,1))

    def test_existing_branch_is_never_replaced(self):
        self.head='c'*40
        with self.assertRaisesRegex(ValueError,'existing branches'):bootstrap.bootstrap(self.runtime)
        self.assertEqual((self.pushes,self.puts),(0,0))

    def test_nonempty_board_or_active_effect_refuses_bootstrap(self):
        for status in (dict(cards=[{'id':'task'}],control={'drained':True}),dict(cards=[],control={'drained':False})):
            self.runtime.status=lambda:status
            with self.assertRaises(ValueError):bootstrap.bootstrap(self.runtime)
        self.assertEqual((self.pushes,self.puts),(0,0))

    def test_preview_has_no_remote_mutation_and_baseline_reset_needs_exact_ack(self):
        self.repo._manifest=lambda head:{'test_existing.py':{'sha256':'old','executable':False}}
        value=bootstrap.bootstrap(self.runtime,preview=True)
        self.assertEqual(value['head'],'b'*40);self.assertEqual(value['removed_paths'],['test_existing.py'])
        self.assertTrue(value['requires_baseline_reset_approval']);self.assertEqual((self.pushes,self.puts),(0,0))
        with self.assertRaisesRegex(ValueError,'baseline'):bootstrap.bootstrap(self.runtime)
        with self.assertRaises(ValueError):bootstrap.bootstrap(self.runtime,expected_head='c'*40)
        self.assertEqual((self.pushes,self.puts),(0,0))
        result=bootstrap.bootstrap(self.runtime,expected_head='b'*40)
        self.assertTrue(result['baseline_reset']);self.assertEqual(result['baseline_reset_ack'],'b'*40)
        # Receipt of this exact decision survives restart/replay; no new approval.
        self.assertEqual(result,bootstrap.bootstrap(self.runtime));self.assertEqual((self.pushes,self.puts),(1,1))

    def test_changed_main_after_preview_is_refused_before_external_mutation(self):
        bootstrap.bootstrap(self.runtime,preview=True)
        self.repo.remote_head=lambda branch:'c'*40 if branch=='main' else self.head
        with self.assertRaises(EffectBlocked):bootstrap.bootstrap(self.runtime,expected_head='b'*40)
        self.assertEqual((self.pushes,self.puts),(0,0))


if __name__=='__main__':unittest.main()
