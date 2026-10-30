"""One clean deployed-QA successor; preserve the approved delivery and history."""
import json
from .artifacts import digest
from .board import Run
from .effects import write_json,EffectBlocked
from .kanban_lane import native
from .recovery import Recovery,browser_refusal_context


def empty_state_failure(report):
    """Recognize only the qualified single EMPTY_LIST precondition failure."""
    import ast
    if not isinstance(report,dict) or report.get('status')!='failed' or report.get('failure_kind')!='behavior':return False
    errors=report.get('errors');prefix='full acceptance suite failed, skipped or did not run completely: '
    if not isinstance(errors,list) or len(errors)!=1 or not isinstance(errors[0],str) or not errors[0].startswith(prefix):return False
    if len(errors[0])>65536:return False
    try:failures=ast.literal_eval(errors[0][len(prefix):])
    except (ValueError,SyntaxError,RecursionError):return False
    case='acceptance_a_empty_list.EmptyList.test_home_shows_empty_state_when_no_waiting_rooms'
    return (isinstance(failures,list) and len(failures)==1 and isinstance(failures[0],str)
        and failures[0].startswith(case+':') and case in report.get('cases',[])
        and 'AssertionError' in failures[0] and 'EMPTY_LIST must observe a fresh app with no rooms' in failures[0])


def origin(project,store,run):
    kb,api,_=native()
    with api.connect_closing() as conn:task=kb.get_task(conn,run.task)
    body=json.loads(task.body or '{}') if task else {}
    key=body.get('inputs',{}).get('qa_recovery')
    if not key:return run
    admission=store.receipt(key,kind='qa_recovery');data=admission['payload']
    source=Run(**data['source_binding'])
    if (digest(body)!=run.contract or data['project']!=project.fingerprint()
            or run.kind!='integration' or run.reviewing is not True or run.actor==run.author
            or run.release!=source.release or run.author!=source.author or run.task==source.task
            or admission['binding']['release']!=run.release or source.kind!='integration' or source.reviewing is not True
            or admission['binding']['actor']!='controller' or run.actor not in project.reviewers_for(run.author)):raise ValueError('exact independent QA successor required')
    return source


def receipt_origin(project,store,record):
    key=record['payload'].get('qa_recovery')
    if not key:return record['binding']
    admission=store.receipt(key,kind='qa_recovery');data=admission['payload'];scope=record['binding'];source=data['source_binding']
    if (data['project']!=project.fingerprint() or admission['binding']['actor']!='controller'
            or scope['release']!=source['release'] or admission['binding']['release']!=scope['release'] or scope['author']!=source['author']
            or scope['kind']!='integration' or scope['reviewing'] is not True or scope['actor']==scope['author']
            or scope['actor'] not in project.reviewers_for(scope['author'])
            or record['payload']['rollout']!=data['rollout'] or record['payload']['artifact']!=data['artifact']):
        raise ValueError('exact recovered QA evidence required')
    return {**source,'actor':scope['actor']}


