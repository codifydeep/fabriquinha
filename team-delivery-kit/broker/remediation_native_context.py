"""Durable fixed context projection, without status/assignment/wakeup authority."""
import json
import re
import time
import urllib.error
import urllib.request
from execution_context import reference,validate
try:
    import remediation_author_context as author
    import remediation_product_context as product
    import remediation_execution as execution
    import remediation_runtime_guard as guard
    import remediation_red_reference as references
    import remediation_test_review as review
    import technical_remediation_plan as planning
    import native
except ImportError:
    from broker import remediation_author_context as author
    from broker import remediation_product_context as product
    from broker import remediation_execution as execution
    from broker import remediation_runtime_guard as guard
    from broker import remediation_red_reference as references
    from broker import remediation_test_review as review
    from broker import technical_remediation_plan as planning
    from broker import native

digest=planning.digest


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS remediation_native_contexts('
                'source_task TEXT,step TEXT,intent TEXT,state TEXT,PRIMARY KEY(source_task,step))')


class Effects(planning.Effects):
    def get(self,key):return native.issue_record(self.settings,key)
    def wakeups(self,key):return self.issues.request('/issues/'+key+'/wakeups')
    def put(self,key,body):
        if (set(body)!={'description','suppress_run'} or body['suppress_run'] is not True
                or not re.fullmatch(r'DELIVERY_EXECUTION_CONTEXT_V1:[a-f0-9]{64}:implementation',body['description'])):
            raise ValueError('fixed non-executing context projection required')
        request=urllib.request.Request('http://backend:8080/api/issues/'+key,
            headers={'Authorization':'Bearer '+self.settings['token'],
                     'X-Workspace-ID':self.settings['workspace_id'],'Content-Type':'application/json'},
            data=json.dumps(body).encode(),method='PUT')
        with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)


def qualify(b,source,step,fx):
    if step not in ('R1','R2'):raise ValueError('fixed remediation execution step required')
    with b.db() as con:
        row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
        if not row:raise ValueError('registered recovery required')
        value,state=map(json.loads,row);runtime=state.get(step.lower()+'_runtime') or {}
        issue=state.get('steps',{}).get(step,{}).get('issue_id')
        if (state.get('execution_authorized') is not False or state.get('r2_issue_hold') or state.get('native_context_hold')
                or not issue or runtime.get('issue_id')!=issue or runtime.get('execution_authorized') is not False
                or runtime.get('dispatch_ready') is not False or runtime.get('release_homologated') is not False
                or runtime.get('execution_contract_sha256')!=digest(value)):
            raise ValueError('exact paused runtime without execution authority required')
        route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        source_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(value['source_issue'],)).fetchone()
        if not route_row or not source_row:raise ValueError('original and current routes required')
        route,original=json.loads(route_row[0]),json.loads(source_row[0])
        capsule=validate(route['execution_context'])
        if (route.get('enabled') is not False or capsule['sha256']!=runtime.get('context_sha256')
                or reference(capsule,'implementation')!=runtime.get('desired_issue_description')):
            raise ValueError('paused exact runtime context required')
        commands=[con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(key,)).fetchone()
                  for key in (value['source_issue'],issue)]
        if (any(not c for c in commands) or commands[0][0]!=commands[1][0]
                or digest(commands[1][0])!=runtime.get('test_command_sha256')):
            raise ValueError('original full-suite command required')
    root=fx.get(value['root_issue'])
    if root.get('status') in ('done','cancelled'):raise ValueError('nonterminal root required')
    if step=='R1':
        if guard.qualified(b,issue)!=value or state.get('r1_gate'):raise ValueError('unexecuted qualified R1 required')
        if route!=author.route(value,original,issue):raise ValueError('exact original R1 context required')
        with b.db() as con:
            policy=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
        if not policy or digest(json.loads(policy[0]))!=runtime.get('review_policy_sha256'):
            raise ValueError('registered immutable R1 review policy required')
        desired=execution.issue_spec(value,root)
    else:
        if route!=product.route(value,state,original,issue):raise ValueError('exact original R2 context required')
        red=references.qualified(b,issue)
        if not red or digest(red)!=runtime.get('reference_sha256'):raise ValueError('exact foreign Red reference required')
        _,r1,_=references.binding(b,issue,source)
        review.verify(b,red['origin_issue'],r1,red['red'],fx.native)
        with b.db() as con:
            row=con.execute('SELECT spec FROM remediation_r2_issues WHERE source_task=?',(source,)).fetchone()
        if not row:raise ValueError('persisted dependent-card specification required')
        desired=json.loads(row[0])
    return dict(issue_id=issue,parent_id=value['root_issue'],run_id=value['run_id'],step=step,
        context_sha256=capsule['sha256'],description=reference(capsule,'implementation'),
        runtime_sha256=digest(runtime),execution_contract_sha256=digest(value),owner=route['techlead'],
        expected_native={**desired,'id':issue,'assignee_id':None})


