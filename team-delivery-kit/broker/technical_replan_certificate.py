"""Qualify an actual CTO inspection, never generate its technical decision.

An extra test-revision level still requires the existing bounded depth gate,
fresh immutable Red and independent semantic review. This receipt changes no
test permission, baseline, worker result or delivery approval.
"""
import json
import re
import time
try:
    import native, handoff_runtime, handoffs
except ImportError:
    from broker import native, handoff_runtime, handoffs


def qualify(route,data,task,decision,reads):
    failure=data.get('validation_failure') or {}
    phase=data.get('phase_evidence') or {}
    source=data.get('source_task')
    files=set(route.get('test_first_files') or [])
    diagnostics=failure.get('diagnostic_read_files') or []
    if (not files or not isinstance(diagnostics,list)
            or any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_./-]+',p)
                   or p.startswith('/') or '..' in p.split('/') for p in [*files,*diagnostics])):
        raise ValueError('controller-selected relative source paths required')
    paths=sorted('/evidence/candidate/'+p for p in files|set(diagnostics))
    if (not route.get('test_first') or route['cto']==route['author']
            or data.get('target')!=route['cto'] or task.get('agent_id')!=route['cto']
            or task.get('status')!='completed' or task.get('id')==source
            or task.get('id')!=data.get('recipient_task')
            or task.get('wakeup_id')!=data.get('wakeup_id')
            or task.get('issue_id')!=route['issue_id']
            or decision.get('action')!='request_test_revision' or decision.get('optional_files')!=[]
            or not isinstance(decision.get('reason'),str) or not 1<=len(decision['reason'])<=1200
            or failure.get('category')!='executed_test_failure' or failure.get('phase')!='frozen_green'
            or failure.get('source_task')!=source or failure.get('exit_code')!=1
            or type(failure.get('tests_executed')) is not int or failure['tests_executed']<=0
            or not failure.get('failures') or not re.fullmatch(r'[a-f0-9]{64}',failure.get('output_sha256',''))
            or phase.get('phase')!='implementation' or phase.get('independent_test_review')!='approved'
            or not re.fullmatch(r'[a-f0-9]{64}',phase.get('red_manifest',''))
            or set(phase.get('frozen_test_hashes',{}))!=files
            or any(not re.fullmatch(r'[a-f0-9]{64}',v) for v in phase['frozen_test_hashes'].values())
            or any(p not in reads or type(reads[p].get('lines')) is not int or reads[p]['lines']<=0
                   or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)):
        raise ValueError('exact complete independent CTO frozen-Green replan required')
    return dict(version='complete-source-replan-v1',issue_id=route['issue_id'],source_task=source,
        decision_task=task['id'],output_sha256=failure['output_sha256'],baseline_edits_allowed=False,
        read_contract='complete-lines-v2',required_read_paths=paths,read_evidence={p:reads[p] for p in paths},
        red_manifest=phase['red_manifest'],delivery_approval=False,
        operation='qualified_frozen_green_cto_replan_v1')


def reconcile(b,source):
    """Internal maintenance: certify the SAME accepted decision, not replay it."""
    with b.LOCK,b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle reconciliation required')
        row=handoffs.load(con,source)
        if not row or row['stage']!='test_revision_required':raise ValueError('pending test revision required')
        latest=con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(row['issue_id'],)).fetchone()
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
        if route.get('enabled') or latest[0]!=source:raise ValueError('current paused route required')
        data=json.loads(row['data']);proposal=data.get('test_revision_proposal') or {}
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,row['issue_id'])
        if any(r.get('status') in ('queued','dispatched','running') for r in runs):raise ValueError('idle native replan required')
        task=native.task_record(settings,proposal.get('decision_task'),route['cto'])
        effects=handoff_runtime.Effects(b,settings)
        decision=effects.decision(task)
        if decision!=data.get('decision'):raise ValueError('accepted native decision drift')
        certificate=qualify(route,data,task,decision,effects.read_evidence(task))
        if (proposal.get('source_task')!=source or proposal.get('output_sha256')!=certificate['output_sha256']
                or proposal.get('reason')!=decision['reason']
                or set(proposal.get('new_test_files',[]))!=set(route['test_first_files'])):
            raise ValueError('proposal lineage drift')
        previous=data.get('technical_replan_certificate')
        if previous and previous!=certificate:raise ValueError('certificate cannot be replaced')
        if not previous:
            data['technical_replan_certificate']=certificate
            data['certificate_reconciliation']=dict(operation='same_cto_decision_evidence_reconciliation_v1',
                model_calls=0,author_restarted=False,delivery_approval=False,at=time.time())
            handoffs.save(con,source,row['issue_id'],row['stage'],row['owner'],data,time.time())
        return dict(qualified=True,decision_task=task['id'],model_calls=0,delivery_approval=False)
