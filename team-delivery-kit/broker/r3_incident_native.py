"""Fixed planning-only native adapter. No shell, edits, merge or restart API."""
import hashlib
import json
from r3_incident_contract import planning_instruction, request_contract
try:
    import native, handoff_runtime
    from incremental_provisioning import NativeIssues
except ImportError:
    from broker import native, handoff_runtime
    from broker.incremental_provisioning import NativeIssues


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def binding(b,settings,evidence):
    with b.LOCK,b.db() as con:
        row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',
                        (evidence['source_task'],)).fetchone()
        if not row:raise ValueError('registered recovery source required')
        contract,state=json.loads(row[0]),json.loads(row[1])
        if (contract.get('source_task')!=evidence['source_task'] or contract.get('root_issue')!=evidence['root_issue']
                or contract.get('original_depth')!=2 or contract.get('release_homologated') is not False):
            raise ValueError('exact original technical recovery required')
        issue=state.get('steps',{}).get('R2',{}).get('issue_id')
        route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone() if issue else None
        if not route:raise ValueError('registered R2 technical roles required')
        route=json.loads(route[0]);actors={k:route[k] for k in ('techlead','cto')}
        if (actors['techlead']==actors['cto'] or any(settings['agents'].get(a)!='planning' for a in actors.values())):
            raise ValueError('independent planning-only technical roles required')
        return actors


def request(operation,body,*,broker=None,settings=None):
    if broker is None:
        import broker as broker
    b=broker
    settings=settings or json.loads((b.STATE/'native.json').read_text())
    if operation=='remaining':
        if body!={}:raise ValueError('fixed budget query required')
        return handoff_runtime.Effects(b,settings).remaining_calls()
    if operation=='binding':
        if set(body)!={'evidence'}:raise ValueError('exact binding query required')
        return binding(b,settings,body['evidence'])
    allowed={'issue':{'config','allow_create'},'wake':{'config','state','note','allow_create'},
             'runs':{'config','state'},'task':{'config','state','task'}}
    if operation not in allowed or set(body)!=allowed[operation]:raise ValueError('fixed R3 planning operation required')
    config=body['config'];evidence=config['evidence']
    if (set(config)!={'evidence','evidence_sha256','techlead','cto'}
            or config['evidence_sha256']!=digest(evidence)
            or {k:config[k] for k in ('techlead','cto')}!=binding(b,settings,evidence)
            or evidence.get('execution_authorized') is not False or evidence.get('release_homologated') is not False):
        raise ValueError('unchanged nonauthorizing technical incident required')
    issues=NativeIssues(settings)
    if operation=='issue':
        if type(body['allow_create']) is not bool:raise ValueError('exact create flag required')
        parent=issues.request('/issues/'+evidence['root_issue'])
        if parent.get('id')!=evidence['root_issue'] or parent.get('status') in ('done','cancelled'):
            raise ValueError('active original incident parent required')
        return issues.ensure(dict(title='R3 publication incident '+config['evidence_sha256'][:16],
            description='Planning-only technical incident '+config['evidence_sha256']+
                '\nSource: '+evidence['source_task']+'\nFacts: '+json.dumps(evidence['facts'],sort_keys=True)+
                '\nTech Lead diagnosis; independent CTO review. No editing, restart, merge or homologation authority.',
            parent_issue_id=evidence['root_issue'],project_id=parent.get('project_id'),stage=3,status='todo'),
            allow_create=body['allow_create'])
    state=body['state'];review=state['stage'] in ('observe_review','awaiting_review')
    if state['stage'] not in ('observe_diagnose','observe_review','awaiting_diagnose','awaiting_review'):
        raise ValueError('current exact planning phase required')
    item=issues.request('/issues/'+state['issue_id'])
    if (item.get('id')!=state['issue_id'] or item.get('parent_issue_id')!=evidence['root_issue']
            or item.get('title')!='R3 publication incident '+config['evidence_sha256'][:16]
            or item.get('stage')!=3 or item.get('status') in ('done','cancelled')):
        raise ValueError('exact live technical incident issue required')
    target=config[('techlead' if review else 'cto') if state.get('escalated') else ('cto' if review else 'techlead')]
    if operation=='wake':
        note=planning_instruction(config,state)
        if note!=body['note'] or type(body['allow_create']) is not bool or request_contract({'messages':[{'role':'user','content':note}]}) is None:
            raise ValueError('fixed typed incident instruction required')
        marker=digest(dict(incident=config['evidence_sha256'],phase='review' if review else 'diagnose',
                           escalation=state.get('escalated',False),proposal=state.get('proposal_sha256') if review else None))
        if 'fixed_incident_capability_catalogue_qualified' in evidence.get('facts',{}).values():
            from r3_incident_capabilities import note as capability_note, sha as catalogue_sha
            note+=capability_note()
            if len(note)>3850:raise ValueError('bounded catalogue context required')
            marker=digest(dict(original_marker=marker,capability_catalogue_sha256=catalogue_sha()))
        return native.ensure_planning_start(settings,state['issue_id'],target,evidence['source_task'],marker,note,
                                           allow_create=body['allow_create'])
    if operation=='runs':return native.issue_task_runs(settings,state['issue_id'])
    if state.get('task_id')!=body['task']:raise ValueError('exact selected incident task required')
    task=native.task_record(settings,body['task'],target)
    if (task.get('id')!=body['task'] or task.get('issue_id')!=state['issue_id']
            or task.get('agent_id')!=target or task.get('wakeup_id')!=state.get('wakeup_id')):
        raise ValueError('incident task identity drift')
    return task
