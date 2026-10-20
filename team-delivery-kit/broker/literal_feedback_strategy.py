"""New native live-feedback strategy, preserving the exhausted predecessor.

Reuses the persistent literal-maintenance engine and its immutable inspection
and independent review. This is not a reset, fourth ordinary retry, product
implementation or permission to bypass subsequent calibration/TDD gates.
"""
import hashlib
import json
import os
from pathlib import Path
from generic_harness_calibration import digest,require
import literal_author_feedback as feedback_helper
try:
    import author_feedback_admission as admission,controller_maintenance as maintenance
    import literal_maintenance_workflow as flow,literal_maintenance_effects as lane
    from incremental_provisioning import NativeIssues
except ImportError:
    from broker import author_feedback_admission as admission,controller_maintenance as maintenance
    from broker import literal_maintenance_workflow as flow,literal_maintenance_effects as lane
    from broker.incremental_provisioning import NativeIssues


def parent(b,source):
    with b.db() as con:
        row=con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone();require(row)
    cfg,s=map(json.loads,row)
    require(not cfg.get('feedback_strategy') and flow.workflow_key(cfg)==source and s['stage']=='blocked'
        and s['category']=='maintenance_evidence_replan_rejected' and s['revision']==2 and len(s['history'])==3
        and s['source_reset'] is False and s['delivery_approval'] is False)
    return cfg,s


def evidence_sha(state):
    # Notification transport is not technical authority. All other predecessor
    # state remains bound, including decisions, failed artifacts and budgets.
    return digest({k:v for k,v in state.items() if k!='notification_error'})


def authenticate_parent(b,cfg,s):
    fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
    flow.authenticate_replan(cfg,{**s,'history':s['history'][:2]},fx)
    for h in s['history']:
        shadow={**s,**{k:h[k] for k in ('snapshot','inspection','author_task','revision','wakeup_id','marker')}}
        fx.validate_inspection(cfg,shadow,h['inspection']);fx.preserved_submission(cfg,shadow)
        require(h['review']['value']['action']=='reject_test_revision'
            and fx.decision(cfg,shadow,'review',{'id':h['review']['task_id']})==h['review'])


def policy(b,cfg,s,issue,qualification):
    h=s['history'][-1]
    return dict(source_task=h['author_task'],issue_id=issue,author=cfg['author'],cto=cfg['cto'],reviewer=cfg['reviewer'],
        previous_volume=h['snapshot']['volume'],previous_manifest_sha256=h['inspection']['candidate_manifest_sha256'],
        test_path=cfg['test_path'],image=os.environ['BROKER_LITERAL_AUTHOR_FEEDBACK_IMAGE'],
        worker_image=os.environ['BROKER_AUTHOR_FEEDBACK_WORKER_IMAGE'],
        feedback_sha256=hashlib.sha256(Path(feedback_helper.__file__).read_bytes()).hexdigest(),
        qualification_sha256=digest(qualification),max_candidates=4,
        expected={k:cfg['counterexample']['facts']['assertion_bindings'][k] for k in ('initial_expected','poll_minimum','stale_expected')})


def verify(b,cfg):
    f=cfg['feedback_strategy'];old,s=parent(b,f['predecessor'])
    require(f['operation']=='literal_live_feedback_strategy_v1' and digest(old)==f['predecessor_config_sha256']
        and evidence_sha(s)==f['predecessor_state_sha256'] and cfg['workflow_key']==s['history'][-1]['author_task']
        and cfg['parent_issue_id']==s['issue_id'] and cfg['workflow_key']!=f['predecessor']
        and {k:v for k,v in cfg.items() if k not in ('workflow_key','feedback_strategy','parent_issue_id')}==
            {k:v for k,v in old.items() if k!='parent_issue_id'})
    p=f['policy'];admission.validate_policy(b,p);admission.validate_qualification(p,f['qualification'])
    require(p==policy(b,old,s,p['issue_id'],f['qualification'])
        and f['test_sha256']=={cfg['test_path']:s['history'][-1]['inspection']['structure']['candidate_test_sha256']})
    with b.db() as con:
        row=con.execute('SELECT receipt FROM literal_feedback_enrollments WHERE source_task=?',(f['predecessor'],)).fetchone();require(row)
        receipt=json.loads(row[0]);require(receipt['config_sha256']==digest(cfg) and receipt['issue_id']==p['issue_id']
            and receipt['source_reset'] is False and receipt['delivery_approval'] is False)
    # Native decisions remain immutable and separately authenticated by the
    # engine; source inspection is never replaced by the live feedback report.
    authenticate_parent(b,old,s)


