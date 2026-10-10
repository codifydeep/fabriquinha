"""Drive independently approved recovery through existing qualified adapters.

This is not a new retry budget or executor. Every underlying adapter retains its
own source-bound intents, observation handles and fail-closed permission gates.
"""
import json
import time
import hashlib
from pathlib import Path
try:
    import technical_remediation_plan as plans, remediation_execution as execution
    import remediation_preparation as preparation, remediation_author_context as author
    import remediation_native_context as presentation, remediation_admission as admission
except ImportError:
    from broker import technical_remediation_plan as plans, remediation_execution as execution
    from broker import remediation_preparation as preparation, remediation_author_context as author
    from broker import remediation_native_context as presentation, remediation_admission as admission


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_remediation_drivers('
                'source_task TEXT PRIMARY KEY,binding TEXT,state TEXT)')


def binding(config, plan):
    if config.get('intake_kind')=='rejected_remediation_r1_v1':
        feedback=config.get('r1_feedback',{})
        if (feedback.get('operation')!='remediation_r1_review_feedback_v1'
                or type(feedback.get('round')) is not int or not 1<=feedback['round']<=2
                or feedback.get('revision_depth_reset') is not False or feedback.get('execution_authorized') is not False):
            raise ValueError('bounded original R1 feedback required')
    if (config.get('intake_kind') not in ('exhausted_frozen_suite_v1','rejected_remediation_r1_v1')
            or config.get('original_depth') != 2 or len(config.get('revision_lineage', [])) != 2
            or plan.get('stage') != 'plan_approved' or plan.get('execution_authorized') is not False
            or plan.get('release_homologated') is not False
            or plan.get('plan_sha256') != plans.digest(plan.get('plan'))
            or plan.get('review', {}).get('decision') != 'approve_plan'
            or plan.get('review', {}).get('plan_sha256') != plan['plan_sha256']
            or not plan.get('plan_task') or not plan.get('review_task')
            or plan['plan_task'] == plan['review_task']):
        raise ValueError('independently approved generic recovery binding required')
    return dict(operation='generic_reviewed_remediation_driver_v1',source_task=config['source_task'],
        config_sha256=plans.digest(config),plan_sha256=plan['plan_sha256'],
        plan_task=plan['plan_task'],review_task=plan['review_task'],
        root_issue=config['root_issue'],original_depth=2,revision_depth_reset=False,
        release_homologated=False)


def next_action(state, context, requested):
    if state is None:return 'register_execution'
    stage = state.get('stage')
    if stage in ('r1_issue_intent','r1_issue_post_pending','r1_issue_observe'):return 'provision_issue'
    if stage in ('r1_provision_pending','r1_seed_provision_pending','r1_base_job_intent',
                 'r1_base_job_created','r1_base_job_start_pending','r1_base_job_running'):return 'prepare_base'
    if stage != 'r1_base_qualified':return 'technical_hold'
    if not state.get('r1_runtime'):return 'prepare_context'
    if not context or context.get('stage') != 'published':return 'publish_context'
    if requested is None:return 'request_full_chain'
    return 'await_delivery_gates'


def changed_base_binding_state(config, plan, prior, recorded_binding, current, *, active, effects_present):
    """Pure qualification of a known pre-job adapter capability rejection."""
    try:import base_equivalence
    except ImportError:from broker import base_equivalence
    if (active or effects_present or config.get('amendment',{}).get('kind')!='inherited_frozen_suite'
            or prior.get('stage')!='technical_hold' or prior.get('action')!='register_execution'
            or prior.get('category')!='ValueError' or recorded_binding!=binding(config,plan)):
        raise ValueError('unchanged approved inherited plan and pre-effect adapter hold required')
    base_equivalence.validate_bindings(config,current)
    return dict(stage='operation_pending',action='register_execution',owner=config['reviewer'],
        execution_authorized=False,release_homologated=False,
        required_action='supervisor qualify full original-base byte equivalence with changed adapter')


