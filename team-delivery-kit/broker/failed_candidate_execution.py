"""Durable one-execution admission for an independently reviewed technical replan.

Internal ledger, not a worker API. Runtime integration MUST obtain facts from
fixed validators, immutable Red receipts and native task identities, and verify
the current durable failed diagnostic before calling register. Agent text or
tool arguments cannot supply facts. No installed route uses this ledger yet.
"""
import json
import hashlib
try:
    from .failed_candidate_plan import digest
except ImportError:
    from failed_candidate_plan import digest


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS failed_candidate_execution_grants('
                'issue_id TEXT PRIMARY KEY,body TEXT NOT NULL)')


def validator_inventory(con,source,volume,offline_image,red,edit_files,*,kind='structure',expected_manifest=None,manifest_only=False):
    """Read actual completed fixed-validator receipts, never agent assertions."""
    if kind not in ('structure','candidate_inventory') or (manifest_only and kind!='structure'):
        raise ValueError('fixed structural or candidate metadata receipt required')
    if (not edit_files and not manifest_only) or len(set(edit_files))!=len(edit_files):
        raise ValueError('exact installed product edit scope required')
    candidates=[]
    for row in con.execute('SELECT identity,state FROM validation_jobs'):
        identity,state=map(json.loads,row)
        if identity.get('task')!=source or identity.get('kind')!=kind:continue
        payload=identity.get('payload') or {};result=state.get('result') or {}
        if (state.get('stage')!='complete' or result.get('exit_code')!=0
                or payload.get('Image')!=offline_image
                or not any(m.get('Source')==volume and m.get('ReadOnly') is True
                    for m in payload.get('HostConfig',{}).get('Mounts',[]))):continue
        output=result.get('output','')
        if hashlib.sha256(output.encode()).hexdigest()!=result.get('output_sha256'):continue
        proof=json.loads(output)
        if kind=='candidate_inventory' and (proof.get('delivery_approval') is not False or proof.get('tests_executed') is not False):continue
        if kind=='candidate_inventory' and (not expected_manifest or proof.get('manifest_sha256')!=expected_manifest):continue
        if (proof.get('baseline_tests_intact') is not True
                or proof.get('base_manifest_sha256')!=red.get('base_manifest_sha256')
                or proof.get('baseline_test_sha256')!=red.get('baseline_test_sha256')
                or proof.get('new_test_sha256')!=red.get('test_sha256')):continue
        inventory=(proof.get('product_file_sha256') if kind=='candidate_inventory' else proof.get('diagnostic_file_sha256')) or {}
        if not set(edit_files)<=set(inventory):continue
        value=dict(manifest_sha256=proof.get('manifest_sha256'),
            product_sha256={p:inventory[p] for p in edit_files},
            test_sha256=proof['new_test_sha256'],baseline_test_sha256=proof['baseline_test_sha256'])
        hashes=[value['manifest_sha256'],*value['product_sha256'].values(),
                *value['test_sha256'].values(),*value['baseline_test_sha256'].values()]
        if any(not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for h in hashes):continue
        if value not in candidates:candidates.append(value)
    if len(candidates)!=1:
        raise ValueError('one exact immutable validator inventory with unchanged Red and baseline required')
    return candidates[0]


def load(con,issue):
    initialize(con)
    row=con.execute('SELECT body FROM failed_candidate_execution_grants WHERE issue_id=?',(issue,)).fetchone()
    return json.loads(row[0]) if row else None


def persist(con,issue,state):
    con.execute('UPDATE failed_candidate_execution_grants SET body=? WHERE issue_id=?',
                (json.dumps(state,sort_keys=True),issue))
    return state


