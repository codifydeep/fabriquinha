"""One explicit author wakeup after independently reviewed scope registration.

Native admission reobserves the exact wakeup without creating work, binds its
new task before grants and qualifies historical Red. A note is never authority.
Terminal failure remains visible; this module does not repeat author attempts.
"""
import time
try:
    from . import product_scope_ledger as ledger, product_scope_execution as execution, product_scope_job as job
    from . import product_scope_task_binding as binding, product_scope_worker as worker, native
except ImportError:
    import product_scope_ledger as ledger
    import product_scope_execution as execution
    import product_scope_job as job
    import product_scope_task_binding as binding
    import product_scope_worker as worker
    import native


PREFIX='DELIVERY_SCOPE_AUTHOR_START'


def note(state):
    receipt=state['registration']['receipt']
    marker=ledger.policy.digest(dict(plan_key=state['key'],contract_sha256=receipt['contract_sha256'],
                                   manifest_sha256=receipt['manifest_sha256'],phase='author'))
    text=('Continue the existing card against its independently reviewed revised code scope. '
          'Inspect the seeded files and frozen tests, implement the correction, run the full registered suite. '
          'Never recreate Red, edit tests, weaken assertions, change discovery or claim delivery approval.\n'
          'Reviewed correction: '+state['proposal']['reason']+'\n'
          'Code scope: '+ledger.encoded(sorted(set(receipt['contract']['editable_files'])-
                                                   set(receipt['contract']['test_files'])))+'\n'
          'Contract SHA256: '+receipt['contract_sha256']+'\n'
          'Frozen test SHA256: '+ledger.encoded(receipt['frozen_test_sha256']))
    if len(text)>3500:raise ValueError('bounded author scope instruction required')
    return marker,text


def exact_note(state):
    marker,text=note(state)
    return PREFIX+' '+marker+'\nSource: '+state['context']['source_task']+'\n'+text


class Effects(execution.NativeEffects):
    def author_wake(self,state,marker,text,*,allow_create=True):
        c=state['context']
        return native.ensure_scope_author_start(self.settings,c['issue_id'],c['author'],c['source_task'],
                                                marker,text,allow_create=allow_create)


def tick(b,key,effects=None,*,now=None):
    fx=effects or Effects(b);now=time.time() if now is None else now
    with b.LOCK,b.db() as con:
        state=ledger.load(con,key);binding.registered(con,state)
    dispatch=state.get('dispatch',{}).get('author')
    if dispatch and dispatch['stage'] in ('blocked','admitted'):return state
    job.reauthenticate(state,fx)
    marker,text=note(state)
    if not dispatch:
        dispatch=dict(stage='intent',marker=marker,deadline=now+600)
        state=execution.save(b,state,dict(state,dispatch=dict(state.get('dispatch',{}),author=dispatch)))
    if dispatch['marker']!=marker:raise ValueError('immutable author dispatch identity changed')
    wake=fx.author_wake(state,marker,text)
    if not wake or not wake.get('id') or dispatch.get('wakeup_id') not in (None,wake['id']):
        raise ValueError('exact author wakeup identity required')
    dispatch=dict(dispatch,stage='observing',wakeup_id=wake['id'])
    identifier=wake.get('last_task_id')
    if identifier:
        task=fx.task(identifier,state['context']['author'])
        if (task.get('id')!=identifier or task.get('issue_id')!=state['context']['issue_id']
                or task.get('agent_id')!=state['context']['author'] or task.get('wakeup_id')!=wake['id']
                or task.get('handoff_note')!=exact_note(state)):
            raise ValueError('exact selected author task identity required')
        if task.get('status') not in ('queued','running'):
            dispatch.update(stage='blocked',incident=dict(category='scope_author_terminal_before_admission',
                owner=state['context']['reviewer'],next_action='diagnose_exact_task',automatic_retry=False))
    elif now>=dispatch['deadline']:
        dispatch.update(stage='blocked',incident=dict(category='scope_author_wakeup_unattended',
            owner=state['context']['reviewer'],next_action='diagnose_exact_wakeup',automatic_retry=False))
    return execution.save(b,state,dict(state,dispatch=dict(state['dispatch'],author=dispatch)))


def admit(b,task,effects=None):
    text=task.get('handoff_note') or ''
    if not text.startswith(PREFIX+' '):return None
    fx=effects or Effects(b)
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='product_scope_plans'").fetchone():
            raise ValueError('registered scope author intent required')
        states=[ledger.load(con,row[0]) for row in con.execute('SELECT plan_key FROM product_scope_plans')]
    matches=[s for s in states if s.get('registration',{}).get('stage')=='complete'
             and s['context']['issue_id']==task.get('issue_id') and s['context']['author']==task.get('agent_id')
             and exact_note(s)==text]
    if len(matches)!=1:raise ValueError('one exact scope author intent required')
    state=matches[0];dispatch=state.get('dispatch',{}).get('author')
    if not dispatch or dispatch['stage'] not in ('intent','observing','admitted'):
        raise ValueError('active persisted scope author dispatch required')
    marker,instruction=note(state)
    wake=fx.author_wake(state,marker,instruction,allow_create=False)
    identifier=task.get('task_id') or task.get('id')
    if (not identifier or not wake or wake.get('id')!=task.get('wakeup_id')
            or wake.get('last_task_id')!=identifier
            or dispatch.get('wakeup_id') not in (None,wake['id'])
            or dispatch.get('task_id') not in (None,identifier)):
        raise ValueError('exact existing scope author wakeup/task required')
    updated=dict(dispatch,stage=dispatch['stage'] if dispatch['stage']=='admitted' else 'observing',
                 wakeup_id=wake['id'],task_id=identifier)
    if dispatch!=updated:
        state=execution.save(b,state,dict(state,dispatch=dict(state['dispatch'],author=updated)))
    try:
        selected=(binding.lookup(b,task['issue_id'],identifier) if dispatch['stage']=='admitted'
                  else binding.bind(b,state['key'],identifier,fx))
        if not selected:raise ValueError('admitted scope task lost its immutable binding')
        config=worker.selection(b,task['issue_id'],identifier)
        if not config:raise ValueError('reviewed historical Red selection required')
    except (ValueError,KeyError,TypeError):
        with b.LOCK,b.db() as con:current=ledger.load(con,state['key'])
        if current==state:
            execution.save(b,state,dict(state,dispatch=dict(state['dispatch'],author=dict(updated,stage='blocked',
                incident=dict(category='scope_author_admission_rejected',owner=state['context']['reviewer'],
                              next_action='diagnose_exact_task_and_red',automatic_retry=False)))))
        raise
    if state['dispatch']['author']['stage']!='admitted':
        execution.save(b,state,dict(state,dispatch=dict(state['dispatch'],author=dict(updated,stage='admitted'))))
    return selected


def prompt(b,task):
    identifier=task.get('task_id') or task.get('id')
    selected=binding.lookup(b,task.get('issue_id'),identifier)
    if selected is None:raise ValueError('bound scope author task required')
    with b.db() as con:state=ledger.load(con,selected['plan_key'])
    if (task.get('agent_id')!=selected['author'] or task.get('wakeup_id')!=selected['wakeup_id']
            or task.get('handoff_note')!=exact_note(state)):
        raise ValueError('scope author prompt identity drift')
    worker.selection(b,task['issue_id'],identifier)
    return exact_note(state)
