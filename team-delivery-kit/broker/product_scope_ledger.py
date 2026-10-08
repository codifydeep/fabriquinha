"""Controller-owned durable scope-plan ledger; never an edit permission API.

The runtime adapter must supply authenticated native task/read observations.
These functions do not fetch them or authorize dispatch. The author remains
blocked even after plan approval, until a separate installer qualifies a new
immutable contract and its unchanged frozen-test references.
"""
import json
try:
    from . import product_scope_revision as policy
except ImportError:
    import product_scope_revision as policy


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'))


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS product_scope_plans '
                '(plan_key TEXT PRIMARY KEY, data TEXT NOT NULL)')


def load(con,key):
    initialize(con)
    row=con.execute('SELECT data FROM product_scope_plans WHERE plan_key=?',(key,)).fetchone()
    if not row:raise ValueError('existing scope intent required')
    return json.loads(row[0])


def open_plan(con,original,context):
    if (not isinstance(context,dict) or set(context)!={'issue_id','source_task','author','cto','reviewer',
            'contract_sha256','snapshot_sha256','failure_output_sha256','eligible_code_sha256','frozen_test_sha256'}
            or not isinstance(context['eligible_code_sha256'],dict)
            or not 1<=len(context['eligible_code_sha256'])<=8):
        raise ValueError('bounded exact controller scope context required')
    # Validate all selectable paths against the original contract before saving intent.
    check=dict(operation='propose_product_scope_revision_v1',reason='Validate scope intent only.',
        write_files=sorted(context['eligible_code_sha256']),**{k:context[k] for k in
            ('issue_id','source_task','contract_sha256','snapshot_sha256','failure_output_sha256')})
    policy.validate_proposal(original,context,check)
    key=policy.digest({k:context[k] for k in ('issue_id','source_task','contract_sha256',
                                            'snapshot_sha256','failure_output_sha256')})
    state=dict(key=key,context=context,original_contract=original,stage='awaiting_proposal',
               author_blocked=True,delivery_approval=False)
    initialize(con)
    con.execute('INSERT OR IGNORE INTO product_scope_plans VALUES (?,?)',(key,encoded(state)))
    stored=load(con,key)
    if stored['context']!=context or stored['original_contract']!=original:
        raise ValueError('existing scope intent changed; independent diagnosis required')
    return stored


def task_identity(task):
    return {k:task.get(k) for k in ('id','agent_id','issue_id','status')}


def save_transition(con,before,after):
    changed=con.execute('UPDATE product_scope_plans SET data=? WHERE plan_key=? AND data=?',
                        (encoded(after),before['key'],encoded(before)))
    if changed.rowcount!=1:raise ValueError('scope intent changed during observation')
    return after


def record_proposal(con,key,proposal,native_task):
    state=load(con,key)
    context=state['context']
    proposal=policy.validate_proposal(state['original_contract'],context,proposal)
    task=task_identity(native_task)
    if (not task['id'] or task['status']!='completed' or task['agent_id']!=context['cto']
            or task['issue_id']!=context['issue_id']):
        raise ValueError('authenticated completed CTO proposal task required')
    if 'proposal' in state:
        if state['proposal']!=proposal or state['proposal_task']!=task:
            raise ValueError('immutable scope proposal already recorded')
        return state
    if state['stage']!='awaiting_proposal':raise ValueError('scope proposal phase required')
    return save_transition(con,state,dict(state,stage='awaiting_review',proposal=proposal,
                           proposal_sha256=policy.digest(proposal),proposal_task=task))


def record_review(con,key,review,native_task,observed_read_hashes):
    state=load(con,key)
    if 'proposal' not in state:raise ValueError('recorded scope proposal required')
    task=task_identity(native_task)
    qualification=policy.qualify_review(state['context'],state['proposal'],review,
                                        state['proposal_task'],task,observed_read_hashes)
    if 'review' in state:
        if state['review']!=review or state['review_task']!=task or state['qualification']!=qualification:
            raise ValueError('immutable scope review already recorded')
        return state
    if state['stage']!='awaiting_review':raise ValueError('scope review phase required')
    return save_transition(con,state,dict(state,stage=qualification['status'],review=review,
                           review_task=task,qualification=qualification,
                           observed_read_hashes={p:observed_read_hashes[p] for p in state['proposal']['write_files']}))
