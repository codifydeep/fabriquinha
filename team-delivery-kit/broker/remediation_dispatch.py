"""Durable initial R1/R2 dispatch; route activation is a separate admission gate."""
import json
import time
import urllib.error
from execution_context import validate,reference
try:
    import native
    import handoff_runtime
    import remediation_author_context as author
    import remediation_product_context as product
    import remediation_native_context as presentation
    import remediation_runtime_guard as guard
    import remediation_red_reference as references
    import remediation_test_review as review
except ImportError:
    from broker import native,handoff_runtime
    from broker import remediation_author_context as author
    from broker import remediation_product_context as product
    from broker import remediation_native_context as presentation
    from broker import remediation_runtime_guard as guard
    from broker import remediation_red_reference as references
    from broker import remediation_test_review as review

digest=presentation.digest


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS remediation_dispatches('
                'source_task TEXT,step TEXT,marker TEXT,binding TEXT,state TEXT,PRIMARY KEY(source_task,step))')
    con.execute('CREATE TABLE IF NOT EXISTS remediation_dispatch_holds(source_task TEXT,step TEXT,data TEXT,PRIMARY KEY(source_task,step))')
    con.execute('CREATE TABLE IF NOT EXISTS remediation_dispatch_observations(source_task TEXT,step TEXT,started_at REAL,PRIMARY KEY(source_task,step))')


class Effects(presentation.Effects):
    def issue(self,key):return self.get(key)
    def runs(self,key):return native.issue_task_runs(self.settings,key)
    def remaining_calls(self):return self.native.remaining_calls()
    def wake(self,*args,**kwargs):return self.native.ensure_unit_start(*args,**kwargs)
    def available(self,issue,agent):
        with self.b.db() as con:
            active=con.execute("SELECT n.issue_id,n.agent_id FROM leases l LEFT JOIN native_bindings n USING(request_id) "
                "WHERE l.status IN ('creating','starting','running','closing')").fetchall()
            pending=con.execute('SELECT binding,state FROM remediation_dispatches').fetchall()
        if len(active)>=2 or any(r[1]==agent for r in active):return False
        reservations=[]
        for bound,raw in pending:
            bound,state=json.loads(bound),json.loads(raw)
            if bound['issue_id']==issue:continue
            unresolved=state.get('post_attempted') and not state.get('task_id')
            if not unresolved:continue
            if any(r[0]==bound['issue_id'] and r[1]==bound['author'] for r in active):continue
            reservations.append(bound)
        return len(active)+len(reservations)<2 and not any(r['author']==agent for r in reservations)


def binding(b,source,step,fx):
    if step not in ('R1','R2'):raise ValueError('fixed recovery execution step required')
    with b.db() as con:
        row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
        if not row:return None
        value,state=map(json.loads,row);runtime=state.get(step.lower()+'_runtime')
        if not runtime:return None
        issue=runtime['issue_id']
        row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        pub=con.execute('SELECT intent,state FROM remediation_native_contexts WHERE source_task=? AND step=?',(source,step)).fetchone()
        original=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(value['source_issue'],)).fetchone()
        if not row or not pub or not original:raise ValueError('registered route and actual native presentation required')
        route=json.loads(row[0]);intent,receipt=map(json.loads,pub)
        original=json.loads(original[0]);capsule=validate(route['execution_context'])
        command=con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(issue,)).fetchone()
        if (state.get('native_context_hold') or state.get('r2_issue_hold')
                or receipt.get('stage')!='published' or receipt.get('context_sha256')!=capsule['sha256']
                or receipt.get('runtime_sha256')!=digest(runtime) or intent.get('runtime_sha256')!=digest(runtime)
                or intent.get('execution_contract_sha256')!=digest(value)
                or runtime.get('execution_contract_sha256')!=digest(value)
                or runtime.get('execution_authorized') is not False or runtime.get('release_homologated') is not False
                or intent.get('description')!=reference(capsule,'implementation')
                or runtime.get('context_sha256')!=capsule['sha256']
                or not command or digest(command[0])!=runtime['test_command_sha256']):
            raise ValueError('exact real published context, original full suite and immutable runtime required')
    expected=author.route(value,original,issue) if step=='R1' else product.route(value,state,original,issue)
    if {**route,'enabled':False}!=expected:raise ValueError('exact scoped recovery route required')
    if step=='R1':
        if guard.qualified(b,issue)!=value:raise ValueError('original tests-only R1 qualification required')
        with b.db() as con:
            policy=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
        if not policy or digest(json.loads(policy[0]))!=runtime['review_policy_sha256']:
            raise ValueError('immutable R1 review policy drift')
    else:
        red=references.qualified(b,issue)
        if not red or digest(red)!=runtime['reference_sha256']:raise ValueError('current approved R1 Red required')
        _,r1,_=references.binding(b,issue,source)
        review.verify(b,red['origin_issue'],r1,red['red'],fx.native)
    if route['enabled']:
        root=fx.get(value['root_issue'])
        if root.get('status') in ('done','cancelled'):raise ValueError('nonterminal release root required')
    return dict(source_task=source,step=step,issue_id=issue,author=route['author'],owner=route['techlead'],
        enabled=route['enabled'],minimum_calls=route['minimum_calls'],context_sha256=capsule['sha256'],
        execution_contract_sha256=digest(value),native_context_sha256=digest(intent),description=intent['description'])


