"""Fixed CI on real local Git/Docker; no GitHub writes, runner or model.

Pass/reuse a proposal, validate its integrated SHA, reject assertion failures,
skips and changes to pre-existing tests. Never claims product delivery.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.effects import EffectBlocked,write_json
from fabriquinha.executor import Runner,docker
from fabriquinha.publication import LocalCI,Repository


def qualify(root,image):
    if root.exists():raise ValueError('fresh private CI root required')
    root.mkdir(mode=0o700,parents=True)
    project=Project.parse(dict(version=1,namespace='delivery-kit-hermes-ci',
        repository='https://github.com/example/ci-qualification',branch='release/ci',validation_image=image,
        tests_dir='tests',reviewers={'author':'reviewer'},qualification=True))
    write_json(root/'project.json',dict(version=1,**{name:(dict(value) if name=='reviewers' else value)
        for name,value in project.__dict__.items() if value is not None}))
    remote=root/'remote.git';remote.mkdir();seed=root/'seed'
    shutil.copytree(ROOT/'tests/fixtures/delivery/base',seed)
    def git(path,*args):
        return subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(path),*args],
            check=True,capture_output=True,text=True,timeout=30).stdout.strip()
    git(remote,'init','--bare','--initial-branch=main');git(seed,'init','--initial-branch=main');git(seed,'add','.')
    git(seed,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','commit','-m','Passing CI infrastructure fixture')
    git(seed,'remote','add','origin',str(remote));git(seed,'push','origin','HEAD:refs/heads/'+project.branch)
    store=Store(root/'private');repo=Repository(project,store,remote=remote);runner=Runner(project,store)
    ci=LocalCI(project,store,repo,runner);base=repo.base()
    def candidate(name,base):
        path=root/name;store.checkout(repo.snapshot(base),path);return path
    def propose(name,path,base):
        head=repo.propose(store.capture(path),base,'ci/'+name,'fixture');repo.push('ci/'+name,head);return head
    def job_count():return len(list((store.root/'jobs').glob('*/result.json')))
    work=candidate('passing',base);(work/'README.md').write_text('CI mechanism fixture; no feature implementation.\n')
    head=propose('passing',work,base)
    passed=ci.validate(head,base,stage='proposal')
    assert store.receipt(passed)['payload']['conclusion']=='success' and job_count()==2
    assert ci.validate(head,base,stage='proposal')==passed and job_count()==2
    try:ci.validate(head,base,stage='integrated')
    except EffectBlocked:pass
    else:raise AssertionError('unintegrated SHA passed integrated CI')
    assert job_count()==2
    repo.push(project.branch,head)
    integrated=ci.validate(head,base,stage='integrated')
    assert store.receipt(integrated)['payload']['conclusion']=='success' and job_count()==3
    work=candidate('failure',head)
    (work/'tests/test_new.py').write_text('import unittest\nclass New(unittest.TestCase):\n def test_failure(self): self.assertEqual(1,2)\n')
    failing=propose('failure',work,head);result=ci.validate(failing,head,stage='proposal')
    assert store.receipt(result)['payload']['conclusion']=='failure' and job_count()==5
    work=candidate('skipped',head)
    (work/'tests/test_new.py').write_text('import unittest\nclass New(unittest.TestCase):\n @unittest.skip("fixture")\n def test_skipped(self): self.assertEqual(1,2)\n')
    skipped=propose('skipped',work,head)
    try:ci.validate(skipped,head,stage='proposal')
    except ValueError as error:assert 'without errors or skips' in str(error)
    else:raise AssertionError('skipped test granted CI approval')
    assert job_count()==6
    work=candidate('weakened',head)
    (work/'tests/test_health.py').write_text('import unittest\n')
    weakened=propose('weakened',work,head)
    try:ci.validate(weakened,head,stage='proposal')
    except ValueError as error:assert 'protected baseline changed' in str(error)
    else:raise AssertionError('removed assertions granted CI approval')
    assert job_count()==6
    work=candidate('reduced-discovery',head)
    (work/'tests/test_aaa_discovery.py').write_text('import unittest\noriginal=unittest.TestLoader.getTestCaseNames\n'
        'def names(self,case):\n return [] if case.__module__=="test_health" else original(self,case)\n'
        'unittest.TestLoader.getTestCaseNames=names\nclass New(unittest.TestCase):\n def test_only_new(self): self.assertTrue(True)\n')
    reduced=propose('reduced-discovery',work,head)
    try:ci.validate(reduced,head,stage='proposal')
    except ValueError as error:assert 'omitted pre-existing test cases' in str(error)
    else:raise AssertionError('reduced test discovery granted CI approval')
    assert job_count()==7
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
    result=dict(passed=True,real_local_git=True,real_docker_jobs=7,proposal_job_reused=True,
        integrated_sha_checked=True,assertion_failure_rejected=True,skip_rejected=True,
        weakened_existing_test_rejected_before_execution=True,reduced_discovery_rejected=True,baseline_cases_preserved=True,
        all_owned_jobs_retired=True,
        github_status_published=False,actions_runner_registered=False,model_calls=0,delivery_approval=False)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--image',required=True);args=parser.parse_args()
    try:qualify(args.root.resolve(),args.image)
    except BaseException as error:
        write_json(args.root/'failure.json',dict(category=type(error).__name__,delivery_approval=False));raise