def publish(b,source,step,*,now=None):
    now=time.time() if now is None else now
    with b.LOCK:
        fx=Effects(b);intent=qualify(b,source,step,fx);issue=fx.get(intent['issue_id'])
        expected=intent['expected_native']
        if any(issue.get(k)!=v for k,v in expected.items() if k!='description'):
            raise ValueError('exact unassigned todo native recovery card required')
        with b.db() as con:
            initialize(con)
            if con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                    "WHERE n.issue_id=? AND l.status IN ('creating','starting','running','closing')",(intent['issue_id'],)).fetchone():
                raise ValueError('native context cannot change an executing issue')
            row=con.execute('SELECT intent,state FROM remediation_native_contexts WHERE source_task=? AND step=?',(source,step)).fetchone()
            if row:
                if json.loads(row[0])!=intent:raise ValueError('immutable native context intent drift')
                state=json.loads(row[1])
                if state['stage']=='blocked':return state
            else:
                if issue.get('description')!=expected['description']:
                    raise ValueError('unrecorded or unrelated native context cannot be adopted')
                state=dict(stage='intent',created_at=now,execution_authorized=False,release_homologated=False)
                con.execute('INSERT INTO remediation_native_contexts VALUES (?,?,?,?)',(source,step,json.dumps(intent,sort_keys=True),json.dumps(state,sort_keys=True)))
        def save(new):
            nonlocal state
            with b.db() as con:
                row=con.execute('SELECT state FROM remediation_native_contexts WHERE source_task=? AND step=?',(source,step)).fetchone()
                if json.loads(row[0])!=state:raise ValueError('concurrent native context projection')
                con.execute('UPDATE remediation_native_contexts SET state=? WHERE source_task=? AND step=?',(json.dumps(new,sort_keys=True),source,step))
            state=new
        if issue.get('description')==intent['description']:
            if state['stage']=='published':return state
            save({**state,'stage':'published','context_sha256':intent['context_sha256'],
                  'runtime_sha256':intent['runtime_sha256'],'observed_at':now})
            return state
        if issue.get('description')!=expected['description']:raise ValueError('native context changed outside exact intent')
        if state['stage']=='published':raise ValueError('published native context reverted')
        if state['stage']=='intent':
            wakeups=fx.wakeups(intent['issue_id'])
            if not isinstance(wakeups,list) or any(w.get('enabled') is True for w in wakeups):
                raise ValueError('no enabled wakeup allowed during paused context projection')
            save({**state,'stage':'write_observe'})
            fx.put(intent['issue_id'],dict(description=intent['description'],suppress_run=True))
            observed=fx.get(intent['issue_id'])
            if any(observed.get(k)!=v for k,v in expected.items() if k!='description'):
                raise ValueError('native metadata changed during fixed projection')
            if observed.get('description')==intent['description']:
                save({**state,'stage':'published','context_sha256':intent['context_sha256'],
                      'runtime_sha256':intent['runtime_sha256'],'observed_at':now})
                return state
            if observed.get('description')!=expected['description']:raise ValueError('unexpected native context after fixed projection')
        elapsed=now-state['created_at']
        save({**state,'stage':'blocked' if elapsed>=1800 else 'observing','alert':elapsed>=600,
              'owner':intent.get('owner','techlead'),'required_action':'reconcile exact native description intent; do not repeat PUT'})
        return state


def retain_hold(b,source,step,category):
    with b.LOCK,b.db() as con:
        row=con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
        if not row:return
        state=json.loads(row[0]);runtime=state.get(step.lower()+'_runtime') or {}
        route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(runtime.get('issue_id'),)).fetchone()
        if not route:return
        owner=json.loads(route[0])['techlead']
        hold=dict(step=step,issue_id=runtime['issue_id'],category=category,owner=owner,
            required_action='reconcile preserved native context intent and exact paused runtime; no repeated PUT or author wakeup',
            execution_authorized=False,release_homologated=False)
        if state.get('native_context_hold'):return
        state.update(native_context_hold=hold,required_action=hold['required_action'])
        con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))


def tick(b):
    with b.db() as con:
        initialize(con)
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_executions'").fetchone():return
        rows=con.execute('SELECT source_task,state FROM remediation_executions').fetchall()
    for source,raw in rows:
        state=json.loads(raw)
        if state.get('native_context_hold') or state.get('r2_issue_hold'):continue
        for step in ('R1','R2'):
            if not state.get(step.lower()+'_runtime'):continue
            with b.db() as con:
                prior=con.execute('SELECT state FROM remediation_native_contexts WHERE source_task=? AND step=?',(source,step)).fetchone()
            if prior and json.loads(prior[0])['stage']=='published':continue
            with b.db() as con:
                latest=json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])
                if latest.get('native_context_hold'):break
                observation=latest.get('native_context_observations',{}).get(step)
                if observation is None:
                    observation=dict(started_at=time.time(),execution_authorized=False)
                    latest['native_context_observations']={**latest.get('native_context_observations',{}),step:observation}
                    con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(latest,sort_keys=True),source))
            if time.time()-observation['started_at']>=1800:
                retain_hold(b,source,step,'native_context_observation_deadline')
                break
            try:
                result=publish(b,source,step)
                if result['stage']=='blocked':retain_hold(b,source,step,'native_context_observation_deadline')
            except urllib.error.HTTPError as error:
                if error.code in (502,503,504):continue
                retain_hold(b,source,step,'native_context_http_rejected')
            except (TimeoutError,ConnectionError,urllib.error.URLError):continue
            except Exception as error:
                if type(error).__name__=='DockerOperationTimeout':continue
                retain_hold(b,source,step,'native_context_precondition_failed')