def dispatch(b,source,step,*,now=None):
    now=time.time() if now is None else now
    with b.LOCK:
        fx=Effects(b)
        with b.db() as con:
            initialize(con)
            hold=con.execute('SELECT data FROM remediation_dispatch_holds WHERE source_task=? AND step=?',(source,step)).fetchone()
            if hold:return json.loads(hold[0])
            prior=con.execute('SELECT marker,binding,state FROM remediation_dispatches WHERE source_task=? AND step=?',(source,step)).fetchone()
            if prior and json.loads(prior[2])['stage'] in ('accepted','blocked'):return json.loads(prior[2])
        bound=binding(b,source,step,fx)
        if bound is None:return dict(stage='paused',release_homologated=False)
        immutable={k:v for k,v in bound.items() if k!='enabled'};marker=digest(immutable)
        if prior:
            if prior[0]!=marker or json.loads(prior[1])!=immutable:raise ValueError('immutable dispatch context drift')
            state=json.loads(prior[2])
        else:
            if not bound['enabled']:return dict(stage='paused',release_homologated=False)
            state=dict(stage='pending',created_at=now,owner=bound['owner'],post_attempted=False,release_homologated=False)
            with b.db() as con:
                con.execute('INSERT INTO remediation_dispatches VALUES (?,?,?,?,?)',
                    (source,step,marker,json.dumps(immutable,sort_keys=True),json.dumps(state,sort_keys=True)))
        def save(**extra):
            nonlocal state
            updated={**state,**extra}
            if updated==state:return state
            with b.db() as con:
                old=con.execute('SELECT state FROM remediation_dispatches WHERE source_task=? AND step=?',(source,step)).fetchone()
                if json.loads(old[0])!=state:raise ValueError('concurrent recovery dispatch')
                con.execute('UPDATE remediation_dispatches SET state=? WHERE source_task=? AND step=?',(json.dumps(updated,sort_keys=True),source,step))
            state=updated
            return state
        if now-state['created_at']>=1800:
            return save(stage='blocked',category='dispatch_or_acceptance_unattended',
                        required_action='reconcile exact wakeup and capacity/budget evidence; no identical author restart')
        if not state['post_attempted']:
            if not bound['enabled']:return dict(**{**state,'stage':'paused'})
            if fx.remaining_calls()<bound['minimum_calls']:return save(stage='budget_wait',alert=now-state['created_at']>=600)
            if not fx.available(bound['issue_id'],bound['author']):return save(stage='capacity_wait',alert=now-state['created_at']>=600)
            issue=fx.issue(bound['issue_id'])
            if (issue.get('id')!=bound['issue_id'] or issue.get('status')!='todo' or issue.get('assignee_id') is not None
                    or issue.get('description')!=bound['description']):
                raise ValueError('exact unassigned native card with presented context required')
            save(stage='write_observe',post_attempted=True)
            allow=True
        else:allow=False
        if not state.get('wakeup_id'):
            note=('CONTROLLER RECOVERY '+step+'. Use the complete registered context '+bound['description']+
                '. Execute only the current phase. Do not recreate previous tasks or implement another phase. '
                'The controller captures and verifies artifacts, tests and independent reviews. '
                'Completion of this task does not approve a release.')
            wake=fx.wake(bound['issue_id'],bound['author'],source,marker,note,allow_create=allow)
            if wake is None:
                if now-state['created_at']>=600 and not state.get('alert'):return save(alert=True)
                return state  # An uncertain POST is observation-only forever.
            if not isinstance(wake.get('id'),str) or not wake['id']:raise ValueError('actual wakeup identity required')
            save(stage='awaiting_acceptance',wakeup_id=wake['id'],dispatched_at=now)
        matches=[t for t in fx.runs(bound['issue_id']) if t.get('wakeup_id')==state['wakeup_id']]
        if len(matches)>1:raise ValueError('duplicate native acceptance')
        if matches:
            task=matches[0]
            if task.get('issue_id')!=bound['issue_id'] or task.get('agent_id')!=bound['author'] or not task.get('id'):
                raise ValueError('wrong native acceptance identity')
            if task.get('status') in ('running','completed'):
                return save(stage='accepted',task_id=task['id'],accepted_at=now,execution_result=task['status'])
            if task.get('status') in ('failed','cancelled'):
                return save(stage='blocked',task_id=task['id'],category='author_execution_failed',
                    required_action='Tech Lead diagnose preserved task before a changed-contract recovery; no identical restart')
        if now-state['created_at']>=600 and not state.get('alert'):return save(alert=True)
        return state