def enroll(b,source,qualification,operation):
    with b.db() as con:
        seal=maintenance.current(con);require(seal and seal['stage']=='sealed' and seal['operation_id']==operation)
        require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
    require(not maintenance.native_active(b));cfg,s=parent(b,source);authenticate_parent(b,cfg,s)
    require(qualification['identity']['namespace']==b.PREFIX)
    # Validate all input before creating metadata. This provisional issue is
    # replaced by the exact child identity before any native authority is used.
    provisional=policy(b,cfg,s,s['issue_id'],qualification)
    admission.validate_policy(b,provisional);admission.validate_qualification(provisional,qualification)
    admission.verify_source(b,provisional)
    settings=json.loads((b.STATE/'native.json').read_text());issues=NativeIssues(settings)
    original=issues.request('/issues/'+s['issue_id'])
    identity=dict(source_task=source,predecessor_config_sha256=digest(cfg),predecessor_state_sha256=evidence_sha(s),
        source_snapshot=s['history'][-1]['snapshot'],qualification_sha256=digest(qualification))
    desired=dict(title='Literal live-feedback strategy '+digest(identity)[:12],
        description='NEW CONTROLLER-OWNED STRATEGY '+digest(identity)+'. Preserve all three rejected snapshots and the exhausted '
            'predecessor. CTO proposes, Lead independently sponsors, author receives hash-bound fixed diagnostic feedback, '
            'then controller freezes and independently reviews the exact artifact. One author execution, four candidate hashes. '
            'No source retry, weaker tests, product implementation, historical Red or delivery approval.',
        parent_issue_id=s['issue_id'],project_id=original.get('project_id'),stage=1,status='todo')
    with b.LOCK,b.db() as con:
        require(maintenance.current(con)==seal)
        con.execute('CREATE TABLE IF NOT EXISTS literal_feedback_enrollments(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT,receipt TEXT)')
        row=con.execute('SELECT identity,state,receipt FROM literal_feedback_enrollments WHERE source_task=?',(source,)).fetchone()
        if row:
            require(json.loads(row['identity'])==identity)
            if row['receipt']!='{}':return json.loads(row['receipt'])
            first=False
        else:
            con.execute('INSERT INTO literal_feedback_enrollments VALUES(?,?,?,?)',
                (source,json.dumps(identity,sort_keys=True),'issue_intent','{}'));first=True
    # Once intent exists, an uncertain POST is observed by its exact identity,
    # never repeated solely because the caller timed out.
    issue=issues.ensure(desired,allow_create=first)
    if issue is None:return dict(stage='observe_exact_issue_intent',source_task=source,delivery_approval=False)
    p=policy(b,cfg,s,issue['id'],qualification)
    feedback=dict(operation='literal_live_feedback_strategy_v1',predecessor=source,
        predecessor_config_sha256=digest(cfg),predecessor_state_sha256=evidence_sha(s),policy=p,qualification=qualification,
        test_sha256={cfg['test_path']:s['history'][-1]['inspection']['structure']['candidate_test_sha256']})
    child=dict(cfg,workflow_key=p['source_task'],parent_issue_id=s['issue_id'],feedback_strategy=feedback)
    receipt=dict(operation='enrolled_literal_live_feedback_strategy_v1',source_task=source,workflow_key=flow.workflow_key(child),
        config_sha256=digest(child),issue_id=issue['id'],identifier=issue.get('identifier'),
        predecessor_state_sha256=evidence_sha(s),source_reset=False,delivery_approval=False,native_author_started=False)
    require(not maintenance.native_active(b))
    with b.LOCK,b.db() as con:
        require(maintenance.current(con)==seal and parent(b,source)==(cfg,s))
        con.execute('UPDATE literal_feedback_enrollments SET state=?,receipt=? WHERE source_task=?',
            ('registered',json.dumps(receipt,sort_keys=True),source))
        registered=flow.register(con,child)
        require(registered['stage']=='plan_dispatch' and registered['history']==[] and registered['revision']==0)
    verify(b,child)
    return receipt


