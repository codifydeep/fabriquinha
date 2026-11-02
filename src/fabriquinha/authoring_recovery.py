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


def resume_partial(runtime,request):
    """One assisted native resume of preserved, unfrozen work after job repair.

    Unlike empty-authoring succession, no workspace, graph or counter is reset.
    The CTO hold is context; current operator authority permits a fresh attempt,
    never a delivery approval. A complete test review is still mandatory.
    """
    if not isinstance(request,dict) or set(request)!={'source','diagnosis','job'}:
        raise ValueError('exact source, CTO diagnosis and failed job required')
    pin=environment()
    if not pin and not runtime.project.qualification:raise ValueError('verified installed source required')
    r=runtime.releases;kb,kbc,_=native()
    with Owner(runtime.root),runtime.control.lock(),runtime.intake.lock(),kbc.connect_closing() as conn:
        state=runtime.control.read()
        if state.get('error') or not state['paused'] or not runtime.pause_status(conn)['drained']:
            raise ValueError('drained maintenance pause required')
        task=kb.get_task(conn,request['source'])
        if not task:raise ValueError('source missing')
        body=json.loads(task.body);latest=kb.latest_run(conn,task.id)
        path=r.store.root/'operations'/('partial-authoring-'+task.id+'.json')
        if path.exists():
            result=json.loads(path.read_bytes());record=r.store.receipt(result['receipt'],kind='partial_authoring_resume')
            if record['payload']['request']!=request or record['binding']['contract']!=digest(body):raise ValueError('resume scope drift')
            if not latest or latest.id!=record['binding']['number'] or task.status!='triage':return result
            anchor=kb.get_task(conn,body.get('release_anchor'))
            if (r.store.capture(task.workspace_path)!=record['payload']['snapshot'] or not anchor
                    or json.loads(r.graph_path(anchor,body).read_bytes())['receipt']!=record['payload']['graph']):
                raise ValueError('partial work or graph changed before native resume')
        else:
            if (body.get('kind')!='tests' or task.status!='triage' or not latest or not latest.ended_at
                    or runtime.recovery.expired_effects(task.id)):raise ValueError('settled tests author triage required')
            decision=r.store.receipt(request['diagnosis'],kind='diagnostic_decision');d=decision['payload'];scope=decision['binding']
            incident=r.store.receipt(d['incident'],kind='incident');origin=incident['binding'];facts=incident['payload']
            diagnostic=kb.get_task(conn,scope['task']);closed=kb.latest_run(conn,scope['task'])
            snapshot=r.store.capture(task.workspace_path)
            if (origin['task']!=task.id or origin['number']!=latest.id or origin['contract']!=digest(body)
                    or origin['kind']!='tests' or origin['reviewing'] is not False
                    or facts['snapshot']!=snapshot or facts['source_state']!='triage' or facts['controller_effects']!=[]
                    or d['project']!=r.project.fingerprint() or d['action']!='hold' or d['delivery_approval'] is not False
                    or scope['actor']!=r.project.technical_roles['cto'] or scope['release']!=body['release']
                    or not diagnostic or diagnostic.status!='done' or not closed or closed.id!=scope['number']
                    or (closed.metadata or {}).get('diagnosis')!=request['diagnosis']):raise ValueError('exact current CTO hold and partial snapshot required')
            from .recovery import suite_refusal_context
            job=suite_refusal_context(r.store,r.project,origin,request['job'],snapshot)
            raw=r.store.receipt(request['job'],kind='suite_job')['payload']
            if (not job['matches_current_snapshot'] or job.get('infrastructure_error')!='validation job exceeded its persistent runtime'
                    or raw['identity'].get('diagnostic_trace')
                    or raw['identity'].get('validation_bundle')!=validation_files(r.project,r.store)[0]):
                raise ValueError('pre-repair timeout on unchanged pinned candidate required')
            baseline=runtime.recovery.input(conn,task,'baseline')
            left=r.store.manifest(baseline);right=r.store.manifest(snapshot)
            if (left==right or any(right.get(p)!=v for p,v in left.items())
                    or any(not p.startswith(r.project.tests_dir+'/') for p in right.keys()-left.keys())):
                raise ValueError('additive partial tests with intact product and baseline required')
            for file in (r.store.root/'receipts').glob('*.json'):
                record=json.loads(file.read_bytes())
                if record.get('binding',{}).get('task')==task.id and record.get('kind') in ('red','test_review','tests_frozen'):
                    raise ValueError('existing handoff requires independent review recovery')
            anchor=kb.get_task(conn,body.get('release_anchor'))
            if not anchor or anchor.status!='blocked' or runtime.intake.terminal(anchor):raise ValueError('active release required')
            graph_key=json.loads(r.graph_path(anchor,body).read_bytes())['receipt']
            graph=r.store.receipt(graph_key,kind='release_graph')
            if not graph['payload'].get('assisted'):raise ValueError('assisted release required')
            found=False
            for item in graph['payload']['items']:
                for phase in ('tests','implementation','integration'):
                    card=item['cards'][phase]
                    current=r.check_card(conn,card)
                    if current.id==task.id:found=True
                    elif found and kb.latest_run(conn,current.id):raise ValueError('downstream execution forbids resume')
                    elif not found and current.status!='done':raise ValueError('completed prefix required')
            if not found:raise ValueError('current graph membership required')
            receipt=r.store.record('partial_authoring_resume',origin,dict(project=r.project.fingerprint(),
                request=request,baseline=baseline,snapshot=snapshot,source_pin=pin,graph=graph_key,
                assisted=True,delivery_approval=False,independent_review_required=True,
                authority='Owner authorized timeout diagnostics repair and continuation of unfrozen partial tests'))
            result=dict(receipt=receipt,assisted=True,delivery_approval=False);write_json(path,result)
        if not kb.specify_triage_task(conn,task.id,author='controller'):raise ValueError('native triage transition refused')
        return result

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