def retain_hold(b,source,step,category):
    with b.LOCK,b.db() as con:
        initialize(con)
        if con.execute('SELECT 1 FROM remediation_dispatch_holds WHERE source_task=? AND step=?',(source,step)).fetchone():return
        row=con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
        if not row:return
        parent=json.loads(row[0]);runtime=parent.get(step.lower()+'_runtime') or {}
        route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(runtime.get('issue_id'),)).fetchone()
        route=json.loads(route[0]) if route else {}
        hold=dict(stage='blocked',step=step,issue_id=runtime.get('issue_id'),category=category,
            owner=route.get('techlead','techlead'),required_action='diagnose preserved dispatch intent, exact wakeup and capacity/budget; no identical restart',
            release_homologated=False)
        con.execute('INSERT INTO remediation_dispatch_holds VALUES (?,?,?)',(source,step,json.dumps(hold,sort_keys=True)))
        parent['remediation_dispatch_holds']={**parent.get('remediation_dispatch_holds',{}),step:hold}
        parent['required_action']=hold['required_action']
        con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(parent,sort_keys=True),source))


def tick(b):
    with b.db() as con:
        initialize(con)
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_executions'").fetchone():return
        rows=con.execute('SELECT source_task,state FROM remediation_executions').fetchall()
    for source,raw in rows:
        parent=json.loads(raw)
        if (parent.get('r1_gate') and parent.get('remediation_dispatch_holds',{}).get('R1',{}).get('category')=='author_execution_failed'):
            # Fresh live verification retires only the superseded source hold.
            # The author session remains failed and all R2 admission gates run.
            try:
                with b.db() as con:
                    r1=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                        (parent['r1_gate']['red']['issue_id'],)).fetchone()[0])
                review.record_gate(b,r1,parent['r1_gate']['red'],Effects(b).native)
                with b.db() as con:
                    parent=json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])
            except (ValueError,KeyError,TypeError,TimeoutError,ConnectionError,urllib.error.URLError):
                continue  # Keep the exact hold; no unverified resolution.
        for step in ('R1','R2'):
            if step=='R1' and parent.get('r1_gate'):continue
            if not parent.get(step.lower()+'_runtime') or parent.get('remediation_dispatch_holds',{}).get(step):continue
            with b.db() as con:
                issue=parent[step.lower()+'_runtime']['issue_id']
                route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
                prior=con.execute('SELECT state FROM remediation_dispatches WHERE source_task=? AND step=?',(source,step)).fetchone()
                pending=json.loads(prior[0]) if prior else {}
                if pending.get('stage')=='accepted':continue
                enabled=bool(route and json.loads(route[0]).get('enabled'))
                if not enabled and not pending.get('post_attempted'):continue
                con.execute('INSERT OR IGNORE INTO remediation_dispatch_observations VALUES (?,?,?)',(source,step,time.time()))
                started=con.execute('SELECT started_at FROM remediation_dispatch_observations WHERE source_task=? AND step=?',(source,step)).fetchone()[0]
            if time.time()-started>=1800:
                retain_hold(b,source,step,'dispatch_observation_deadline')
                continue
            try:
                result=dispatch(b,source,step)
                if result['stage']=='blocked':retain_hold(b,source,step,result.get('category','dispatch_blocked'))
            except urllib.error.HTTPError as error:
                if error.code in (502,503,504):continue
                retain_hold(b,source,step,'dispatch_http_rejected')
            except (TimeoutError,ConnectionError,urllib.error.URLError,handoff_runtime.BudgetStatusUnavailable):continue
            except Exception as error:
                if type(error).__name__=='DockerOperationTimeout':continue
                retain_hold(b,source,step,'dispatch_precondition_failed')
