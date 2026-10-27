"""Offline real-Docker qualification of one immutable Python acceptance suite.

Scripted fixtures only: no model, GitHub mutation or product delivery approval.
All targets are owned disposable containers; existing deployments are untouched.
"""
import argparse
from contextlib import contextmanager
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.browser import acceptance_manifest,expected_checks
from fabriquinha.config import Project
from fabriquinha.effects import Pending,write_json
from fabriquinha.executor import Runner,docker,grouping,seal_validation
from fabriquinha.quality import CONTROL_CONTRACT,suite_report,preview_evidence


def qualify(root,image,browser_image,qa_subnet,*,resume=False):
    root=Path(root).absolute()
    if root.exists() and not resume:raise ValueError('fresh private root or explicit resume required')
    if root.is_relative_to(ROOT) and subprocess.run(['git','-C',str(ROOT),'check-ignore','--quiet',str(root)],capture_output=True).returncode:
        raise ValueError('qualification root must be private and Git ignored')
    root.mkdir(mode=0o700,parents=True,exist_ok=resume)
    namespace='delivery-kit-acceptance-'+hashlib.sha256(str(root).encode()).hexdigest()[:8]
    project=Project.parse(dict(version=1,namespace=namespace,repository='https://github.com/example/acceptance-proof',
        branch='release/proof',validation_image=image,browser_image=browser_image,browser_tdd=True,
        tests_dir='tests',reviewers={'author':'reviewer','reviewer':'author'},qualification=True,
        coordination_roles={'product':'author','lead':'reviewer'},delivery_roles={'tests':'reviewer','integration':'author'}))
    store=Store(root/'private');bundle=seal_validation(store)
    installation=dict(project=project.fingerprint(),control_contract=CONTROL_CONTRACT,validation_bundle=bundle,browser_contract=2)
    if (root/'installation.json').exists():
        if json.loads((root/'installation.json').read_bytes())!=installation:raise ValueError('resume source or project changed')
    else:write_json(root/'installation.json',installation)
    runner=Runner(project,store);work=root/'work';(work/'tests').mkdir(parents=True,exist_ok=resume)
    app=(ROOT/'tests/fixtures/acceptance_app.py').read_text()
    tests=(ROOT/'tests/fixtures/acceptance_probe.py').read_text()
    (work/'app.py').write_text(app)
    (work/'tests/test_unit.py').write_text('import unittest\nclass Unit(unittest.TestCase):\n def test_auxiliary(self):self.assertEqual(2+2,4)\n')
    (work/'tests/acceptance_probe.py').write_text(tests)
    criteria={name:dict(cases=['acceptance_probe.Probe.'+case],gates=[]) for name,case in
        [('SESSIONS','test_independent_sessions_and_bounded_update'),('ISOLATION','test_isolation')]}
    criteria['REGRESSION']=dict(cases=[],gates=['regression'])
    write_json(work/'tests/acceptance.probe.json',dict(version=2,criteria=criteria))
    good=store.capture(work)
    (work/'app.py').write_text(app.replace('BROKEN=False','BROKEN=True'));broken=store.capture(work)
    (work/'app.py').write_text(app.replace('LAG=0','LAG=3400'));late=store.capture(work)
    frozen={p:v for p,v in store.manifest(good).items() if p.startswith('tests/')}
    for snapshot in (broken,late):assert frozen=={p:v for p,v in store.manifest(snapshot).items() if p.startswith('tests/')}
    jobs=[];run=Run('proof',1,'author','implementation',False,'author','proof','contract')
    def call(operation,kind,*args):
        deadline=time.monotonic()+project.timeout_seconds+20
        while True:
            try:key=operation(*args);break
            except Pending:
                if time.monotonic()>deadline:raise
                time.sleep(0.1)
        jobs.append(key);return store.receipt(key,kind=kind)['payload']
    red=call(runner.run,'suite_job',run,broken,'red')
    assert suite_report(red)['failures'] and not red['report']['errors'],red
    green=call(runner.run,'suite_job',run,good,'green')
    preview_evidence(project,store,green,good,'green')
    assert not suite_report(green)['failures'] and green['report']['tests_run']==3,green
    delayed=call(runner.run,'suite_job',run,late,'control')
    assert suite_report(delayed)['failures'] and not delayed['report']['errors'],delayed
    # Dynamic selection and skips cannot produce accepted full inventory.
    (work/'app.py').write_text(app)
    (work/'tests/acceptance_probe.py').write_text(tests+'\ndef load_tests(loader,tests,pattern):\n import unittest\n return unittest.TestSuite()\n')
    partial=store.capture(work)
    partial_report=call(runner.run,'suite_job',run,partial,'green')
    try:suite_report(partial_report)
    except ValueError:pass
    else:raise AssertionError('partial acceptance inventory accepted')
    (work/'tests/acceptance_probe.py').write_text(tests.replace('    def test_isolation(self):','    @__import__("unittest").skip("forbidden")\n    def test_isolation(self):'))
    skipped=call(runner.run,'suite_job',run,store.capture(work),'green')
    try:suite_report(skipped)
    except ValueError:pass
    else:raise AssertionError('skipped acceptance accepted')

    network=namespace+'-homologation_qa';network_id=None;source='a'*40
    @contextmanager
    def target(snapshot):
        name=namespace+'-target-'+snapshot[:12];container=None
        args=['create','--name',name,*grouping('acceptance-target',namespace),
            '--label','fabriquinha.proof='+project.fingerprint(),'--network',network,'--network-alias','web',
            '--read-only','--user','10000:10000','--cap-drop','ALL','--security-opt','no-new-privileges:true',
            '--memory','128m','--cpus','1','--pids-limit','64','--tmpfs','/tmp:rw,nosuid,size=16m',
            '--env','FABRIQUINHA_SOURCE_SHA='+source,
            '--mount',f'type=bind,src={store.tree(snapshot)/"app.py"},dst=/app.py,readonly',browser_image,'-B','/app.py','8080']
        write_json(root/(snapshot+'-intent.json'),dict(name=name,project=project.fingerprint(),snapshot=snapshot))
        try:
            container=docker(*args).strip();docker('start',container)
            for attempt in range(30):
                try:
                    docker('exec',container,'python','-c','import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=1)')
                    break
                except subprocess.CalledProcessError:
                    if attempt==29:raise
                    time.sleep(.1)
            yield
        finally:
            if container:
                info=json.loads(docker('inspect',container))[0]
                if (info['Id']!=container or info['Config']['Labels'].get('fabriquinha.proof')!=project.fingerprint()
                        or info['Config']['Labels'].get('com.docker.compose.project')!=namespace+'-tests'):
                    raise ValueError('target ownership changed; retain container')
                write_json(root/(snapshot+'-target.json'),dict(container=container,image=info['Image'],logs=docker('logs',container)))
                docker('stop','--time','3',container)
                info=json.loads(docker('inspect',container))[0]
                if info['State']['Running']:raise ValueError('target still running; retain container')
                docker('rm',container)
    try:
        subnet=ipaddress.IPv4Network(qa_subnet,strict=True)
        if subnet.prefixlen!=28 or not any(subnet.subnet_of(ipaddress.IPv4Network(pool)) for pool in
                ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):raise ValueError('private aligned /28 required')
        ids=docker('network','ls','-q').split()
        for info in json.loads(docker('network','inspect',*ids)) if ids else []:
            for config in (info.get('IPAM',{}).get('Config') or []):
                used=config.get('Subnet')
                if used and ipaddress.ip_network(used).version==4 and subnet.overlaps(ipaddress.ip_network(used)):
                    raise ValueError('qualification subnet overlaps existing network; preserve it')
        network_id=docker('network','create','--internal','--subnet',str(subnet),'--label','com.docker.compose.project='+namespace+'-homologation',
            '--label','fabriquinha.proof='+project.fingerprint(),network).strip()
        for snapshot,passed in ((good,True),(late,False)):
            with target(snapshot):
                observed=call(runner.browser,'browser_job',run,snapshot,source)
                report=observed['report']
                assert (report['status']=='passed')==passed and not observed['infrastructure_error'],observed
                if passed:
                    assert report['checks']==expected_checks(store.tree(good)/'tests',2)
                    assert report['cases']==acceptance_manifest(store.tree(good)/'tests')['cases']
                else:assert report['failure_kind']=='behavior'
    finally:
        if network_id:
            info=json.loads(docker('network','inspect',network_id))[0]
            if info['Containers'] or info['Labels'].get('fabriquinha.proof')!=project.fingerprint():
                raise ValueError('network still used or ownership changed; retain it')
            docker('network','rm',network_id)
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+namespace+'-tests').strip()
    result=dict(passed=True,browser_contract=2,jobs=len(jobs),job_receipts=jobs,
        same_frozen_acceptance_preview_and_deployed=True,multiple_isolated_contexts=True,
        third_claim_rejected=True,over_three_second_mutation_rejected_on_both_targets=True,
        readonly_no_credentials_no_socket_no_external_network=True,partial_and_skip_rejected=True,
        old_test_bytes_preserved=True,containers_retired=True,model_calls=0,github_mutations=0,delivery_approval=False)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--image',required=True);parser.add_argument('--browser-image',required=True)
    parser.add_argument('--qa-subnet',required=True);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    try:qualify(args.root,args.image,args.browser_image,args.qa_subnet,resume=args.resume)
    except BaseException as error:
        if args.root.exists():write_json(args.root/'failure.json',dict(category=type(error).__name__,detail=str(error)[:2000]))
        raise
