import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import publish_u3_coverage as publication


class CoveragePublicationTests(unittest.TestCase):
    def fixture(self, root):
        repo=root/'repo';repo.mkdir();snapshot=root/'snapshot';snapshot.mkdir()
        def git(*args):return publication.git(repo,*args).decode().strip()
        git('init','-q');git('config','user.name','Test');git('config','user.email','test@example.invalid')
        old={'app.js':b'old product\n','tests/test_old.py':b'old assertions\n'}
        for name,content in old.items():
            path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        git('add','.');git('commit','-qm','base');base=git('rev-parse','HEAD')
        content={**old,**{name:b'new coverage\n' for name in publication.TESTS}}
        metadata={}
        for name,raw in content.items():
            path=snapshot/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            metadata[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        raw=json.dumps(dict(files=metadata),sort_keys=True).encode();(snapshot/'manifest.json').write_bytes(raw)
        digest=hashlib.sha256(raw).hexdigest()
        c=dict(schema='u3-coverage-integration-v1',classification='existing_behavior_coverage_only',
            base_sha=base,base_manifest_sha256='b'*64,manifest_sha256=digest,
            new_test_sha256={name:metadata[name]['sha256'] for name in publication.TESTS},
            author='author',reviewer='reviewer',previous_files_unchanged=True,
            product_admission_authorized=False,historical_tdd_red=False,
            delivery_approval=False,merge_authorized=False,deploy_authorized=False)
        r=dict(schema='u3-coverage-integration-review-v1',contract_sha256=publication.digest(c),
            integration_review_approved=True,reviewer='reviewer',manifest_sha256=digest,
            decision=dict(action='approve_test_revision',manifest_sha256=digest,optional_files=[]),
            historical_tdd_red=False,delivery_approval=False,merge_authorized=False,deploy_authorized=False)
        bundle=dict(schema='u3-coverage-publication-input-v1',contract=c,receipt=r)
        return repo,snapshot,bundle,content

    def test_exact_snapshot_and_original_git_bytes_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,content=self.fixture(Path(tmp))
            self.assertEqual(publication.preflight(repo,bundle,snapshot),content)

    def test_changed_product_and_missing_test_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,_=self.fixture(Path(tmp))
            (snapshot/'app.js').write_bytes(b'changed product')
            with self.assertRaises(ValueError):publication.preflight(repo,bundle,snapshot)

    def test_stale_receipt_and_fake_red_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,_,bundle,_=self.fixture(Path(tmp))
            for key,value in (('historical_tdd_red',True),('merge_authorized',True),
                              ('deploy_authorized',True),('delivery_approval',True)):
                altered=copy.deepcopy(bundle);altered['receipt'][key]=value
                with self.assertRaises(ValueError):publication.validate_bundle(altered)
            altered=copy.deepcopy(bundle);altered['receipt']['manifest_sha256']='e'*64
            with self.assertRaises(ValueError):publication.validate_bundle(altered)

    def test_changed_contract_cannot_reuse_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,_,bundle,_=self.fixture(Path(tmp))
            altered=copy.deepcopy(bundle);altered['contract']['base_sha']='e'*40
            with self.assertRaises(ValueError):publication.validate_bundle(altered)

    def test_commit_does_not_touch_worktree_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,_,bundle,content=self.fixture(Path(tmp))
            before=publication.git(repo,'rev-parse','HEAD')
            (repo/'app.js').write_bytes(b'user uncommitted work')
            (repo/'untracked.txt').write_bytes(b'user file')
            with patch.object(publication,'git',wraps=publication.git) as git:
                git.side_effect=lambda r,*args,**kw: b'' if args[:2]==('ls-remote','origin') else publication.run(
                    'git','-C',str(r),*args,data=kw.get('data'),env=kw.get('env'))
                head=publication.ensure_commit(repo,bundle['contract']['base_sha'],content)
                self.assertEqual(publication.ensure_commit(repo,bundle['contract']['base_sha'],content),head)
            self.assertEqual(publication.git(repo,'rev-parse','HEAD'),before)
            self.assertEqual((repo/'app.js').read_bytes(),b'user uncommitted work')
            self.assertEqual((repo/'untracked.txt').read_bytes(),b'user file')
            publication.verify_commit(repo,head,bundle['contract']['base_sha'],content)

    def test_commit_with_product_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,_,bundle,content=self.fixture(Path(tmp))
            with patch.object(publication,'git',wraps=publication.git) as git:
                git.side_effect=lambda r,*args,**kw: b'' if args[:2]==('ls-remote','origin') else publication.run(
                    'git','-C',str(r),*args,data=kw.get('data'),env=kw.get('env'))
                head=publication.ensure_commit(repo,bundle['contract']['base_sha'],content)
            altered=dict(content);altered['app.js']=b'changed'
            with self.assertRaises(ValueError):publication.verify_commit(repo,head,bundle['contract']['base_sha'],altered)

    def test_wrong_remote_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,_,_,_=self.fixture(Path(tmp))
            publication.git(repo,'remote','add','origin','https://github.com/codifydeep/truco-online.git')
            with self.assertRaises(ValueError):publication.remote_base(repo)

    def test_repository_metadata_omitted_from_snapshot_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,content=self.fixture(Path(tmp))
            workflow=repo/'.github/workflows/ci.yml';workflow.parent.mkdir(parents=True)
            workflow.write_bytes(b'protected workflow\n')
            publication.git(repo,'add','.github');publication.git(repo,'commit','-qm','metadata')
            base=publication.git(repo,'rev-parse','HEAD').decode().strip()
            bundle['contract']['base_sha']=base
            bundle['receipt']['contract_sha256']=publication.digest(bundle['contract'])
            approved=publication.preflight(repo,bundle,snapshot)
            self.assertEqual(approved,content)
            with patch.object(publication,'git',wraps=publication.git) as git:
                git.side_effect=lambda r,*args,**kw: b'' if args[:2]==('ls-remote','origin') else publication.run(
                    'git','-C',str(r),*args,data=kw.get('data'),env=kw.get('env'))
                head=publication.ensure_commit(repo,base,approved)
            self.assertEqual(publication.git(repo,'show',head+':.github/workflows/ci.yml'),b'protected workflow\n')
            publication.verify_commit(repo,head,base,approved)

    def test_runtime_checkpoint_is_not_mislabeled_as_git_coverage_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,_=self.fixture(Path(tmp))
            path=snapshot/'tests/test_predecessor.py';path.write_bytes(b'prior runtime checkpoint\n')
            raw=json.loads((snapshot/'manifest.json').read_bytes())
            raw['files']['tests/test_predecessor.py']=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=len(path.read_bytes()))
            payload=json.dumps(raw,sort_keys=True).encode();(snapshot/'manifest.json').write_bytes(payload)
            sha=hashlib.sha256(payload).hexdigest();bundle['contract']['manifest_sha256']=sha
            bundle['receipt']['manifest_sha256']=sha;bundle['receipt']['decision']['manifest_sha256']=sha
            bundle['receipt']['contract_sha256']=publication.digest(bundle['contract'])
            with self.assertRaises(publication.PublicationBlocked) as caught:
                publication.preflight(repo,bundle,snapshot)
            self.assertEqual(caught.exception.diagnostic['extra_files'],['tests/test_predecessor.py'])
            self.assertEqual(caught.exception.diagnostic['owner'],'cto')
            self.assertFalse(caught.exception.diagnostic['merge_authorized'])

    def test_new_git_binding_does_not_rewrite_original_review_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,content=self.fixture(Path(tmp))
            original=copy.deepcopy(bundle)
            (repo/'metadata.txt').write_bytes(b'new Git metadata\n')
            publication.git(repo,'add','metadata.txt');publication.git(repo,'commit','-qm','integrated base')
            target=publication.git(repo,'rev-parse','HEAD').decode().strip()
            self.assertEqual(publication.preflight(repo,bundle,snapshot,target_base=target),content)
            self.assertEqual(bundle,original)

    def test_new_git_binding_cannot_hide_different_product_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,_=self.fixture(Path(tmp))
            (repo/'app.js').write_bytes(b'other implementation')
            publication.git(repo,'add','app.js');publication.git(repo,'commit','-qm','wrong base')
            target=publication.git(repo,'rev-parse','HEAD').decode().strip()
            with self.assertRaises(publication.PublicationBlocked):
                publication.preflight(repo,bundle,snapshot,target_base=target)
