"""Real isolated suite evidence for reassessment; programmed roles, no LLM.

Complements the native lifecycle proof; does not qualify autonomous judgment.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import Pending,write_json
from fabriquinha.executor import Runner
from fabriquinha.quality import Quality,product_mutations
from fabriquinha.repairs import review_reassessment,record_review_admission,review_admission
from fabriquinha.recovery import Diagnostic


def qualify(root,image):
    if root.exists():raise ValueError('fresh isolated root required')
    root.mkdir(parents=True,mode=0o700)
    project=Project.parse(dict(version=1,namespace='delivery-kit-review-jobs',repository='https://github.com/example/qualification',
        branch='release/proof',validation_image=image,tests_dir='tests',reviewers={'author':'lead','lead':'cto'},
        technical_roles={'lead':'lead','cto':'cto'},qualification=True))
    store=Store(root/'private');work=root/'work';(work/'tests').mkdir(parents=True)
    (work/'app.py').write_text('VALUE = 1\n')
    (work/'tests/test_baseline.py').write_text('import unittest\nfrom app import VALUE\nclass Baseline(unittest.TestCase):\n def test_type(self): self.assertIsInstance(VALUE,int)\n')
    baseline=store.capture(work)
    (work/'tests/test_new.py').write_text('import unittest\nfrom app import VALUE\nclass New(unittest.TestCase):\n def test_value(self): self.assertEqual(VALUE,2)\n')
    snapshot=store.capture(work)
    board=SimpleNamespace(ensure=lambda run:None,input=lambda *a,**kw:baseline)
    quality=Quality(project,store,Runner(project,store),board)
    def wait(call):
        deadline=time.monotonic()+120
        while True:
            try:return call()
            except Pending:
                if time.monotonic()>=deadline:raise
                time.sleep(.2)
    author=Run('source',1,'author','tests',False,'author','release','source-contract')
    red=wait(lambda:quality.red(author,baseline,snapshot))
    source=Run('source',2,'lead','tests',True,'author','release','source-contract')
    incident=store.record('incident',source.binding(),dict(project=project.fingerprint(),source_state='triage',source='source',source_run=2,
        resume_allowed=False,controller_effects=[],snapshot=snapshot))
    prior=Run('held-diagnosis',3,'cto','diagnostic',False,'cto','release','hold-contract')
    job,report=wait(lambda:quality.observe(prior,snapshot,'diagnostic'))
    experiment=quality.record(prior,'diagnostic_experiment',dict(incident=incident,snapshot=snapshot,job=job,report=report))
    hold=quality.record(prior,'diagnostic_decision',dict(incident=incident,action='hold',experiment=experiment,delivery_approval=False))
    probe=Run('probe',4,'cto','diagnostic',False,'cto','release','probe-contract')
    board.input=lambda run,key,**kwargs:{'incident':incident,'held_review':hold}.get(key,baseline)
    diagnostic=Diagnostic(SimpleNamespace(run=probe),quality)
    # Only the native task lookup is programmed here. Both observations and the
    # admission gate are real; this fixture must not claim native dispatch.
    task=SimpleNamespace(body=json.dumps(dict(review_experiment=dict(handoff=red))))
    api=(SimpleNamespace(get_task=lambda *args:task),SimpleNamespace(connect_closing=lambda:nullcontext(None)),None)
    repeated_job,repeated_report=wait(lambda:quality.observe(probe,snapshot,'diagnostic'))
    diagnostic.experiment=quality.record(probe,'diagnostic_experiment',dict(incident=incident,
        source_snapshot=snapshot,snapshot=snapshot,job=repeated_job,report=repeated_report))
    with patch('fabriquinha.recovery.native',return_value=api):
        refused=diagnostic.review_probe_feedback()['review_reassessment']
    assert refused['eligible'] is False and refused['delivery_approval'] is False
    assert 'Do not repeat' in refused['next_action']
    candidate=product_mutations(quality,snapshot,[{'app.py':'VALUE = 2\n'}])[0]
    next_job,next_report=wait(lambda:quality.observe(probe,candidate,'diagnostic'))
    observation=quality.record(probe,'diagnostic_experiment',dict(incident=incident,source_snapshot=snapshot,snapshot=candidate,job=next_job,report=next_report))
    diagnostic.experiment=observation
    with patch('fabriquinha.recovery.native',return_value=api):
        feedback=diagnostic.review_probe_feedback()['review_reassessment']
    assert feedback['eligible'] is True and feedback['delivery_approval'] is False
    admitted=review_reassessment(project,store,incident,hold,red,observation)
    diagnosis=quality.record(probe,'diagnostic_decision',dict(incident=incident,action='hold',experiment=observation,delivery_approval=False))
    binding=dict(actor='controller',task='anchor',release='release',contract='anchor-contract')
    graph=dict(project=project.fingerprint(),items=[])
    admission=record_review_admission(project,store,binding,graph,incident,hold,red,observation,diagnosis)
    assert record_review_admission(project,store,binding,graph,incident,hold,red,observation,diagnosis)==admission
    assert review_admission(project,store,admission)['payload']['delivery_approval'] is False
    assert report['failures'] and not next_report['failures']
    assert admitted['snapshot']==snapshot and admitted['delivery_approval'] is False
    assert (work/'app.py').read_text()=='VALUE = 1\n'
    assert (store.tree(snapshot)/'app.py').read_text()=='VALUE = 1\n'
    assert quality.tests(snapshot)==quality.tests(candidate)
    records=[json.loads(p.read_text()) for p in (store.root/'receipts').glob('*.json')]
    jobs=[r for r in records if r['kind']=='suite_job']
    assert len(jobs)==5
    assert all(r['payload']['sandbox']==dict(network='none',snapshot='readonly',user='65534:65534') for r in jobs)
    assert not any(r['kind'] in ('green','tests_frozen','delivery_review','release_acceptance') for r in records)
    result=dict(passed=True,real_suite_jobs=len(jobs),real_red=True,changed_diagnostic_evidence_admitted=True,
        author_snapshot_preserved=True,tests_exact=True,delivery_approval=False,model_calls=0,native_roles_programmed=True,
        repeated_observation_feedback=refused,changed_observation_feedback=feedback,
        red=red,incident=incident,hold=hold,observation=observation,controller_admission=admission)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--image',required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.root.resolve(),args.image),indent=2))
