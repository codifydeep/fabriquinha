"""Explicit full-chain admission; activate each qualified phase exactly once.

No agent can call this module as a tool. Registration is a controller/operator
operation. Admission never resets depth, raises the paid proxy cap, copies Red,
or turns execution/review acceptance into release success.
"""
import json
import time
try:
    import remediation_dispatch as dispatch
    import technical_remediation_plan as planning
except ImportError:
    from broker import remediation_dispatch as dispatch
    from broker import technical_remediation_plan as planning

REQUIRED_CALLS=256


def initialize(con):
    dispatch.initialize(con)
    con.execute('CREATE TABLE IF NOT EXISTS remediation_admissions('
                'source_task TEXT PRIMARY KEY,intent TEXT,state TEXT)')


class Effects(dispatch.Effects):
    def plan(self,source):
        with self.b.db() as con:
            row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
        if not row:raise ValueError('approved native remediation plan required')
        config,state=map(json.loads,row)
        if state.get('stage')!='plan_approved':raise ValueError('independent plan approval required')
        for phase,key,role,wake in (('awaiting_plan','plan_task','cto',state['plan_wakeup']),
                                    ('awaiting_review','review_task','reviewer',state['wakeup_id'])):
            task=self.task(state[key],config[role]);body=self.result(task)
            if (not planning.validate_result(config,{**state,'stage':phase,'wakeup_id':wake},task,body,self.reads(task))
                    or body!=state['plan' if role=='cto' else 'review']):
                raise ValueError('current actual independent plan execution required')
        return config,state