def reconcile(r,conn,anchor,graph):
    kb,_,_=native();path=r.folder(anchor)/'qa-recovery.json'
    if path.exists():
        key=json.loads(path.read_bytes())['receipt'];record=r.store.receipt(key,kind='release_graph')
        if record['binding']!=r.binding(anchor):raise ValueError('QA recovery graph scope changed')
        result=record['payload'];item=result['items'][-1];card=item['cards']['integration']
        publish(r,conn,card)
        return result
    item=graph['items'][-1];card=item['cards']['integration'];source=r.check_card(conn,card)
    if source.status!='triage':return graph
    latest=kb.latest_run(conn,source.id)
    if not latest or not latest.ended_at:return graph
    recovery=Recovery(r.project,r.store,r.board)
    decisions=[]
    for task in recovery.cards(conn):
        body=json.loads(task.body or '{}')
        if task.status!='done' or body.get('source')!=source.id or body.get('source_run')!=latest.id or body.get('stage')!='cto':continue
        row=kb.latest_run(conn,task.id);key=(row.metadata or {}).get('diagnosis') if row else None
        if not key:continue
        decision=r.store.receipt(key,kind='diagnostic_decision');d=decision['payload']
        if d.get('action')!='hold' or not d.get('experiment'):continue
        incident=r.store.receipt(d['incident'],kind='incident')
        job=incident['payload'].get('browser_refusal')
        if not job:continue
        facts=browser_refusal_context(r.store,r.project,incident['binding'],job)
        if facts['infrastructure_error'] or not empty_state_failure(facts.get('report')):continue
        if (decision['binding']['actor']!=r.project.technical_roles['cto'] or decision['binding']['number']!=row.id
                or decision['binding']['contract']!=digest(body) or row.outcome!='completed'
                or incident['binding']['task']!=source.id or incident['binding']['number']!=latest.id
                or incident['binding']['contract']!=digest(json.loads(source.body))):raise ValueError('exact completed CTO QA hold required')
        decisions.append((key,incident,task.id))
    if not decisions:return graph
    if len(decisions)!=1:raise ValueError('one settled QA diagnosis required')
    if conn.execute('SELECT count(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]:return graph
    if recovery.expired_effects(source.id):raise EffectBlocked('settle QA effects before succession')
    decision,incident,diagnostic=decisions[0]
    event,handoff=recovery.handoff(conn,source)
    if not handoff.get('rollout'):raise ValueError('original rollout handoff required')
    rollout=r.store.receipt(handoff['rollout'],kind='rollout');artifact=r.store.receipt(rollout['payload']['candidate'],kind='artifact')
    scope=incident['binding'];data=artifact['payload']
    if (rollout['binding']['task']!=source.id or rollout['binding']['contract']!=scope['contract']
            or rollout['binding']['actor']!=card['owner'] or scope['reviewing'] is not True
            or data['project']!=r.project.fingerprint() or data['snapshot']!=incident['payload']['snapshot']):
        raise ValueError('exact retained candidate required')
    delivery,_,_=r.closed(item['cards']['implementation']['id'],'delivery','delivery_review')
    if data['review']!=delivery:raise ValueError('unchanged independent delivery required')
    for plan in conn.execute('SELECT id,body FROM tasks'):
        if json.loads(plan['body'] or '{}').get('repair_of')==source.id:
            t=kb.get_task(conn,plan['id'])
            if t.status not in ('triage','blocked'):raise EffectBlocked('settle competing corrective plan first')
    admission=r.store.record('qa_recovery',r.binding(anchor),dict(project=r.project.fingerprint(),
        source_binding=scope,diagnosis=decision,rollout=handoff['rollout'],artifact=rollout['payload']['candidate'],
        metadata=handoff,delivery_approval=False,reason='fresh-instance QA with independently frozen maintenance preflight'))
    body={**card['body'],'qa_recovery_graph':True,'inputs':{**card['body']['inputs'],'qa_recovery':admission}}
    parents=list(dict.fromkeys([*card['parents'],diagnostic]));workspace=r.store.root.parent/'work'/scope['release']/('qa-'+admission)/'integration'
    workspace.mkdir(parents=True,exist_ok=True,mode=0o777);workspace.chmod(0o777)
    if r.board.guard:r.board.guard()
    ident=kb.create_task(conn,title='QA CLEAN '+source.title,body=json.dumps(body),assignee=card['owner'],parents=parents,
        workspace_kind='dir',workspace_path=str(workspace),completion_contract=card['completion_contract'],initial_status='blocked',
        max_retries=2,max_runtime_seconds=600,idempotency_key=digest([scope['release'],source.id,latest.id,'qa-clean-v1']))
    successor={**card,'id':ident,'body':body,'parents':parents,'workspace':str(workspace)}
    result={**graph,'items':[*graph['items'][:-1],{**item,'cards':{**item['cards'],'integration':successor}}],
        'qa_recovery':admission,'previous_graph':r.store.record('release_graph',r.binding(anchor),graph)}
    key=r.store.record('release_graph',r.binding(anchor),result);write_json(path,{'receipt':key})
    publish(r,conn,successor)
    return result


def publish(r,conn,card):
    kb,_,_=native();task=r.check_card(conn,card);key=card['body']['inputs']['qa_recovery']
    record=r.store.receipt(key,kind='qa_recovery');metadata={**record['payload']['metadata'],'qa_recovery':key,'transfer_only':True}
    row=conn.execute("SELECT r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id LIMIT 1",(task.id,)).fetchone()
    if row:
        if json.loads(row[0])!=metadata:raise ValueError('QA handoff transfer drift')
        return
    if kb.latest_run(conn,task.id):raise EffectBlocked('unrelated successor activity')
    if r.board.guard:r.board.guard()
    if task.status=='blocked' and not kb.unblock_task(conn,task.id):raise ValueError('QA activation refused')
    if not kb.request_review(conn,task.id,reviewer=r.project.reviewer(card['owner']),
            summary='Retained rollout transferred for independent clean-instance QA; no new implementation',metadata=metadata):
        raise EffectBlocked('QA dependencies not satisfied')
