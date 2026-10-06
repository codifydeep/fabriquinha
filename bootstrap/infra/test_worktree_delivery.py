"""Local Git/worktree acceptance. Not an agent/PR/CI or product certification."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

def run(root,*args,ok=True):
    p=subprocess.run(args,cwd=root,capture_output=True,text=True,
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=60)
    if ok and p.returncode: raise RuntimeError(p.stderr or p.stdout)
    return p

def git(root,*args): return run(root,'git',*args).stdout.strip()

with tempfile.TemporaryDirectory(prefix='hermes-worktree-acceptance-') as folder:
    root=Path(folder); remote=root/'remote.git'; repo=root/'repo'
    git(root,'init','--bare',str(remote)); git(root,'init','-b','release/fixture',str(repo))
    git(repo,'config','user.name','Hermes acceptance'); git(repo,'config','user.email','acceptance@example.invalid')
    git(repo,'remote','add','origin',str(remote))
    (repo/'lobby.py').write_text('def nickname(value):\n    return value.strip()\n\ndef claim(players, name):\n    raise NotImplementedError\n')
    baseline='import unittest\nfrom lobby import nickname\nclass Existing(unittest.TestCase):\n    def test_trim(self): self.assertEqual(nickname(" A "), "A")\n'
    (repo/'test_existing.py').write_text(baseline)
    git(repo,'add','.'); git(repo,'commit','-m','fixture baseline'); git(repo,'push','-u','origin','release/fixture')
    base=git(repo,'rev-parse','HEAD')
    author=root/'author'; parallel=root/'parallel'; reviewer=root/'reviewer'
    git(repo,'worktree','add','-b','feat/capacity',str(author),'origin/release/fixture')
    git(repo,'worktree','add','-b','feat/docs',str(parallel),'origin/release/fixture')
    (author/'test_capacity.py').write_text('import unittest\nfrom lobby import claim\nclass Capacity(unittest.TestCase):\n    def test_limit(self):\n        players=[]\n        self.assertTrue(claim(players,"A"))\n        self.assertTrue(claim(players,"B"))\n        self.assertFalse(claim(players,"C"))\n        self.assertEqual(players,["A","B"])\n')
    red=run(author,'python3','-m','unittest','discover','-v',ok=False)
    assert red.returncode!=0 and 'NotImplementedError' in red.stderr
    (author/'lobby.py').write_text('def nickname(value):\n    return value.strip()\n\ndef claim(players, name):\n    if len(players) >= 2:\n        return False\n    players.append(name)\n    return True\n')
    green=run(author,'python3','-m','unittest','discover','-v')
    assert (author/'test_existing.py').read_text()==baseline
    git(author,'add','.'); git(author,'commit','-m','capacity Red then Green')
    (parallel/'README.md').write_text('Parallel independent artifact.\n')
    assert not (parallel/'test_capacity.py').exists(), 'workspaces are not isolated'
    git(parallel,'add','.'); git(parallel,'commit','-m','parallel docs')
    git(repo,'merge','--no-ff','feat/docs','-m','integrate docs'); git(repo,'push','origin','release/fixture')
    git(author,'fetch','origin')
    stale=run(author,'git','merge-base','--is-ancestor','origin/release/fixture','HEAD',ok=False)
    assert stale.returncode==1
    git(author,'merge','--no-edit','origin/release/fixture')
    git(author,'merge-base','--is-ancestor','origin/release/fixture','HEAD')
    head=git(author,'rev-parse','HEAD')
    git(repo,'worktree','add','--detach',str(reviewer),head)
    run(reviewer,'python3','-m','unittest','discover','-v')
    assert git(reviewer,'status','--porcelain')==''
    assert (reviewer/'test_existing.py').read_text()==baseline
    guard=Path(__file__).resolve().parents[1]/'planning-publication-worktree/scripts/ci/test-integrity-guard.sh'
    assert guard.exists(), 'reviewed baseline guard required'
    run(author,'bash',str(guard),base,head)
    # Deliberate malicious weakening in the disposable fixture only.
    (author/'test_existing.py').write_text(baseline.replace('def test_trim', '@unittest.skip("bypass")\n    def test_trim'))
    git(author,'add','test_existing.py'); git(author,'commit','-m','negative probe: weaken old test')
    weak=git(author,'rev-parse','HEAD')
    rejection=run(author,'bash',str(guard),head,weak,ok=False)
    assert rejection.returncode!=0, 'existing test weakening was not rejected'
    assert git(reviewer,'rev-parse','HEAD')==head and git(reviewer,'status','--porcelain')==''
    print(json.dumps(dict(passed=True,scope='local_git_worktree_only',red_exit=red.returncode,
        green_exit=green.returncode,isolated_parallel_worktrees=True,stale_base_detected=True,
        updated_base=True,independent_checkout_sha=head,preexisting_tests_preserved=True,
        weakening_rejected=True,red_output_sha256=hashlib.sha256(red.stderr.encode()).hexdigest(),
        green_output_sha256=hashlib.sha256(green.stderr.encode()).hexdigest(),
        real_agent_pr_ci_validation=False,product_released=False),indent=2))