def request(b,source):
    """Record a full-chain request without dispatch or budget-cap changes."""
    with b.LOCK:
        fx=Effects(b);config,approved=fx.plan(source)
        bound=dispatch.binding(b,source,'R1',fx)
        if not bound or bound['enabled']:raise ValueError('qualified paused R1 required for admission request')
        with b.db() as con:
            initialize(con)
            value,state=map(json.loads,con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
            if (value.get('original_depth')!=2 or value.get('root_issue')!=config['root_issue']
                    or value.get('plan_sha256')!=planning.digest(approved['plan'])
                    or state.get('r1_gate') or state.get('execution_authorized') is not False):
                raise ValueError('exact unexecuted original full-chain admission required')
            intent=dict(operation='remediation_full_chain_admission_v1',source_task=source,
                root_issue=value['root_issue'],execution_contract_sha256=planning.digest(value),
                plan_sha256=value['plan_sha256'],original_depth=2,minimum_calls=REQUIRED_CALLS,
                release_homologated=False)
            row=con.execute('SELECT intent,state FROM remediation_admissions WHERE source_task=?',(source,)).fetchone()
            if row:
                if json.loads(row[0])!=intent:raise ValueError('immutable admission request drift')
                return json.loads(row[1])
            receipt=dict(stage='awaiting_budget',created_at=time.time(),steps={},release_homologated=False)
            con.execute('INSERT INTO remediation_admissions VALUES(?,?,?)',
                        (source,json.dumps(intent,sort_keys=True),json.dumps(receipt,sort_keys=True)))
            return receipt


def reconcile(b,source):
    """Wait safely for capacity/budget; enable only live-qualified R1 then R2."""
    with b.LOCK:
        fx=Effects(b)
        with b.db() as con:
            initialize(con)
            row=con.execute('SELECT intent,state FROM remediation_admissions WHERE source_task=?',(source,)).fetchone()
            if not row:return None
            intent,state=map(json.loads,row)
            value,parent=map(json.loads,con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
        if (intent['execution_contract_sha256']!=planning.digest(value) or value.get('original_depth')!=2
                or intent.get('release_homologated') is not False):raise ValueError('admission contract drift')
        if (state.get('stage')=='blocked' and state.get('category')=='superseded_by_r1_feedback'
                and parent.get('r1_gate')):
            try:import review_successor_resolution
            except ImportError:from broker import review_successor_resolution
            state=review_successor_resolution.resolve(b,source,fx)
        if state['stage']=='blocked':
            # A dependency incident remains preserved, but its resolved hold
            # must not permanently starve an already authorized full chain.
            # Every live binding, approval, budget and native-context check
            # below still runs before any route activation.
            if (state.get('category')!='admission_dependency_hold'
                    or not state.get('steps',{}).get('R1') or state.get('steps',{}).get('R2')
                    or not parent.get('r1_gate') or not parent.get('r2_runtime')
                    or parent.get('native_context_hold') or parent.get('r2_issue_hold')
                    or parent.get('remediation_dispatch_holds')):
                return state
            prior=json.loads(json.dumps(state))
            prior.pop('dependency_hold_history',None)  # History stays once, in the outer ledger.
            state={k:v for k,v in state.items() if k not in ('owner','category')}
            state.update(stage='awaiting_dependency',dependency_hold_history=[
                *state.get('dependency_hold_history',[]),dict(previous_state=prior,
                resolved_at=time.time(),phase_activated=False,release_homologated=False)])
        def save(**extra):
            nonlocal state
            state={**state,**extra,'release_homologated':False}
            with b.db() as con:
                con.execute('UPDATE remediation_admissions SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
            return state
        root=fx.issue(intent['root_issue'])
        if root.get('id')!=intent['root_issue'] or root.get('status') not in ('todo','in_progress','blocked'):
            return save(stage='blocked',owner='techlead',category='admission_root_not_active')
        if parent.get('native_context_hold') or parent.get('r2_issue_hold') or parent.get('remediation_dispatch_holds'):
            return save(stage='blocked',owner='techlead',category='admission_dependency_hold')
        step='R2' if parent.get('r1_gate') else 'R1'
        if state['steps'].get(step):return state  # Never undo an operator pause or re-enable R1 after its gate.
        bound=dispatch.binding(b,source,step,fx)
        if bound is None:return save(stage='awaiting_dependency',next_step=step)
        if bound['enabled']:return save(stage='blocked',owner='techlead',category='unrecorded_phase_activation')
        minimum=REQUIRED_CALLS if not state.get('budget_admitted') else bound['minimum_calls']
        remaining=fx.remaining_calls()
        if type(remaining) is not int or remaining<minimum:return save(stage='awaiting_budget',next_step=step,required_calls=minimum)
        if not fx.available(bound['issue_id'],bound['author']):return save(stage='awaiting_capacity',next_step=step)
        fx.plan(source)  # Re-read actual CTO/TL approvals before every phase activation.
        issue=fx.issue(bound['issue_id'])
        if (issue.get('id')!=bound['issue_id'] or issue.get('status')!='todo' or issue.get('assignee_id') is not None
                or issue.get('description')!=bound['description']):
            return save(stage='blocked',owner='techlead',category='admission_native_context_changed')
        if dispatch.binding(b,source,step,fx)!=bound:raise ValueError('phase binding changed during admission')
        receipt=dict(issue_id=bound['issue_id'],binding_sha256=planning.digest({k:v for k,v in bound.items() if k!='enabled'}),
                     stage='phase_enabled',enabled_at=time.time(),release_homologated=False)
        # One transaction binds route activation and its durable receipt. No API
        # or wakeup effect occurs here; the existing dispatcher owns that intent.
        with b.db() as con:
            current=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(bound['issue_id'],)).fetchone()
            route=json.loads(current[0])
            if route.get('enabled') is not False:raise ValueError('concurrent phase activation')
            route['enabled']=True
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),bound['issue_id']))
            state={**state,'stage':'phases_admitted','budget_admitted':True,
                   'steps':{**state['steps'],step:receipt},'release_homologated':False}
            con.execute('UPDATE remediation_admissions SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return state


def tick(b):
    with b.db() as con:
        initialize(con);sources=[r[0] for r in con.execute('SELECT source_task FROM remediation_admissions')]
    for source in sources:
        try:reconcile(b,source)
        except (TimeoutError,ConnectionError):continue
        except Exception as error:
            if type(error).__name__ in ('URLError','DockerOperationTimeout','BudgetStatusUnavailable'):continue
            with b.LOCK,b.db() as con:
                row=con.execute('SELECT state FROM remediation_admissions WHERE source_task=?',(source,)).fetchone()
                state=json.loads(row[0])
                if state.get('stage')=='blocked':continue
                state.update(stage='blocked',owner='techlead',category='admission_precondition_failed',release_homologated=False)
                con.execute('UPDATE remediation_admissions SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