def reconcile_base_binding(b, source):
    """Maintenance-only repair; preserve the hold and approvals, never run them."""
    try:import controller_maintenance,base_equivalence,native
    except ImportError:from broker import controller_maintenance,base_equivalence,native
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS generic_base_binding_repairs(source_task TEXT PRIMARY KEY,receipt TEXT)')
            maintenance=controller_maintenance.current(c)
            if not maintenance or maintenance['stage']!='sealed':raise ValueError('sealed maintenance required')
            saved=c.execute('SELECT receipt FROM generic_base_binding_repairs WHERE source_task=?',(source,)).fetchone()
            if saved:return json.loads(saved[0])
            row=c.execute('SELECT binding,state FROM generic_remediation_drivers WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('exact driver hold required')
            recorded,prior=map(json.loads,row)
            active=bool(c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone())
            effects_present=bool(c.execute('SELECT 1 FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='original_base_equivalences_v2'").fetchone():
                effects_present=effects_present or bool(c.execute('SELECT 1 FROM original_base_equivalences_v2 WHERE source_task=?',(source,)).fetchone())
        fx=Effects(b);config,plan=fx.approved(source)  # Actual completed independent native approvals.
        settings=json.loads((b.STATE/'native.json').read_text())
        for issue in (config['source_issue'],plan['issue_id']):
            if any(t.get('status') in ('queued','running','dispatched') for t in native.issue_task_runs(settings,issue)):
                raise ValueError('idle native recovery scope required')
        name=b.PREFIX+'-base-equivalence-v2-'+source
        effects_present=effects_present or bool(b.docker('GET','/containers/'+name+'/json'))
        current=b.issue_base(config['source_issue'])
        updated=changed_base_binding_state(config,plan,prior,recorded,current,
            active=active,effects_present=effects_present)
        receipt=dict(operation='changed_base_binding_adapter_reconciliation_v1',previous_state=prior,
            binding=recorded,current_base=current,
            adapter_sha256=hashlib.sha256(Path(base_equivalence.__file__).read_bytes()).hexdigest(),
            execution_authorized=False,approvals_changed=False,author_restarted=False,
            jobs_replayed=False,revision_depth_reset=False)
        with b.db() as c:
            if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
            if (controller_maintenance.current(c)!=maintenance
                    or list(map(json.loads,c.execute('SELECT binding,state FROM generic_remediation_drivers WHERE source_task=?',(source,)).fetchone()))!=[recorded,prior]
                    or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()
                    or c.execute('SELECT 1 FROM remediation_executions WHERE source_task=?',(source,)).fetchone()):
                raise ValueError('adapter hold changed before reconciliation')
            c.execute('INSERT INTO generic_base_binding_repairs VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
            c.execute('UPDATE generic_remediation_drivers SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return receipt


class Effects:
    def __init__(self,b):self.b=b
    def approved(self,source):return admission.Effects(self.b).plan(source)
    def state(self,source):
        with self.b.db() as con:
            execution.initialize(con);presentation.initialize(con);admission.initialize(con)
            row=con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
            context=con.execute('SELECT state FROM remediation_native_contexts WHERE source_task=? AND step=?',(source,'R1')).fetchone()
            requested=con.execute('SELECT state FROM remediation_admissions WHERE source_task=?',(source,)).fetchone()
        return tuple(json.loads(r[0]) if r else None for r in (row,context,requested))
    def idle(self):
        with self.b.db() as con:
            return not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    def perform(self,source,action):
        operations={'register_execution':execution.register,'provision_issue':execution.provision_issue,
                    'prepare_base':preparation.prepare,'prepare_context':author.prepare,
                    'request_full_chain':admission.request}
        if action=='publish_context':return presentation.publish(self.b,source,'R1')
        return operations[action](self.b,source)


def advance(b, source, effects=None):
    fx=effects or Effects(b)
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            prior=con.execute('SELECT binding,state FROM generic_remediation_drivers WHERE source_task=?',(source,)).fetchone()
            previous=json.loads(prior['state']) if prior else None
            if previous and previous.get('stage') in ('technical_hold','await_delivery_gates'):return previous
        if not fx.idle():return dict(stage='awaiting_capacity',release_homologated=False)
        config,plan=fx.approved(source)  # Actual native hash-bound CTO/TL approvals, not prose.
        bound=binding(config,plan)
        if bound['source_task']!=source:raise ValueError('exact requested recovery source required')
        if prior and json.loads(prior['binding'])!=bound:raise ValueError('immutable recovery driver binding drift')
        execution_state,context,requested=fx.state(source)
        action=next_action(execution_state,context,requested)
        state=dict(stage='await_delivery_gates' if action=='await_delivery_gates' else
                   'technical_hold' if action=='technical_hold' else 'operation_pending',
                   action=action,owner=config['cto'] if action=='technical_hold' else config['reviewer'],
                   release_homologated=False,execution_authorized=False,updated_at=time.time())
        if action=='technical_hold':state['required_action']='CTO diagnose preserved execution-adapter hold; no identical restart'
        with b.db() as con:
            initialize(con)
            con.execute('INSERT INTO generic_remediation_drivers VALUES(?,?,?) ON CONFLICT(source_task) DO UPDATE SET state=excluded.state',
                (source,json.dumps(bound,sort_keys=True),json.dumps(state,sort_keys=True)))
        if action in ('await_delivery_gates','technical_hold'):return state
        try:fx.perform(source,action)
        except Exception as error:
            transient= isinstance(error,(TimeoutError,ConnectionError)) or type(error).__name__ in (
                'URLError','DockerOperationTimeout','BudgetStatusUnavailable')
            state.update(stage='observe_existing_operation' if transient else 'technical_hold',
                owner=config['reviewer'] if transient else config['cto'],
                category=type(error).__name__,required_action='Observe adapter-owned exact intent/handle; no repeated uncertain POST' if transient else
                'CTO diagnose exact execution-adapter rejection; no identical retry')
            with b.db() as con:
                con.execute('UPDATE generic_remediation_drivers SET state=? WHERE source_task=?',
                    (json.dumps(state,sort_keys=True),source))
        return state


def tick(b):
    with b.db() as con:
        plans.initialize(con);initialize(con)
        candidates=[r['source_task'] for r in con.execute('SELECT source_task,config,state FROM technical_remediation_plans')
            if json.loads(r['config']).get('intake_kind') in ('exhausted_frozen_suite_v1','rejected_remediation_r1_v1')
            and json.loads(r['state']).get('stage')=='plan_approved']
    for source in candidates:
        try:advance(b,source)
        except Exception as error:
            if isinstance(error,(TimeoutError,ConnectionError)) or type(error).__name__ in ('URLError','DockerOperationTimeout','BudgetStatusUnavailable'):continue
            # Qualification fails before effects; preserve a visible hold once.
            with b.db() as con:
                row=con.execute('SELECT state FROM generic_remediation_drivers WHERE source_task=?',(source,)).fetchone()
                state=json.loads(row[0]) if row else {}
                state.update(stage='technical_hold',category=type(error).__name__,owner='cto',
                    required_action='CTO diagnose rejected actual plan qualification; no identical retry',release_homologated=False)
                con.execute('INSERT INTO generic_remediation_drivers VALUES(?,?,?) ON CONFLICT(source_task) DO UPDATE SET state=excluded.state',
                    (source,'{}',json.dumps(state,sort_keys=True)))
