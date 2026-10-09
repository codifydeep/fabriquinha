"""Independent technical plans for failed work; not implementation permission.

Caller must verify the durable failed-execution receipt and native identities.
These proposals retain the frozen tests and existing attempt history. A reviewed
plan requires a separate bounded execution adapter before any author dispatch.
"""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def paths(route,data):
    failure=data['validation_failure']
    files=set(route.get('test_first_files',[]))|set(failure.get('diagnostic_read_files',[]))|set(data.get('author_edit_files',[]))
    if not files or len(files)>32:raise ValueError('split failed-candidate inspection scope before dispatch')
    return sorted('/evidence/candidate/'+p for p in files)


def prepare(route,data,task,decision,reads):
    proof=data.get('failed_execution_diagnostic') or {}
    if (data.get('target')!=route['cto'] or task.get('agent_id')!=route['cto']
            or task.get('status')!='completed' or task.get('issue_id')!=route['issue_id']
            or task.get('wakeup_id')!=data.get('wakeup_id')
            or decision.get('action')!='request_correction' or decision.get('optional_files')!=[]
            or not data.get('author_edit_files') or data.get('failed_candidate_plan')
            or proof.get('status')!='diagnostic_only_not_approved'
            or proof.get('failure')!=data.get('validation_failure')
            or data.get('source_status')!='failed'
            or len({route['author'],route['cto'],route['techlead']})!=3
            or not set(paths(route,data))<=set(reads)):
        raise ValueError('exact independent CTO proposal and observed candidate reads required')
    return dict(operation='failed_candidate_plan_v1',source_task=data['source_task'],
        issue_id=route['issue_id'],contract_sha256=route['contract_sha256'],
        diagnostic_sha256=digest(proof),cto_task=task['id'],cto=route['cto'],
        author=route['author'],reviewer=route['techlead'],proposal=decision,
        read_paths=paths(route,data),edit_files=data['author_edit_files'],
        author_execution_authorized=False,tests_may_change=False,delivery_approval=False)


def instruction(route,data):
    plan=data['failed_candidate_plan']
    if (plan['diagnostic_sha256']!=digest(data['failed_execution_diagnostic'])
            or plan['contract_sha256']!=route['contract_sha256'] or plan['reviewer']!=route['techlead']):
        raise ValueError('failed candidate plan identity drift')
    note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        'INDEPENDENT TECH LEAD REVIEW OF FAILED-CANDIDATE REPLAN.\n'
        'Read the exact immutable candidate, frozen tests and installed edit scope. '
        'CTO proposal is not authority: '+plan['proposal']['reason']+'\n'
        'Return request_correction only for a source-supported actionable product fix '
        'within the declared scope; otherwise escalate_cto with a concrete blocker or '
        'experiment. You do not implement, approve delivery, change tests, replay Red, '
        'or reset attempts. A positive review records a plan, not an author grant. '
        'Return ONLY JSON action(request_correction|escalate_cto), reason(one actionable '
        'sentence <=300 chars, hard limit1200), optional_files=[].\n'
        'Frozen failure: DELIVERY_BOUND_FAILURE_CONTEXT_V1:'+data['source_task']+':'+digest(data['validation_failure'])+'\n'
        'Plan SHA256: '+digest(plan)+'\n')
    for path in plan['read_paths']:note+='DELIVERY_REVIEW_READ_PATH:'+path+'\n'
    if len(note)>3800:raise ValueError('split independent failed-candidate plan context before dispatch')
    return note


def review(route,data,task,decision,reads):
    plan=data['failed_candidate_plan']
    instruction(route,data)
    if (data.get('target')!=route['techlead'] or task.get('agent_id')!=route['techlead']
            or task.get('status')!='completed' or task.get('issue_id')!=route['issue_id']
            or task.get('wakeup_id')!=data.get('wakeup_id') or task['id']==plan['cto_task']
            or decision.get('action')!='request_correction' or decision.get('optional_files')!=[]
            or not set(plan['read_paths'])<=set(reads)):
        raise ValueError('independent source-bound plan review and reads required')
    return dict(operation='failed_candidate_plan_review_v1',plan_sha256=digest(plan),
        diagnostic_sha256=plan['diagnostic_sha256'],cto_task=plan['cto_task'],
        techlead_task=task['id'],decision=decision,contract_sha256=route['contract_sha256'],
        author_execution_authorized=False,tests_may_change=False,delivery_approval=False,
        retry_budget_reset=False,status='reviewed_replan_requires_bounded_execution_adapter')
