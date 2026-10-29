"""Real Docker proof of scoped legacy-test repair; roles programmed, no model.

Not a native dispatch or autonomous-delivery qualification. Artifacts are private.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import Pending,write_json
from fabriquinha.executor import Runner
from fabriquinha.quality import Quality,product_mutations
from fabriquinha.technical_repair import validate_scope
from fabriquinha.repairs import reviewed
from fabriquinha.test_revision import implementation_seed

BASE='''LEGACY = True
FEATURE = 0
def value(tag):
    return 1 if tag == 'real' or LEGACY else 2
def feature():
    return FEATURE
'''
IMPLEMENTED=BASE.replace('LEGACY = True','LEGACY = False').replace('FEATURE = 0','FEATURE = 2')
OLD='''import unittest
from app import value
class Legacy(unittest.TestCase):
    def test_value(self):
        observed = value('legacy')
        self.assertEqual(observed, 1)
'''
NEW=OLD.replace("value('legacy')", "value('real')")
LEGACY='acceptance_old.Legacy.test_value'
FEATURE='acceptance_new.Feature.test_added'


def qualify(root,image):
    if root.exists():raise ValueError('fresh private root required')
    root.mkdir(parents=True,mode=0o700)
    project=Project.parse(dict(version=1,namespace='delivery-kit-test-repair-proof',repository='https://github.com/example/qualification',
        branch='release/proof',validation_image=image,tests_dir='tests',reviewers={'author':'lead','lead':'cto'},
        technical_roles={'lead':'lead','cto':'cto'},qualification=True))
    store=Store(root/'private');work=root/'work';(work/'tests').mkdir(parents=True)
    (work/'app.py').write_text(BASE)
    (work/'tests/test_driver.py').write_text("def load_tests(loader, tests, pattern):\n    return loader.discover('/workspace/tests', pattern='acceptance_*.py')\n")
    (work/'tests/acceptance_old.py').write_text(OLD);baseline=store.capture(work)
    (work/'tests/acceptance_new.py').write_text('import unittest\nfrom app import feature\nclass Feature(unittest.TestCase):\n    def test_added(self):\n        self.assertEqual(feature(), 2)\n')
    candidate=store.capture(work)
    inputs={};board=SimpleNamespace(ensure=lambda r:None,input=lambda r,k,**kw:inputs[k],repair_input=lambda r:inputs.get('repair'))
    q=Quality(project,store,Runner(project,store),board)
    def wait(call):
        until=time.monotonic()+180
        while True:
            try:return call()
            except Pending:
                if time.monotonic()>until:raise
                time.sleep(.2)
    author=Run('tests',1,'author','tests',False,'author','proof','tests-contract')
    red=wait(lambda:q.red(author,baseline,candidate));inputs['red']=red
    verdict=dict(decision='approve',reason='Programmed fixture review; not autonomous judgment.',findings=[])
    frozen=q.tests_review(replace(author,number=2,actor='lead',reviewing=True),red,verdict)
    (work/'app.py').write_text(IMPLEMENTED);implementation=store.capture(work)
    impl=Run('implementation',3,'author','implementation',False,'author','proof','impl-contract')
    incident=store.record('incident',impl.binding(),dict(project=project.fingerprint(),source=impl.task,source_run=impl.number,
        source_state='blocked',controller_effects=[],snapshot=implementation,resume_allowed=True))
    cto=Run('diagnosis',4,'cto','diagnostic',False,'cto','proof','diag-contract')
    job,report=wait(lambda:q.observe(cto,implementation,'diagnostic'))
    assert {f['case'] for f in report['failures']}=={LEGACY}
    experiment=q.record(cto,'diagnostic_experiment',dict(incident=incident,snapshot=implementation,job=job,report=report))
    scope=validate_scope(project,store,incident,cto.binding(),experiment,dict(tests=frozen,test_paths=['tests/acceptance_old.py'],cases=[LEGACY]))
    decision=q.record(cto,'diagnostic_decision',dict(incident=incident,action='repair_tests',experiment=experiment,test_repair=scope,delivery_approval=False))
    binding=dict(actor='controller',task='anchor',release='proof',contract='anchor-contract')
    graph=store.record('release_graph',binding,dict(project=project.fingerprint(),items=[]))
    admission=store.record('test_repair_admission',binding,dict(**scope,project=project.fingerprint(),repair_kind='fixture',
        incident=incident,source=impl.task,source_run=impl.number,source_contract=impl.contract,
        prior_graph=graph,current_diagnosis=decision,reviewed_diagnosis=decision,qa_paths=scope['test_paths']))
    authority=reviewed(project,store,admission);inputs['repair']=admission
    (work/'app.py').write_text(BASE);(work/'tests/acceptance_old.py').write_text(NEW);corrected=store.capture(work)
    successor=replace(author,task='corrected-tests',number=5,contract='corrected-contract')
    fresh=wait(lambda:q.red(successor,candidate,corrected));inputs['red']=fresh
    try:q.protect(baseline,corrected,allow_revision=True)
    except ValueError:pass
    else:raise AssertionError('CI accepted correction before independent freeze')
    freeze=q.tests_review(replace(successor,number=6,actor='lead',reviewing=True),fresh,verdict)
    plan=q.frozen_plan(store.receipt(freeze));assert set(plan['control_cases'])=={LEGACY,FEATURE}
    q.protect(baseline,corrected,allow_revision=True)
    seed=implementation_seed(project,store,q,authority,plan)
    inputs['tests']=freeze
    worker=replace(impl,task='corrected-implementation',number=7,contract='new-implementation')
    green=wait(lambda:q.green(worker,freeze,seed))
    mutants=product_mutations(q,seed,[{'app.py':IMPLEMENTED.replace("return 1 if tag == 'real' or LEGACY else 2",'return 3')},
                                     {'app.py':IMPLEMENTED.replace('FEATURE = 2','FEATURE = 0')}])
    controls=wait(lambda:q.controls(worker,green,mutants))
    assert set(store.receipt(controls)['payload']['coverage'])=={LEGACY,FEATURE}
    assert (store.tree(baseline)/'tests/acceptance_old.py').read_text()==OLD
    assert (store.tree(implementation)/'app.py').read_text()==IMPLEMENTED
    jobs=[store.receipt(p.stem) for p in (store.root/'receipts').glob('*.json') if store.receipt(p.stem)['kind']=='suite_job']
    assert all(j['payload']['sandbox']==dict(network='none',snapshot='readonly',user='65534:65534') for j in jobs)
    result=dict(passed=True,model_calls=0,roles_programmed=True,native_dispatch_qualified=False,delivery_approval=False,
        real_jobs=len(jobs),red=fresh,freeze=freeze,green=green,controls=controls,baseline_preserved=True,
        legacy_negative_control_required=True,admission=admission)
    write_json(root/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--image',required=True)
    args=p.parse_args();print(json.dumps(qualify(args.root.resolve(),args.image),indent=2))
