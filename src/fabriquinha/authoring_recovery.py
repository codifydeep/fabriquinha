"""Operator maintenance after an empty, incomplete test-authoring activity.

Not an agent retry tool. Preserve the failed graph and create one successor tail
under the same reviewed plan, baseline and validators. No freeze is inherited.
"""
import json
from .artifacts import digest
from .effects import write_json
from .kanban_lane import native
from .runtime import Owner
from .repairs import held_incident,protocol_failure
from .source import environment
from .executor import validation_files

PROTOCOL='empty-test-authoring-recovery-1'


def eligible(project,store,incident,decision,body,baseline,snapshot):
    record,_=held_incident(project,store,incident,decision,snapshot)
    scope=record['binding'];data=record['payload']
    if (scope['kind']!='tests' or scope['reviewing'] is not False
            or scope['contract']!=digest(body) or body.get('kind')!='tests'
            or body.get('authoring_repair') or protocol_failure(data) is None
            or snapshot!=baseline):
        raise ValueError('unchanged baseline and incomplete pre-freeze test authoring required')
    return record


def admit(runtime,request):
    if not isinstance(request,dict) or set(request)!={'source','diagnosis','graph'}:
        raise ValueError('exact source, CTO diagnosis and current graph required')
    source_pin=environment()
    if not source_pin and not runtime.project.qualification:raise ValueError('verified installed source required')
    root=runtime.root;r=runtime.releases;kb,kbc,_=native()
    with Owner(root),runtime.control.lock(),runtime.intake.lock(),kbc.connect_closing() as conn:
        state=runtime.control.read()
        if state.get('error') or not state['paused'] or not runtime.pause_status(conn)['drained']:
            raise ValueError('valid drained maintenance pause required')
        source=kb.get_task(conn,request['source'])
        if not source:raise ValueError('source missing')
        body=json.loads(source.body);anchor=kb.get_task(conn,body.get('release_anchor'))
        if not anchor or anchor.status!='blocked' or runtime.intake.terminal(anchor):raise ValueError('active release required')
        path=r.folder(anchor)/'authoring-recovery.json';graph_path=r.folder(anchor)/'graph.json'
        if path.exists():
            saved=json.loads(path.read_bytes());proof=r.store.receipt(saved['admission'],kind='authoring_recovery')
            if proof['payload']['request']!=request or proof['binding']!=r.binding(anchor):raise ValueError('recovery already scoped elsewhere')
            current=json.loads(graph_path.read_bytes())['receipt']
            if current not in (request['graph'],saved['graph']):raise ValueError('recovered graph advanced; do not replay')
            recovered=r.store.receipt(saved['graph'],kind='release_graph')
            if recovered['binding']!=r.binding(anchor) or recovered['payload'].get('authoring_repair')!=saved['admission']:
                raise ValueError('recovery graph identity changed')
            for item in recovered['payload']['items']:
                for card in item['cards'].values():r.check_card(conn,card)
            if current==request['graph']:write_json(graph_path,{'receipt':saved['graph']})
            return dict(**saved,assisted=True,delivery_approval=False)
        current=json.loads(graph_path.read_bytes())['receipt']
        record=r.store.receipt(current,kind='release_graph');graph=record['payload']
        if (current!=request['graph'] or record['binding']!=r.binding(anchor)
                or graph.get('authoring_repair') or graph.get('continuation_review')
                or graph.get('validation_bundle')!=validation_files(runtime.project,r.store)[0]):
            raise ValueError('unchanged original graph and validator required')
        spec=r.specification(conn,anchor)
        if not spec or spec['review']!=graph['plan_review']:raise ValueError('same approved plan required')
        index=next((n for n,i in enumerate(graph['items']) if i['cards']['tests']['id']==source.id),None)
        latest=kb.latest_run(conn,source.id)
        if index is None or source.status!='triage' or not latest or not latest.ended_at:raise ValueError('settled current test triage required')
        diagnosis=r.store.receipt(request['diagnosis'],kind='diagnostic_decision')
        dt=kb.get_task(conn,diagnosis['binding']['task']);dr=kb.latest_run(conn,dt.id) if dt else None
        if not dt or dt.status!='done' or not dr or (dr.metadata or {}).get('diagnosis')!=request['diagnosis']:
            raise ValueError('current completed CTO diagnosis required')
        incident=diagnosis['payload']['incident'];snapshot=r.store.capture(source.workspace_path)
        baseline=runtime.recovery.input(conn,source,'baseline')
        failure=eligible(runtime.project,r.store,incident,request['diagnosis'],body,baseline,snapshot)
        if failure['binding']['task']!=source.id or failure['binding']['number']!=latest.id:raise ValueError('stale source incident')
        for item_index,item in enumerate(graph['items']):
            for card in item['cards'].values():
                task=r.check_card(conn,card);run=kb.latest_run(conn,task.id)
                if item_index<index:
                    if task.status!='done':raise ValueError('completed prefix required')
                elif task.id!=source.id and (run or task.status not in ('todo','ready','blocked')):
                    raise ValueError('downstream execution forbids replacement')
        for file in (r.store.root/'receipts').glob('*.json'):
            receipt=json.loads(file.read_bytes())
            if receipt.get('binding',{}).get('task')==source.id and receipt.get('kind') in ('red','test_review','tests_frozen'):
                raise ValueError('submitted test evidence requires its own review path')
        admission=r.store.record('authoring_recovery',r.binding(anchor),dict(protocol=PROTOCOL,
            project=runtime.project.fingerprint(),request=request,incident=incident,baseline=baseline,
            source_snapshot=snapshot,source_run=latest.id,source_pin=source_pin,
            assisted=True,delivery_approval=False,prior_diagnosis_is_not_authorization=True))
        mapping={};items=list(graph['items'][:index]);retired=[]
        for item in graph['items'][index:]:
            cards={}
            for phase in ('tests','implementation','integration'):
                old=item['cards'][phase];new=json.loads(json.dumps(old['body']));new['authoring_repair']=admission
                for key,value in new['inputs'].items():
                    if value.startswith('parent:'):
                        _,parent,field=value.split(':',2);new['inputs'][key]='parent:'+mapping.get(parent,parent)+':'+field
                parents=[mapping.get(p,p) for p in old['parents']]
                workspace=root/'work'/r.binding(anchor)['release']/('authoring-'+admission)/item['package']['id']/phase
                workspace.mkdir(mode=0o777,parents=True,exist_ok=True);workspace.chmod(0o777)
                if any(workspace.iterdir()):raise ValueError('successor workspace must remain empty before admission')
                ident=kb.create_task(conn,title=phase.upper()+' '+item['package']['title'],body=json.dumps(new),
                    assignee=old['owner'],parents=parents,workspace_kind='dir',workspace_path=str(workspace),
                    completion_contract=old['completion_contract'],initial_status='blocked',max_retries=2,max_runtime_seconds=600,
                    idempotency_key=digest([admission,item['package']['id'],phase]))
                mapping[old['id']]=ident;retired.append(old['id'])
                cards[phase]=dict(old,id=ident,body=new,parents=parents,workspace=str(workspace))
            items.append(dict(item,cards=cards))
        updated=dict(graph,items=items,previous_graph=current,authoring_repair=admission,
            assisted=True,platform_repair=admission,superseded_cards=sorted(set(graph.get('superseded_cards',[]))|set(retired)))
        key=r.store.record('release_graph',r.binding(anchor),updated)
        for item in updated['items']:
            for card in item['cards'].values():r.check_card(conn,card)
        conn.commit()  # Parked native cards must be durable before publishing either pointer.
        # Intent precedes publication; retries can complete only the exact recorded transition.
        write_json(path,dict(admission=admission,graph=key))
        write_json(graph_path,{'receipt':key})
        conn.commit()
        return dict(admission=admission,graph=key,assisted=True,delivery_approval=False)
