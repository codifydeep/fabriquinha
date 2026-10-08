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
             'runs':{'config','state'},'task':{'config','state','task'},
             'revision':{'config','state','review'},'reassess':{'config','state'}}
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
    if operation=='reassess':
        from r3_decision_revision import qualify
        from r3_resume_contract import sha
        if (not state.get('post_experiment') or state.get('resume_contract_reassessment_sha256')
                or set(evidence.get('experiment_history',[]))!={'observe_existing_controller','verify_frozen_delivery','verify_github_ci','verify_local_deployment'}
                or not {'experiment_snapshot_intact','experiment_github_ci_exact_sha','experiment_local_deployment_exact_sha',
                        'experiment_controller_absent'}<=set(evidence['facts'].values())):
            raise ValueError('one reviewed hold after complete distinct passed observations required')
        author=config['cto' if state.get('escalated') else 'techlead']
        proof=qualify(config,state,state['review'],native.task_record(settings,state['diagnosis_task'],author),
                      native.task_record(settings,state['task_id'],target),accepted_decision='retain_hold')
        if proof['proposal']['action']!='retain_hold' or digest(proof['proposal'])!=proof['proposal_sha256']:
            raise ValueError('original reviewed hold required')
        saved=dict(operation='qualified_resume_contract_reassessment_v1',incident_sha256=config['evidence_sha256'],
            issue_id=state['issue_id'],record=proof,policy_sha256=sha(),execution_authorized=False,release_homologated=False)
        key=digest(saved)
        with b.LOCK,b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS r3_resume_reassessments(reassessment_sha256 TEXT PRIMARY KEY,incident_sha256 TEXT UNIQUE,proof TEXT)')
            old=con.execute('SELECT reassessment_sha256,proof FROM r3_resume_reassessments WHERE incident_sha256=?',(config['evidence_sha256'],)).fetchone()
            if old:
                if old[0]!=key or json.loads(old[1])!=saved:raise ValueError('immutable resume policy reassessment changed')
            else:con.execute('INSERT INTO r3_resume_reassessments VALUES(?,?,?)',(key,config['evidence_sha256'],json.dumps(saved,sort_keys=True)))
        return dict(reassessment_sha256=key,proof=saved)
    if operation=='revision':
        from r3_decision_revision import qualify
        author=config['cto' if state.get('escalated') else 'techlead']
        proof=qualify(config,state,body['review'],
            native.task_record(settings,state['diagnosis_task'],author),
            native.task_record(settings,state['task_id'],target))
        key=digest(proof)
        if digest(proof['proposal'])!=proof['proposal_sha256']:raise ValueError('exact proposal hash required')
        saved=dict(operation='independent_incident_revision_v1',incident_sha256=config['evidence_sha256'],
                   issue_id=state['issue_id'],record=proof,execution_authorized=False)
        with b.LOCK,b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS r3_decision_revisions(revision_sha256 TEXT PRIMARY KEY,review_task TEXT UNIQUE,proof TEXT)')
            old=con.execute('SELECT revision_sha256,proof FROM r3_decision_revisions WHERE review_task=?',(state['task_id'],)).fetchone()
            if old:
                if old[0]!=key or json.loads(old[1])!=saved:raise ValueError('immutable incident revision changed')
            else:con.execute('INSERT INTO r3_decision_revisions VALUES(?,?,?)',(key,state['task_id'],json.dumps(saved,sort_keys=True)))
        return dict(revision_sha256=key)
    if operation=='wake':
        note=planning_instruction(config,state)
        if note!=body['note'] or type(body['allow_create']) is not bool or request_contract({'messages':[{'role':'user','content':note}]}) is None:
            raise ValueError('fixed typed incident instruction required')
        marker=digest(dict(incident=config['evidence_sha256'],phase='review' if review else 'diagnose',
                           escalation=state.get('escalated',False),proposal=state.get('proposal_sha256') if review else None))
        if state.get('decision_revision_sha256'):
            key=state['decision_revision_sha256']
            with b.LOCK,b.db() as con:
                row=con.execute('SELECT proof FROM r3_decision_revisions WHERE revision_sha256=?',(key,)).fetchone()
            proof=json.loads(row[0]) if row else {}
            if (proof.get('operation')!='independent_incident_revision_v1'
                    or proof.get('incident_sha256')!=config['evidence_sha256'] or proof.get('issue_id')!=state['issue_id']
                    or proof.get('record')!=(state.get('decision_revisions') or [None])[-1]
                    or digest(proof.get('record'))!=key or proof.get('execution_authorized') is not False):
                raise ValueError('registered independent revision required')
            marker=digest(dict(original_marker=marker,decision_revision_sha256=key))
        if state.get('resume_contract_reassessment_sha256'):
            from r3_resume_contract import POLICY,sha
            key=state['resume_contract_reassessment_sha256']
            with b.LOCK,b.db() as con:
                row=con.execute('SELECT proof FROM r3_resume_reassessments WHERE reassessment_sha256=?',(key,)).fetchone()
            proof=json.loads(row[0]) if row else {}
            if (digest(proof)!=key or proof.get('policy_sha256')!=sha()
                    or proof.get('incident_sha256')!=config['evidence_sha256'] or proof.get('issue_id')!=state['issue_id']
                    or proof.get('execution_authorized') is not False or proof.get('release_homologated') is not False):
                raise ValueError('registered unchanged conditional-resume policy required')
            note+='\nConditional resume contract (not execution evidence): '+POLICY
            marker=digest(dict(original_marker=marker,resume_contract_reassessment_sha256=key))
        elif 'fixed_incident_capability_catalogue_qualified' in evidence.get('facts',{}).values():
            from r3_incident_capabilities import note as capability_note, sha as catalogue_sha
            note+=capability_note()
            if len(note)>3850:raise ValueError('bounded catalogue context required')
            marker=digest(dict(original_marker=marker,capability_catalogue_sha256=catalogue_sha()))
        if state.get('review_transport_recovery_sha256'):
            recovery=state['review_transport_recovery_sha256']
            with b.LOCK,b.db() as con:
                row=con.execute('SELECT proof FROM r3_json_review_recoveries WHERE recovery_sha256=?',(recovery,)).fetchone()
            proof=json.loads(row[0]) if row else {}
            if (digest(proof)!=recovery or not review or proof.get('operation')!='qualified_r3_json_review_recovery_v1'
                    or proof.get('issue_id')!=state['issue_id'] or proof.get('incident_sha256')!=config['evidence_sha256']
                    or proof.get('proposal_sha256')!=state.get('proposal_sha256') or proof.get('reviewer')!=target
                    or proof.get('execution_authorized') is not False or proof.get('release_homologated') is not False):
                raise ValueError('registered exact changed-transport review required')
            marker=digest(dict(original_marker=marker,json_review_recovery_sha256=recovery))
            note+='\nThe previous review had malformed JSON; no decision was accepted. Submit fresh schema-valid arguments only.'
            if len(note)>3850:raise ValueError('bounded recovery review context required')
        if len(note)>3850:raise ValueError('bounded fixed incident context required')
        return native.ensure_planning_start(settings,state['issue_id'],target,evidence['source_task'],marker,note,
                                           allow_create=body['allow_create'])
    if operation=='runs':return native.issue_task_runs(settings,state['issue_id'])
    if state.get('task_id')!=body['task']:raise ValueError('exact selected incident task required')
    task=native.task_record(settings,body['task'],target)
    if (task.get('id')!=body['task'] or task.get('issue_id')!=state['issue_id']
            or task.get('agent_id')!=target or task.get('wakeup_id')!=state.get('wakeup_id')):
        raise ValueError('incident task identity drift')
    return task