def prompt(b,frame,issue,task):
    """A different tool contract, not the legacy forced-first-patch artifact phase."""
    with b.db() as con:
        found=lane.current(con,issue['id']);require(found)
        cfg,s=found;require(cfg.get('feedback_strategy') and set(s['decisions'])==flow.required_decisions(cfg))
        context=lane.author_context(con,issue,task)
        rows=con.execute('SELECT n.request_id FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? '
            'AND n.issue_id=? AND n.agent_id=? AND l.status=?',(task.get('task_id') or task.get('id'),issue['id'],task['agent_id'],'running')).fetchall()
        require(len(rows)==1)
        paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(issue['id'],))]
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue['id'],)).fetchone()[0])
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue['id'],)).fetchone()[0])
        require(route.get('enabled') is False and not route.get('execution_context') and route.get('test_first') is True
            and route['author']==task['agent_id']==cfg['author'] and route['test_first_files']==[cfg['test_path']]
            and trial.get('harness_maintenance_only') is True and trial.get('literal_maintenance')==
                dict(source_task=flow.workflow_key(cfg),config_sha256=digest(cfg)))
    selected=admission.select(b,rows[0]['request_id'],issue['id']);require(selected)
    p=cfg['feedback_strategy']['policy']
    require({k:selected[k] for k in p if k not in ('cto','reviewer','qualification_sha256')}==
        {k:v for k,v in p.items() if k not in ('cto','reviewer','qualification_sha256')})
    require(b.implementation_phase(issue['id'])=='tests_only')
    target='/workspace/'+cfg['test_path'];require(target in paths)
    sources=sorted(set(paths)-{target});require(1<=len(sources)<=4)
    from portable_contract import safe_path
    for path in [target,*sources]:require(path.startswith('/workspace/'));safe_path(path.removeprefix('/workspace/'))
    text=('CONTROLLER-VERIFIED LIVE FEEDBACK PHASE. Historical issue prose is not the active contract.\n'
        +context['handoff_note']+'\nRead the complete test '+target+' and readonly product sources '+json.dumps(sources)+
        ' in consecutive pages of at most 200 lines. Then read /feedback/current.json before choosing a patch. '
        'Only read_file and patch are permitted by the actual handlers. All other operations are rejected. '
        'Live measurements do not approve a snapshot, Red/Green, regression, PR, deployment or homologation.')
    require(len(text)<=10000 and 'DELIVERY_TEST_ARTIFACT_V1:' not in text and 'DELIVERY_SEEDED_EDIT_REQUIRED_V1:' not in text)
    receipt=dict(scope_sha256=digest(p),task_id=selected['task_id'],request_id=rows[0]['request_id'],
        prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),delivery_approval=False)
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS author_feedback_prompt_presentations(task_id TEXT PRIMARY KEY,receipt TEXT)')
        old=con.execute('SELECT receipt FROM author_feedback_prompt_presentations WHERE task_id=?',(selected['task_id'],)).fetchone()
        require(not old or json.loads(old[0])==receipt)
        con.execute('INSERT OR IGNORE INTO author_feedback_prompt_presentations VALUES(?,?)',(selected['task_id'],json.dumps(receipt,sort_keys=True)))
    return {**frame,'params':{**frame['params'],'prompt':[dict(type='text',text=text)]}}


