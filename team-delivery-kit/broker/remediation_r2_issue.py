"""Durable R2 card creation after real R1 approval, without worker authority."""
import json
import time
import urllib.error
import uuid
try:
    import remediation_author_context as context
    import remediation_test_review as review
    import technical_remediation_plan as planning
except ImportError:
    from broker import remediation_author_context as context
    from broker import remediation_test_review as review
    from broker import technical_remediation_plan as planning


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS remediation_r2_issues(source_task TEXT PRIMARY KEY,input_sha256 TEXT,spec TEXT,state TEXT)')


def dependency_busy(con,state):
    gate=state['r1_gate']
    tasks=(gate['red']['task_id'],gate['review_task'])
    return bool(con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
        "WHERE n.task_id IN (?,?) AND l.status IN ('creating','starting','running','closing')",tasks).fetchone())


def issue_spec(value,state,parent):
    inputs=context.product_input(value,state);step=value['steps'][1]
    if parent.get('id')!=value['root_issue'] or parent.get('status') in ('done','cancelled'):
        raise ValueError('nonterminal exact root required for recovery')
    text=('REMEDIATION R2 — PRODUCT ONLY; no worker dispatch yet.\nRun: '+value['run_id']+
        '\nApproved plan: '+value['plan_sha256']+'\nObjective: '+step['objective']+
        '\nRed origin='+inputs['origin_issue']+' task='+inputs['red']['task_id']+
        ' manifest='+inputs['red']['red']['manifest_sha256']+
        '\nApproved acceptance (unchanged):\n'+'\n'.join(k+': '+v for k,v in sorted(value['criteria'].items()))+
        '\nWritable product files: '+json.dumps(inputs['editable_files'])+
        '\nReadonly frozen tests: '+json.dumps(inputs['readonly_tests'])+
        '\nPrepare the original Git base and seed exact R1 tests before dispatch. '
        'Never edit tests, baseline, discovery or historical snapshots. Never recreate or relabel Red. '
        'Full Green and independent immutable product review remain mandatory. '
        'Product PR, exact-SHA CI, merge, local deploy and browser QA are subsequent controller gates. '
        'This card is not a release or homologation approval.')
    if len(text)>7000:raise ValueError('split lossless R2 context before issue creation')
    return dict(title='Remediation R2 '+planning.digest(value)[:16],description=text,
                parent_issue_id=value['root_issue'],project_id=parent.get('project_id'),stage=1,status='todo')


