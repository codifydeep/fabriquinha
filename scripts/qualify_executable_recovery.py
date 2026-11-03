"""Isolated native executable CTO decision; programmed technical choices, no model.

Initial incident/decision context is a fixture, not evidence from production.
The proof must preserve current-experiment gates and native handoff identity.
"""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_delivery import create_trial
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json,Pending
from fabriquinha.kanban_lane import native
from fabriquinha.recovery import Recovery


def prepare_case(root,upstream,image):
    source,implementation=create_trial(root,upstream,image,namespace='delivery-kit-executable-recovery')
    settings=json.loads((root/'project.json').read_bytes())
    settings['technical_roles']={'lead':'flow-lead','cto':'flow-cto'}
    write_json(root/'project.json',settings)
    project=Project.parse(settings);store=Store(root/'private');board=Board(project)
    from hermes_cli.profiles import create_profile
    for name in project.technical_roles.values():
        create_profile(name,no_skills=True,description='Isolated programmed recovery proof')
    kb,kbc,_=native();recovery=Recovery(project,store,board)
    with kbc.connect_closing() as conn:
        task=kb.claim_task(conn,source);assert task
        original=board.current(source,task.current_run_id)
        assert kb.block_task(conn,source,reason='Programmed missing terminal operation',expected_run_id=original.number)
        recovery.discover(conn,kb.get_task(conn,source),lambda *a,**kw:None)
        diagnostics=[t for t in recovery.cards(conn) if json.loads(t.body or '{}').get('kind')=='diagnostic']
        assert len(diagnostics)==1
        incident=json.loads(diagnostics[0].body)['inputs']['incident']
    return SimpleNamespace(root=root,project=project,store=store,board=board,recovery=recovery,
                           source=source,implementation=implementation,incident=incident)


def qualify(root,upstream,image):
    import time
    from fabriquinha.hermes import Sandbox
    from fabriquinha.executor import Runner
    from fabriquinha.quality import Quality
    from fabriquinha.recovery import Diagnostic
    c=prepare_case(root,upstream,image);kb,kbc,_=native()
    quality=Quality(c.project,c.store,Runner(c.project,c.store),c.board)
    def activity(task_id):
        with kbc.connect_closing() as conn:
            task=kb.claim_task(conn,task_id);assert task
        run=c.board.current(task.id,task.current_run_id)
        return Diagnostic(Sandbox(c.project,c.store,c.board,run),quality)
    def validate(d):
        while True:
            try:return d.validate({'hypothesis':'Observe immutable baseline before author correction'})
            except Pending:time.sleep(.1)
    with kbc.connect_closing() as conn:
        lead=next(t for t in c.recovery.cards(conn) if json.loads(t.body or '{}').get('kind')=='diagnostic')
    d=activity(lead.id);prior=validate(d)
    decision=d.decide(dict(action='hold',reason='Current baseline does not test the approved new value',
        findings=[dict(evidence='experiment',detail='Baseline observation retained for CTO')]))
    # Explicit initial scenario fixture: no production hold is rewritten or authorized.
    body=json.loads(lead.body);body.update(stage='cto',escalated_from=lead.id,
        hold_resolution=dict(protocol='executable-decision-1',role='decide',diagnosis=decision['diagnosis'],
            objective='Choose bounded author correction with retained evidence'))
    with kbc.connect_closing() as conn:
        task_id=kb.create_task(conn,title='Executable CTO fixture',body=json.dumps(body),assignee='flow-cto',
            parents=[lead.id],workspace_kind='dir',workspace_path=lead.workspace_path,completion_contract='local-only')
    d=activity(task_id);d.report_page(dict(offset=0,experiment=prior['experiment']))
    args=dict(action='resume',reason='Author must add the missing value expectation',
        findings=[dict(evidence=prior['experiment'],detail='Retained baseline does not protect requested value')],
        ruling=dict(choice='Add behavior test',correction='Author adds value expectation then requests independent freeze',
            remaining='Red, independent review, Green and negative controls',blocker='none'))
    try:d.decide(args)
    except ValueError as e:assert 'real experiment' in str(e)
    else:raise AssertionError('history authorized resume')
    validate(d);result=d.decide(args)
    for _ in range(2):
        # Reconstruct controller and connection; persisted journal prevents duplicate resume.
        with kbc.connect_closing() as conn:
            Recovery(c.project,c.store,Board(c.project)).apply(conn,kb.get_task(conn,task_id))
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn,c.source).status=='ready'
        assert conn.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='unblocked'",(c.source,)).fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM task_comments WHERE task_id=? AND body LIKE 'DIAG %'",(c.source,)).fetchone()[0]==1
    proof=dict(executable_decision=True,historical_citation=True,current_experiment_required=True,
        native_author_resume_once=True,reconstructed_controller_idempotent=True,model_calls=0,
        delivery_approval=False,initial_context_programmed=True)
    write_json(root/'result.json',proof);return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True)
    args=parser.parse_args()
    print(json.dumps(qualify(args.root.resolve(),args.upstream.resolve(),args.image),indent=2))
