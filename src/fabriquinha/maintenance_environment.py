"""Bounded succession after the pinned read-only harness becomes accessible."""
import json
from .artifacts import digest
from .effects import write_json,EffectBlocked
from .executor import validation_files
from .kanban_lane import native
from .maintenance import reviewed
from .recovery import Recovery


def selection(r,anchor):
    path=r.folder(anchor)/'maintenance-environment.json'
    if not path.exists():return None
    key=json.loads(path.read_bytes())['receipt']
    record=r.store.receipt(key,kind='maintenance_environment')
    if record['binding']!=r.binding(anchor):raise ValueError('exact maintenance environment admission required')
    bundle,files=validation_files(r.project,r.store)
    if record['payload']['bundle']!=bundle or record['payload']['browser']!=str(files['browser.py'].resolve()):
        raise ValueError('maintenance environment pin changed')
    return key,record['payload']


def admit(runtime,value):
    if not isinstance(value,dict) or set(value)!={'release','diagnosis'}:raise ValueError('exact release and diagnosis required')
    r=runtime.releases;kb,api,_=native()
    with runtime.intake.lock(),api.connect_closing() as conn:
        anchor=kb.get_task(conn,value['release'])
        if not anchor or anchor.status!='blocked' or not json.loads(anchor.body).get('maintenance'):
            raise ValueError('active scoped maintenance required')
        if conn.execute('SELECT count(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]:
            raise ValueError('settle workers before environment succession')
        existing=selection(r,anchor)
        if existing:
            if existing[1]['diagnosis']!=value['diagnosis']:raise ValueError('one environment succession only')
            return {'receipt':existing[0],'delivery_approval':False}
        spec=r.specification(conn,anchor)
        if not spec or not spec.get('maintenance_replan'):raise ValueError('independently corrected maintenance plan required')
        reviewed(r.project,r.store,spec['review'])
        path=r.folder(anchor)/('maintenance-graph-'+spec['task']+'.json')
        prior=json.loads(path.read_bytes())['receipt'];graph_record=r.store.receipt(prior,kind='release_graph');graph=graph_record['payload']
        if graph_record['binding']!=r.binding(anchor) or graph['plan_review']!=spec['review'] or len(graph['items'])!=1:
            raise ValueError('exact current maintenance graph required')
        item=graph['items'][0]
        for card in item['cards'].values():r.check_card(conn,card)
        source=kb.get_task(conn,item['cards']['tests']['id']);latest=kb.latest_run(conn,source.id)
        if source.status!='triage' or not latest or not latest.ended_at:raise ValueError('settled tests triage required')
        for phase in ('implementation','integration'):
            if kb.latest_run(conn,item['cards'][phase]['id']):raise ValueError('downstream work already exists')
        if Recovery(r.project,r.store,r.board).expired_effects(source.id):raise EffectBlocked('settle source effects')
        decision=r.store.receipt(value['diagnosis'],kind='diagnostic_decision');d=decision['payload'];scope=decision['binding']
        incident=r.store.receipt(d['incident'],kind='incident');task=kb.get_task(conn,scope['task']);closed=kb.latest_run(conn,scope['task'])
        if (d['project']!=r.project.fingerprint() or d['action']!='hold' or not d.get('experiment')
                or scope['actor']!=r.project.technical_roles['cto'] or scope['release']!=json.loads(anchor.body)['release']
                or not task or task.status!='done' or not closed or closed.id!=scope['number'] or closed.outcome!='completed'
                or (closed.metadata or {}).get('diagnosis')!=value['diagnosis'] or scope['contract']!=digest(json.loads(task.body))
                or incident['binding']['task']!=source.id or incident['binding']['number']!=latest.id
                or incident['binding']['reviewing'] is not False or incident['binding']['contract']!=digest(json.loads(source.body))
                or incident['payload']['snapshot']!=r.store.capture(source.workspace_path)):
            raise ValueError('exact CTO hold and unchanged author required')
        # Prove the failed worker did not already have the mount: no repeat of
        # the same precondition, no prompt-only assertion that it was corrected.
        intents=[]
        for f in (r.store.root/'agents').glob('*/sandbox.json'):
            observed=json.loads(f.read_bytes());intent=observed.get('identity',{})
            if intent.get('binding')==incident['binding']:
                if f.parent.name!=digest(intent) or intent.get('project')!=r.project.fingerprint() or intent.get('image')!=r.project.validation_image:
                    raise ValueError('historical sandbox identity drift')
                if any(m.get('Destination')=='/opt/fabriquinha/browser.py' for m in observed.get('mounts',[]) if isinstance(m,dict)):
                    raise ValueError('harness was already mounted')
                intents.append(intent)
        if len(intents)!=1 or 'validation_browser' in intents[0]:raise ValueError('exact historical missing mount required')
        bundle,files=validation_files(r.project,r.store)
        if not bundle:raise ValueError('pinned browser validator required')
        from .hermes import command
        expected={**intents[0],'validation_browser':str(files['browser.py'].resolve())}
        args=command(r.project,expected)
        mount='type=bind,src='+expected['validation_browser']+',dst=/opt/fabriquinha/browser.py,readonly'
        if mount not in args:raise ValueError('installed command must provide readonly harness')
        record=r.store.record('maintenance_environment',r.binding(anchor),dict(project=r.project.fingerprint(),
            diagnosis=value['diagnosis'],prior_graph=prior,review=spec['review'],source=source.id,source_run=latest.id,
            bundle=bundle,browser=expected['validation_browser'],previous_intent=digest(intents[0]),delivery_approval=False))
        write_json(r.folder(anchor)/'maintenance-environment.json',{'receipt':record})
        return {'receipt':record,'delivery_approval':False}
