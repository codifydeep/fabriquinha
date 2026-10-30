"""One fenced maintenance replan; native roles and immutable predecessor evidence."""
import json
from .artifacts import digest
from .effects import write_json,EffectBlocked
from .maintenance import reviewed,authorization
from .recovery import Recovery
from .kanban_lane import native


def admit(runtime,value):
    if not isinstance(value,dict) or set(value)!={'release','diagnosis'}:
        raise ValueError('exact release and CTO diagnosis required')
    r=runtime.releases;kb,api,_=native()
    with runtime.intake.lock(),api.connect_closing() as conn:
        anchor=kb.get_task(conn,value['release'])
        if not anchor or anchor.status!='blocked':raise ValueError('active maintenance root required')
        body=json.loads(anchor.body);authority=body.get('maintenance')
        authorization(r.project,r.store,authority)
        if conn.execute('SELECT count(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]:
            raise ValueError('settle all workers before replan')
        path=r.folder(anchor)/'maintenance-replan.json'
        if path.exists():
            state=json.loads(path.read_bytes())
            if state['diagnosis']!=value['diagnosis']:raise ValueError('one exact maintenance replan only')
            return state
        old_key=json.loads((r.folder(anchor)/'graph.json').read_bytes())['receipt']
        record=r.store.receipt(old_key,kind='release_graph');graph=record['payload']
        if record['binding']!=r.binding(anchor) or len(graph['items'])!=1:
            raise ValueError('exact single-package maintenance graph required')
        reviewed(r.project,r.store,graph['plan_review'])
        item=graph['items'][0];source=kb.get_task(conn,item['cards']['tests']['id'])
        for card in item['cards'].values():r.check_card(conn,card)
        latest=kb.latest_run(conn,source.id)
        if source.status!='triage' or not latest or not latest.ended_at:
            raise ValueError('settled held tests author required')
        if Recovery(r.project,r.store,r.board).expired_effects(source.id):
            raise EffectBlocked('settle source effects before replan')
        for phase in ('implementation','integration'):
            if kb.latest_run(conn,item['cards'][phase]['id']):raise ValueError('no downstream execution allowed')
        decision=r.store.receipt(value['diagnosis'],kind='diagnostic_decision')
        d=decision['payload'];scope=decision['binding']
        incident=r.store.receipt(d['incident'],kind='incident')
        task=kb.get_task(conn,scope['task']);closed=kb.latest_run(conn,scope['task'])
        if (d['project']!=r.project.fingerprint() or d['action']!='hold' or not d.get('experiment')
                or scope['actor']!=r.project.technical_roles['cto'] or scope['release']!=body['release']
                or not task or task.status!='done' or not closed or closed.id!=scope['number']
                or closed.outcome!='completed' or (closed.metadata or {}).get('diagnosis')!=value['diagnosis']
                or scope['contract']!=digest(json.loads(task.body))
                or incident['binding']['task']!=source.id or incident['binding']['number']!=latest.id
                or incident['binding']['reviewing'] is not False
                or incident['binding']['contract']!=digest(json.loads(source.body))
                or incident['payload']['snapshot']!=r.store.capture(source.workspace_path)):
            raise ValueError('exact settled CTO hold and unchanged source required')
        state=dict(project=r.project.fingerprint(),release=anchor.id,diagnosis=value['diagnosis'],
            prior_graph=old_key,prior_review=graph['plan_review'],authority=authority,
            source=source.id,source_run=latest.id,delivery_approval=False)
        permission=r.store.record('maintenance_replan_authorization',r.binding(anchor),state)
        plan_body=dict(version=1,kind='plan',release=body['release'],anchor=anchor.id,
            inputs=dict(approved_brief=authority),maintenance_replan=permission)
        identity=digest([body['release'],old_key,'maintenance-replan'])
        if r.board.guard:r.board.guard()
        plan=kb.create_task(conn,title='REPLAN '+body['request']['label'],body=json.dumps(plan_body),
            assignee=r.project.coordination_roles['lead'],workspace_kind='scratch',
            parents=[scope['task']],completion_contract='local-only',max_retries=2,max_runtime_seconds=600,
            idempotency_key=identity)
        if json.loads(kb.get_task(conn,plan).body)!=plan_body:raise ValueError('replan contract drift')
        state.update(plan=plan,authorization=permission)
        write_json(path,state)
        return state


def selection(r,conn,anchor):
    path=r.folder(anchor)/'maintenance-replan.json'
    if not path.exists():return None
    state=json.loads(path.read_bytes());kb,_,_=native()
    receipt=r.store.receipt(state['authorization'],kind='maintenance_replan_authorization')
    expected={k:v for k,v in state.items() if k not in ('plan','authorization')}
    if receipt['binding']!=r.binding(anchor) or receipt['payload']!=expected:
        raise ValueError('maintenance replan pointer drift')
    task=kb.get_task(conn,state['plan'])
    if (not task or json.loads(task.body).get('maintenance_replan')!=state['authorization']
            or json.loads(task.body).get('inputs')!={'approved_brief':state['authority']}):
        raise ValueError('exact native maintenance successor plan required')
    return state


def plan_scope(document,paths):
    tasks=document.get('tasks',[])
    if len(tasks)!=1 or any(path not in tasks[0].get('acceptance','') for path in paths):
        raise ValueError('one package must explicitly name every authorized test path; independent semantic review remains required')