def register(con,route,data,facts):
    """Called under controller transaction/lock, after external evidence checks.

    The issue-level primary key survives source changes and process restarts.
    A grant never resets the ordinary identical-correction counter.
    """
    initialize(con)
    plan=data.get('failed_candidate_plan') or {};peer=data.get('failed_candidate_plan_review') or {}
    if (plan.get('operation')!='failed_candidate_plan_v1'
            or peer.get('operation')!='failed_candidate_plan_review_v1'
            or peer.get('status')!='reviewed_replan_requires_bounded_execution_adapter'
            or peer.get('plan_sha256')!=digest(plan)
            or peer.get('diagnostic_sha256')!=plan.get('diagnostic_sha256')
            or plan.get('diagnostic_sha256')!=digest(data.get('failed_execution_diagnostic'))
            or peer.get('cto_task')!=plan.get('cto_task')
            or not peer.get('techlead_task') or peer['techlead_task']==plan.get('cto_task')
            or len({route['author'],route['cto'],route['techlead']})!=3
            or any(plan.get(k)!=route[v] for k,v in (('author','author'),('cto','cto'),('reviewer','techlead')))
            or any(value.get('contract_sha256')!=route['contract_sha256'] for value in (plan,peer,facts))
            or plan.get('issue_id')!=route['issue_id'] or facts.get('issue_id')!=route['issue_id']
            or plan.get('source_task')!=data.get('source_task') or facts.get('source_task')!=data.get('source_task')
            or any(value.get(k) is not False for value in (plan,peer)
                   for k in ('author_execution_authorized','tests_may_change','delivery_approval'))
            or peer.get('retry_budget_reset') is not False
            or facts.get('source_status')!='failed' or facts.get('diagnostic_only') is not True
            or any(facts.get(k) is not True for k in ('baseline_tests_intact','frozen_tests_intact','independent_tasks_verified'))
            or facts.get('active_leases')!=0 or not facts.get('volume')
            or not facts.get('manifest_sha256') or not facts.get('test_sha256')
            or not facts.get('baseline_test_sha256') or not facts.get('product_sha256')
            or not set(facts['product_sha256'])<=set(plan.get('edit_files',[]))
            or set(facts['product_sha256']) & (set(facts['test_sha256'])|set(facts['baseline_test_sha256']))
            or not facts.get('previous_product_sha256')
            or any(previous==facts['product_sha256'] for previous in facts['previous_product_sha256'])
            or type(facts.get('identical_corrections')) is not int or facts['identical_corrections']<2
            or type(data.get('attempts')) is not int or data['attempts']<0):
        raise ValueError('changed immutable candidate, preserved tests and exact independently reviewed plan required')
    grant=dict(operation='failed_candidate_execution_v1',issue_id=route['issue_id'],
        source_task=data['source_task'],plan_sha256=digest(plan),review_sha256=digest(peer),
        candidate_facts_sha256=digest(facts),prior_attempts=data['attempts'],author=route['author'],
        prior_identical_corrections=facts['identical_corrections'],
        attempt_limit=1,retry_budget_reset=False,delivery_approval=False,tests_may_change=False,
        contract_sha256=route['contract_sha256'],
        seed=dict(mount=dict(Type='volume',Source=facts['volume'],Target='/previous',ReadOnly=True),
            selection=dict(manifest_sha256=facts['manifest_sha256'],test_sha256=facts['test_sha256'],
                product_sha256=facts['product_sha256'],bounded_execution=dict(
                    operation='reviewed_failed_candidate_seed_v1',source_task=data['source_task'],plan_sha256=digest(plan)))),
        status='admitted_not_dispatched')
    grant['grant_sha256']=digest(grant)
    old=load(con,route['issue_id'])
    if old:
        if old['grant_sha256']!=grant['grant_sha256']:
            raise ValueError('issue recovery allowance already bound; no new grant or retry reset')
        return old
    con.execute('INSERT INTO failed_candidate_execution_grants VALUES(?,?)',
                (route['issue_id'],json.dumps(grant,sort_keys=True)))
    return grant


