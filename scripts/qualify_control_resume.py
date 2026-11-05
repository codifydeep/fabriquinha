"""Offline native Kanban handoff qualification with programmed validator reports."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'src'),str(BASE/'tests')]
from qualify_hermes_s1 import prepare
from fabriquinha.artifacts import Store
from fabriquinha.board import Board,Run
from fabriquinha.config import Project
from fabriquinha.control_submission import seal,advance,previous_submission,wait_payload,NextControl
from fabriquinha.kanban_lane import native
from fabriquinha.quality import Quality,product_mutations
from fixtures.control_evidence import frozen_evidence
from test_delivery_core import configuration


def qualify(root,upstream):
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    prepare(root,upstream)
    kb,api,_=native()
    from hermes_cli.profiles import create_profile
    for name in ('backend','lead','cto'):create_profile(name,no_skills=True)
    project=Project.parse({**configuration(),'reviewers':{'backend':['lead','cto']}})
    store=Store(root/'private'); work=root/'work';work.mkdir()
    (work/'app.py').write_text('value=1'); snapshot=store.capture(work)
    freeze=frozen_evidence(store,project,Run('tests',1,'lead','tests',False,'lead','v','test-contract'),snapshot,snapshot,'cto')
    board=Board(project)
    with api.connect_closing() as conn:
        task=kb.create_task(conn,title='Control proof',assignee='backend',workspace_kind='dir',workspace_path=str(work),
                            body=json.dumps(dict(version=1,kind='implementation',release='v',inputs={'tests':freeze})))
    def claim():
        with api.connect_closing() as conn:row=kb.claim_task(conn,task)
        return board.current(task,row.current_run_id)
    calls=[]
    def execute(run,tree,phase):
        calls.append((tree,phase))
        failures=[] if phase=='green' else [dict(case='new',assertion=True,frames=[dict(file='tests/test_new.py',function='test_new')])]
        return store.record('suite_job',run.binding(),dict(exit_code=int(bool(failures)),report=dict(version=1,tests_run=2,
            cases=['existing','new'],failures=failures,errors=[],skips=[],expected_failures=[],unexpected_successes=[]),
            identity=dict(binding=run.binding(),project=project.fingerprint(),snapshot=tree,phase=phase,image=project.validation_image,
                          control_submission=getattr(runner,'control_submission',None)),sandbox=dict(network='none',snapshot='readonly',user='65534:65534')))
    runner=SimpleNamespace(run=execute)
    quality=Quality(project,store,runner,board)
    origin=claim();green=quality.green(origin,freeze,snapshot)
    mutants=product_mutations(quality,snapshot,[{'app.py':'value=2'},{'app.py':'value=3'}])
    plan=seal(quality,origin,green,mutants)
    live=origin
    for index in range(2):
        with api.connect_closing() as conn:
            key=wait_payload(store,project,live,plan)
            assert kb.schedule_task(conn,task,reason=json.dumps({'control_wait':key}),expected_run_id=live.number)
            assert kb.unblock_task(conn,task)
        live=claim()
        with api.connect_closing() as conn:assert previous_submission(conn,store,live)==plan
        try:result=advance(quality,live,plan)
        except NextControl:assert index==0
    assert result['evidence']['green']==green and calls==[(snapshot,'green')]+[(m,'control') for m in mutants]
    with api.connect_closing() as conn:review=kb.claim_review_task(conn,task)
    independent=board.current(task,review.current_run_id)
    assert independent.actor=='cto' and independent.reviewing
    assert board.input(independent,'controls',review_handoff=True)==result['evidence']['controls']
    print(json.dumps(dict(passed=True,native_claims=True,model_calls=0,programmed_reports=True,independent_review_started=True)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args()
    qualify(args.root.resolve(),args.upstream.resolve())