def provision(b,source,*,now=None):
    now=time.time() if now is None else now
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('registered recovery required')
            value,parent_state=map(json.loads,row);inputs=context.product_input(value,parent_state)
            if dependency_busy(con,parent_state):
                raise ValueError('R1 source/review lease must close before dependent-card provisioning')
            r1=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(inputs['origin_issue'],)).fetchone()[0])
        fx=planning.Effects(b)
        review.verify(b,inputs['origin_issue'],r1,inputs['red'],fx.native)
        parent=fx.issues.request('/issues/'+value['root_issue']);desired=issue_spec(value,parent_state,parent)
        identity=planning.digest(dict(value=value,r1_gate=parent_state['r1_gate'],spec=desired))
        with b.db() as con:
            existing=con.execute('SELECT input_sha256,spec,state FROM remediation_r2_issues WHERE source_task=?',(source,)).fetchone()
            if existing:
                if existing[0]!=identity or json.loads(existing[1])!=desired:raise ValueError('immutable dependent-card input drift')
                state=json.loads(existing[2])
                if state['stage'] in ('issue_created','blocked'):return state
            else:
                state=dict(stage='issue_intent',created_at=now,owner=r1['techlead'],
                    execution_authorized=False,release_homologated=False)
                con.execute('INSERT INTO remediation_r2_issues VALUES(?,?,?,?)',
                    (source,identity,json.dumps(desired,sort_keys=True),json.dumps(state,sort_keys=True)))
        def save(new):
            nonlocal state
            with b.db() as con:
                actual=json.loads(con.execute('SELECT state FROM remediation_r2_issues WHERE source_task=?',(source,)).fetchone()[0])
                if actual!=state:raise ValueError('concurrent dependent issue transition')
                con.execute('UPDATE remediation_r2_issues SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
            state=new
        allow=state['stage']=='issue_intent'
        if allow:save({**state,'stage':'issue_post_pending'})
        elif state['stage'] not in ('issue_post_pending','issue_observe'):
            raise ValueError('exact pending dependent issue required')
        try:item=fx.issues.ensure(desired,allow_create=allow)
        except (TimeoutError,ConnectionError,urllib.error.URLError):item=None
        if item is None:
            elapsed=now-state['created_at']
            save({**state,'stage':'blocked' if elapsed>=1800 else 'issue_observe',
                'observations':state.get('observations',0)+1,'alert':elapsed>=600,
                'required_action':'Tech Lead reconcile exact R2 create intent; do not repeat POST',
                'next_check_at':None if elapsed>=1800 else now+15})
            if state['stage']=='blocked':publish_hold(b,source,'dependent_issue_observation_deadline')
            return state
        if str(uuid.UUID(item['id']))!=item['id']:raise ValueError('canonical created issue identity required')
        new={**state,'stage':'issue_created','issue_id':item['id'],'identifier':item.get('identifier'),
            'created_observed_at':now,'required_action':'prepare_original_base_frozen_tests_and_lossless_context_before_dispatch'}
        with b.db() as con:
            actual=json.loads(con.execute('SELECT state FROM remediation_r2_issues WHERE source_task=?',(source,)).fetchone()[0])
            current=json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])
            if actual!=state or current!=parent_state:raise ValueError('dependent issue or parent changed before binding')
            con.execute('UPDATE remediation_r2_issues SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
            current['steps']={**current['steps'],'R2':dict(stage='provision_pending',issue_id=item['id'],identifier=item.get('identifier'))}
            current['required_action']=new['required_action']
            con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(current,sort_keys=True),source))
        return new


def publish_hold(b,source,category,*,required_action='diagnose exact R2 input/root/create intent; no identical retry'):
    """Project an unresolved technical hold through the existing handoff channel."""
    with b.db() as con:
        parent=json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])
        origin=parent['steps']['R1']['issue_id']
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(origin,)).fetchone()[0])
        hold=dict(category=category,owner=route['techlead'],
            required_action=required_action,
            execution_authorized=False,release_homologated=False)
        if parent.get('r2_issue_hold')==hold:return
        parent.update(r2_issue_hold=hold,required_action=hold['required_action'])
        con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(parent,sort_keys=True),source))
        try:import handoffs
        except ImportError:from broker import handoffs
        handoffs.initialize(con)
        handoffs.save(con,parent['r1_gate']['red']['task_id'],origin,'remediation_r2_blocked',
                      route['techlead'],hold,time.time())


def tick(b):
    with b.db() as con:
        initialize(con)
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_executions'").fetchone():return
        rows=con.execute('SELECT source_task,state FROM remediation_executions').fetchall()
    for row in rows:
        state=json.loads(row[1])
        if not state.get('r1_gate') or state.get('steps',{}).get('R1',{}).get('stage')!='approved':continue
        with b.db() as con:
            if dependency_busy(con,state):continue  # Only the actual dependency; unrelated work cannot starve creation.
        if state.get('r2_issue_hold'):continue
        with b.db() as con:
            prior=con.execute('SELECT state FROM remediation_r2_issues WHERE source_task=?',(row[0],)).fetchone()
        saved=json.loads(prior[0]) if prior else {}
        if saved.get('stage') in ('issue_created','blocked') or saved.get('next_check_at',0)>time.time():continue
        try:provision(b,row[0])
        except (TimeoutError,ConnectionError,urllib.error.URLError):continue
        except ValueError:
            with b.db() as con:
                latest=con.execute('SELECT state FROM remediation_r2_issues WHERE source_task=?',(row[0],)).fetchone()
                if latest:
                    current=json.loads(latest[0]);current.update(stage='blocked',category='dependent_issue_precondition_failed',
                        required_action='Tech Lead diagnose retained R2 issue intent; no new POST or worker')
                    con.execute('UPDATE remediation_r2_issues SET state=? WHERE source_task=?',(json.dumps(current,sort_keys=True),row[0]))
            publish_hold(b,row[0],'dependent_issue_precondition_failed')
