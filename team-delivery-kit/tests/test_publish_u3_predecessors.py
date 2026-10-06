import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import publish_u3_predecessors as p


class PredecessorPublicationTests(unittest.TestCase):
    def fixture(self,root):
        repo=root/'repo';repo.mkdir();snapshot=root/'snapshot';snapshot.mkdir()
        git=lambda *args:p.common.git(repo,*args).decode().strip()
        git('init','-q');git('config','user.name','Test');git('config','user.email','test@example.invalid')
        old={name:b'old product\n' for name in p.CODE};old['tests/test_old.py']=b'old assertion\n'
        for name,raw in old.items():
            path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        git('add','.');git('commit','-qm','base');base=git('rev-parse','HEAD')
        content={**old,**{name:b'reviewed implementation\n' for name in p.CODE},
                 **{name:b'new test\n' for name in p.TESTS}}
        metadata={}
        for name,raw in content.items():
            path=snapshot/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            metadata[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        raw=json.dumps(dict(files=metadata),sort_keys=True).encode();(snapshot/'manifest.json').write_bytes(raw)
        sha=hashlib.sha256(raw).hexdigest();proofs=[]
        for i,name in enumerate(('tests/test_feedback_search_client.py','tests/test_incremental_u2.py')):
            green=dict(exit_code=0,full_suite=True,author='author',test_count=(249,255)[i],
                manifest_sha256=('a'*64,sha)[i],base_manifest_sha256=('b'*64,'a'*64)[i],
                test_sha256={name:metadata[name]['sha256']})
            review=dict(reviewer='reviewer',decision='approve',manifest_sha256=green['manifest_sha256'],
                green_receipt_sha256=p.checkpoint_digest(green))
            proofs.append(dict(unit=('U1','U2')[i],green=green,review=review))
        return repo,snapshot,dict(schema='u3-predecessor-publication-input-v1',author='author',reviewer='reviewer',
            base_sha=base,manifest_sha256=sha,proofs=proofs),content

    def test_qualified_predecessor_snapshot_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,content=self.fixture(Path(tmp))
            self.assertEqual(p.preflight(repo,bundle,snapshot),content)

    def test_stale_manifest_review_or_suite_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,_=self.fixture(Path(tmp))
            for key,value in (('decision','request_changes'),('reviewer','author'),('green_receipt_sha256','e'*64)):
                altered=copy.deepcopy(bundle);altered['proofs'][1]['review'][key]=value
                with self.assertRaises(ValueError):p.preflight(repo,altered,snapshot)

    def test_checkpoint_digest_uses_ledger_canonical_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,_=self.fixture(Path(tmp))
            altered=copy.deepcopy(bundle)
            altered['proofs'][1]['review']['green_receipt_sha256']=p.common.digest(altered['proofs'][1]['green'])
            with self.assertRaises(ValueError):p.preflight(repo,altered,snapshot)

    def test_new_coverage_files_cannot_leak_into_predecessor_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,snapshot,bundle,_=self.fixture(Path(tmp))
            path=snapshot/'tests/test_u3_c01_controls.py';path.write_bytes(b'outside scope')
            with self.assertRaises(ValueError):p.preflight(repo,bundle,snapshot)

    def test_predecessor_commit_preserves_checkout_and_previous_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,_,bundle,content=self.fixture(Path(tmp))
            before=p.common.git(repo,'rev-parse','HEAD')
            with patch.object(p.common,'git',wraps=p.common.git) as git:
                git.side_effect=lambda r,*args,**kw:b'' if args[:2]==('ls-remote','origin') else p.common.run(
                    'git','-C',str(r),*args,data=kw.get('data'),env=kw.get('env'))
                head=p.ensure_commit(repo,bundle['base_sha'],content)
                self.assertEqual(head,p.ensure_commit(repo,bundle['base_sha'],content))
            self.assertEqual(p.common.git(repo,'rev-parse','HEAD'),before)
            self.assertEqual(p.common.git(repo,'show',head+':tests/test_old.py'),b'old assertion\n')
            p.verify_commit(repo,head,bundle['base_sha'],content)

    def test_commit_outside_declared_scope_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo,_,bundle,content=self.fixture(Path(tmp))
            altered=dict(content);altered['tests/test_old.py']=b'weakened'
            with patch.object(p.common,'git',wraps=p.common.git) as git:
                git.side_effect=lambda r,*args,**kw:b'' if args[:2]==('ls-remote','origin') else p.common.run(
                    'git','-C',str(r),*args,data=kw.get('data'),env=kw.get('env'))
                with self.assertRaises(ValueError):p.ensure_commit(repo,bundle['base_sha'],altered)