def dispatch_intent(con,issue,grant_sha,marker):
    """Persist before native effects; unknown acknowledgments observe this marker."""
    state=load(con,issue)
    if (not state or state['grant_sha256']!=grant_sha or not marker
            or state['status'] not in ('admitted_not_dispatched','dispatch_intent','execution_bound')
            or state.get('dispatch_marker',marker)!=marker):
        raise ValueError('single stable recovery dispatch intent required')
    state['dispatch_marker']=marker
    if state['status']=='admitted_not_dispatched':state['status']='dispatch_intent'
    return persist(con,issue,state)


def bind_dispatch(con,issue,grant_sha,marker,task):
    """Bind one exact observed native execution, not an uncertain second POST."""
    state=load(con,issue)
    binding=dict(marker=marker,task_id=task)
    if (not state or state['grant_sha256']!=grant_sha or not marker or not task
            or state['status'] not in ('dispatch_intent','execution_bound')
            or state.get('dispatch_marker')!=marker
            or state.get('dispatch',binding)!=binding):
        raise ValueError('one exact active recovery execution required')
    state.update(status='execution_bound',dispatch=binding)
    return persist(con,issue,state)


def record_wakeup(con,issue,marker,wakeup):
    state=load(con,issue)
    if (not state or state.get('dispatch_marker')!=marker or not wakeup
            or state['status'] not in ('dispatch_intent','execution_bound')
            or state.get('wakeup_id',wakeup)!=wakeup):
        raise ValueError('exact recovery wakeup required')
    state['wakeup_id']=wakeup
    return persist(con,issue,state)


def observe_author(con,route,source):
    state=load(con,route['issue_id'])
    if not state or state['status'] not in ('dispatch_intent','execution_bound') or source['id']==state['source_task']:
        return None
    if (source.get('agent_id')!=state['author'] or state['author']!=route['author']
            or source.get('issue_id')!=route['issue_id'] or not state.get('wakeup_id')
            or source.get('wakeup_id')!=state['wakeup_id']):
        raise ValueError('unrelated author cannot consume bounded recovery')
    state=bind_dispatch(con,route['issue_id'],state['grant_sha256'],state['dispatch_marker'],source['id'])
    if source.get('status') in ('failed','completed'):
        state=finish(con,route['issue_id'],source['id'],source['status'],'native-task:'+source['id'])
    return state


def seed_source(b,issue):
    """One hash-bound candidate; this does not restart or approve an author."""
    try:
        from . import bound_failure_context
    except ImportError:
        import bound_failure_context
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='failed_candidate_execution_grants'").fetchone():return None
        state=load(con,issue)
        if not state or state['status'] not in ('dispatch_intent','execution_bound'):return None
        row=con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(state['source_task'],)).fetchone()
        installed=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        data=json.loads(row[0]) if row else {};route=json.loads(installed[0]) if installed else {}
        if (route.get('enabled') is not True or route.get('author')!=state['author']
                or route.get('contract_sha256')!=state['contract_sha256']
                or data.get('failed_candidate_execution',{}).get('grant_sha256')!=state['grant_sha256']
                or data.get('dispatch_marker')!=state.get('dispatch_marker')
                or not bound_failure_context.verified_failed_diagnostic(con,state['source_task'],data)):
            raise ValueError('current durable recovery seed binding required')
    labels=(b.docker('GET','/volumes/'+state['seed']['mount']['Source']) or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=state['source_task']:
        raise ValueError('immutable recovery seed ownership drift')
    return state['seed']


def finish(con,issue,task,status,evidence_reference):
    """Worker termination is not delivery approval or incident resolution."""
    state=load(con,issue)
    result=dict(task_id=task,status=status,evidence_reference=evidence_reference)
    if (not state or state.get('dispatch',{}).get('task_id')!=task
            or status not in ('failed','completed') or not evidence_reference
            or state['status'] not in ('execution_bound','blocked_technical_recovery','awaiting_delivery_validation')
            or state.get('terminal',result)!=result):
        raise ValueError('exact terminal execution evidence required')
    state.update(terminal=result,owner='cto' if status=='failed' else 'techlead',
        status='blocked_technical_recovery' if status=='failed' else 'awaiting_delivery_validation')
    return persist(con,issue,state)