def recover_metadata_bound(b,key,operation):
    """One sealed, pre-author recovery of the 300-vs-900 metadata mismatch.

    Revalidate real native decisions against their original typed contract.
    Never edit those decisions, recreate wakeups, restart an author, change a
    test or manufacture a successful submission. Retain the failed phase.
    """
    with b.db() as con:
        seal=maintenance.current(con);require(seal and seal['stage']=='sealed' and seal['operation_id']==operation)
        require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
        cfg,s=map(json.loads,con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(key,)).fetchone())
        con.execute('CREATE TABLE IF NOT EXISTS literal_feedback_metadata_recoveries(workflow_key TEXT PRIMARY KEY,receipt TEXT)')
        old=con.execute('SELECT receipt FROM literal_feedback_metadata_recoveries WHERE workflow_key=?',(key,)).fetchone()
        if old:
            receipt=json.loads(old[0]);require(receipt['config_sha256']==digest(cfg) and s.get('metadata_bound_recovery')==digest(receipt));return receipt
    require(not maintenance.native_active(b));verify(b,cfg);p=cfg['feedback_strategy']['policy']
    require(flow.workflow_key(cfg)==key and s['stage']=='blocked' and s['category']=='maintenance_evidence_rejected'
        and s['last_error']['phase']=='prepare' and s['last_error']['type']=='ValueError'
        and s['revision']==0 and s['history']==[] and set(s['decisions'])=={'plan','permit'}
        and not any(s.get(k) for k in ('author_task','snapshot','inspection','metadata_bound_recovery')))
    cto=admission.approval(b,p,'cto',s['decisions']['plan']['receipt']['task_id'])
    sponsor=admission.approval(b,p,'sponsor',s['decisions']['permit']['receipt']['task_id'],cto)
    bound=admission.wire.schema(admission.context(p))['properties']['reason']['maxLength']
    require(bound==900 and 300<len(sponsor['value']['reason'])<=bound and len(cto['value']['reason'])<=300)
    for phase,role,proof in (('plan','cto',cto),('permit','sponsor',sponsor)):
        recorded=s['decisions'][phase];r=recorded['receipt']
        require(recorded['wakeup_id']==proof['wakeup_id'] and recorded['marker']==admission.marker(p,role)
            and all(r[k]==proof[k] for k in ('task_id','agent_id','wakeup_id','output_sha256','value'))
            and r['execution_id']==proof['request_id'] and r['read_evidence']=={})
    settings=json.loads((b.STATE/'native.json').read_text());runs=admission.native.issue_task_runs(settings,p['issue_id'])
    require({t['id'] for t in runs}=={cto['task_id'],sponsor['task_id']} and all(t['status']=='completed' for t in runs))
    with b.db() as con:
        trial=con.execute('SELECT parent_issue,config FROM test_revision_trials WHERE issue_id=?',(p['issue_id'],)).fetchone()
        require(trial and trial['parent_issue']==cfg['parent_issue_id']
            and json.loads(trial['config'])['literal_maintenance']==dict(source_task=key,config_sha256=digest(cfg)))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='author_feedback_admissions'").fetchone():
            require(not con.execute('SELECT 1 FROM author_feedback_admissions WHERE scope_sha256=?',(digest(p),)).fetchone())
    receipt=dict(operation='recover_literal_feedback_metadata_bound_v1',workflow_key=key,config_sha256=digest(cfg),
        previous_state=s,maintenance_operation=operation,typed_reason_limit=bound,legacy_local_reason_limit=300,
        reason_characters=len(sponsor['value']['reason']),revalidated_authority=dict(cto=cto,sponsor=sponsor),
        legacy_rule_versioned_source_sha256='2d0ed041a725139cc7f30c9c560e917fccee12f6654764543e81a5aaf60872dd',
        source_reset=False,author_retry_authorized=False,native_author_started=False,delivery_approval=False)
    updated=dict(s,stage='prepare',owner=cfg['reviewer'],metadata_bound_recovery=digest(receipt),
        required_action='Resume exact preparation after typed metadata validation; no native decision replay or source retry')
    for field in ('category','last_error'):updated.pop(field,None)
    with b.LOCK,b.db() as con:
        con.execute('BEGIN IMMEDIATE');require(maintenance.current(con)==seal)
        require(json.loads(con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(key,)).fetchone()[0])==s)
        con.execute('INSERT INTO literal_feedback_metadata_recoveries VALUES(?,?)',(key,json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),key))
    return receipt
