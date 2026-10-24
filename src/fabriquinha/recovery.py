"""Executable technical diagnostics as native Kanban cards, not another workflow DB."""
import json
from pathlib import Path
from .artifacts import digest
from .board import Run
from .effects import Journal, EffectBlocked, Pending
from .kanban_lane import native
from .quality import DeliveryTools, product_mutations, review_decision


class Diagnostic:
    def __init__(self,sandbox,quality):
        self.sandbox,self.q,self.run=sandbox,quality,sandbox.run
        self.store,self.board=quality.store,quality.board
        self.board.ensure(self.run)
        record=self.store.receipt(self.board.input(self.run,'incident'),kind='incident')
        self.incident,self.original=record['payload'],record['binding']
        roles=quality.project.technical_roles
        if (self.run.kind!='diagnostic' or self.run.reviewing or not roles or self.run.actor not in roles.values()
                or self.incident['project']!=quality.project.fingerprint()
                or self.original['release']!=self.run.release):
            raise ValueError('controller-assigned technical diagnosis required')
        self.level=next(level for level,actor in roles.items() if actor==self.run.actor)
        self.experiment=None

    def evidence(self):
        result=dict(incident=self.incident,failed_execution=self.original)
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            body=json.loads(kb.get_task(conn,self.run.task).body)
            if body.get('escalated_from'):
                prior=kb.latest_run(conn,body['escalated_from'])
                result['previous_diagnosis']=dict(summary=prior.summary,error=prior.error) if prior else None
                if prior and prior.metadata and prior.metadata.get('diagnosis'):
                    receipt=self.store.receipt(prior.metadata['diagnosis'],kind='diagnostic_decision')
                    if receipt['payload']['incident']==self.board.input(self.run,'incident'):
                        result['previous_diagnosis']=receipt['payload']
        return result

    def validate(self,args):
        self.board.ensure(self.run)
        if (not isinstance(args,dict) or not {'hypothesis'}<=set(args) or set(args)-{'hypothesis','replacements'}
                or not isinstance(args['hypothesis'],str) or not 1<=len(args['hypothesis'].strip())<=2000):
            raise ValueError('bounded experiment hypothesis and optional product replacements required')
        snapshot=self.incident['snapshot']
        if 'replacements' in args:snapshot=product_mutations(self.q,snapshot,[args['replacements']])[0]
        job,report=DeliveryTools.wait(self,lambda:self.q.observe(self.run,snapshot,'diagnostic'))
        self.experiment=self.q.record(self.run,'diagnostic_experiment',dict(incident=self.board.input(self.run,'incident'),
            snapshot=snapshot,hypothesis=args['hypothesis'],job=job,report=report))
        return dict(experiment=self.experiment,report=report,delivery_approval=False)

    @property
    def quality(self):return self.q  # Reuse the bounded fixed-job observation helper.

    def decide(self,args):
        self.board.ensure(self.run)
        if (not isinstance(args,dict) or set(args)!={'action','reason','findings'}
                or args['action'] not in ('resume','escalate','hold')
                or args['action']=='escalate' and self.level=='cto'):
            raise ValueError('technical resume, lead escalation or explicit hold required; never CEO or delivery approval')
        if args['action']=='resume' and self.experiment is None:
            raise ValueError('resume requires a real experiment in this execution')
        snapshot=self.incident['snapshot']
        verdict=review_decision(dict(decision='changes',reason=args['reason'],findings=args['findings']),
            self.store.manifest(snapshot),self.store.tree(snapshot))
        receipt=self.q.record(self.run,'diagnostic_decision',dict(incident=self.board.input(self.run,'incident'),
            action=args['action'],verdict=verdict,experiment=self.experiment,delivery_approval=False))
        self.sandbox.close()
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            if not kb.complete_task(conn,self.run.task,summary=verdict['reason'],metadata={'diagnosis':receipt},
                                    expected_run_id=self.run.number):
                raise ValueError('native diagnostic completion refused')
        return dict(status='diagnosis_completed',action=args['action'],diagnosis=receipt,delivery_approval=False)


class Recovery:
    def __init__(self,project,store,board):
        self.project,self.store,self.board=project,store,board
        self.journal=Journal(store.root/'effects')

    def cards(self,conn):
        kb,_,_=native()
        return [kb.get_task(conn,row[0]) for row in conn.execute('SELECT id FROM tasks ORDER BY created_at,id')]

    def stage_for(self,reviewing,actor):
        return 'cto' if reviewing or actor==self.project.technical_roles['lead'] else 'lead'

    def create(self,conn,incident,stage,*,previous=None):
        kb,_,_=native();record=self.store.receipt(incident,kind='incident');data=record['payload']
        actor=self.project.technical_roles[stage]
        return kb.create_task(conn,title='DIAG '+stage+' — '+data['source'],assignee=actor,priority=100,
            body=json.dumps(dict(version=1,kind='diagnostic',release=record['binding']['release'],stage=stage,
                source=data['source'],source_run=data['source_run'],block_event=data['block_event'],
                cause=data['cause'],inputs={'incident':incident},escalated_from=previous)),
            workspace_kind='dir',workspace_path=str(self.store.tree(data['snapshot'])),completion_contract='local-only',
            max_retries=2,max_runtime_seconds=600,idempotency_key=digest([
                self.project.fingerprint(),data['source'],data['source_run'],data['block_event'],'diagnostic',stage]))

    def discover(self,conn,task,settle):
        kb,_,_=native();body=json.loads(task.body)
        if body.get('kind')=='diagnostic':
            if body['stage']=='lead':self.create(conn,body['inputs']['incident'],'cto',previous=task.id)
            return
        if body.get('version')!=1 or body.get('kind') not in ('tests','implementation'):return
        row=conn.execute('SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1',(task.id,)).fetchone()
        event=conn.execute("SELECT * FROM task_events WHERE task_id=? AND kind IN ('blocked','gave_up') ORDER BY id DESC LIMIT 1",(task.id,)).fetchone()
        if not row or not row['ended_at'] or not event:return
        claimed=conn.execute("SELECT payload FROM task_events WHERE run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
        reviewing=bool(claimed and json.loads(claimed[0]).get('source_status')=='review')
        stage=self.stage_for(reviewing,row['profile'])
        key=digest([self.project.fingerprint(),task.id,row['id'],event['id'],'diagnostic',stage])
        existing=conn.execute('SELECT id FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if existing:return
        settle(task.id,conn=conn)
        author=row['profile']
        if reviewing:
            origin=conn.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='review_requested' ORDER BY id DESC LIMIT 1",(task.id,)).fetchone()
            author=json.loads(origin[0])['implementer']
            handoff=json.loads(conn.execute('SELECT metadata FROM task_runs WHERE id=(SELECT run_id FROM task_events '
                "WHERE task_id=? AND kind='review_requested' ORDER BY id DESC LIMIT 1)",(task.id,)).fetchone()[0])
            kind='red' if body['kind']=='tests' else 'green'
            snapshot=self.store.receipt(handoff[kind],kind=kind)['payload']['snapshot']
        else:snapshot=self.store.capture(Path(task.workspace_path))
        source=Run(task.id,row['id'],row['profile'],body['kind'],reviewing,author,body['release'],digest(body))
        failure=row['summary'] or row['error'] or task.result or 'Native worker could not complete'
        payload=json.loads(event['payload'] or '{}')
        reason=payload.get('reason')
        if isinstance(reason,str):
            try:
                data=json.loads(reason)
                if data.get('failure'):
                    failure_record=self.store.receipt(data['failure'],kind='worker_failure')
                    if failure_record['binding']==source.binding():failure=failure_record['payload']['message']
            except (ValueError,TypeError):pass
        cause=digest([task.id,source.contract,reviewing,snapshot,failure])
        incident=self.store.record('incident',source.binding(),dict(project=self.project.fingerprint(),snapshot=snapshot,
            source=task.id,source_run=row['id'],block_event=event['id'],cause=cause,failure=failure,
            workspace=task.workspace_path))
        # A native idempotent anchor survives restart before stage materialization.
        self.create(conn,incident,stage)

    def apply(self,conn,task):
        kb,_,_=native();body=json.loads(task.body);row=kb.latest_run(conn,task.id)
        if not row or row.outcome!='completed' or not row.metadata or 'diagnosis' not in row.metadata:return
        receipt_id=row.metadata['diagnosis'];receipt=self.store.receipt(receipt_id,kind='diagnostic_decision');data=receipt['payload']
        expected=Run(task.id,row.id,task.assignee,'diagnostic',False,task.assignee,body['release'],digest(body))
        if (receipt['binding']!=expected.binding() or data['project']!=self.project.fingerprint()
                or data['incident']!=body['inputs']['incident']
                or task.assignee!=self.project.technical_roles[body['stage']]):raise ValueError('exact native diagnostic evidence required')
        incident=self.store.receipt(data['incident'],kind='incident');source=incident['payload']
        if data['action']=='escalate':
            if body['stage']!='lead':raise ValueError('only lead escalates to CTO')
            self.create(conn,data['incident'],'cto',previous=task.id);return
        if data['action']=='hold':return
        experiment=self.store.receipt(data['experiment'],kind='diagnostic_experiment')
        if experiment['binding']!=expected.binding() or experiment['payload']['incident']!=data['incident']:
            raise ValueError('resume requires its current validated experiment')
        identity=dict(diagnosis=receipt_id,source=source['source'],block_event=source['block_event'])
        key=digest(identity)
        path=self.journal.root/(digest(key+':resume')+'.json')
        if path.exists() and json.loads(path.read_bytes())['state']=='done':return
        attempts=0
        for other in self.cards(conn):
            previous=json.loads(other.body or '{}')
            if previous.get('kind')!='diagnostic' or previous.get('cause')!=source['cause']:continue
            prior=kb.latest_run(conn,other.id)
            if not prior or not prior.metadata or not prior.metadata.get('diagnosis'):continue
            old_id=prior.metadata['diagnosis'];old=self.store.receipt(old_id,kind='diagnostic_decision')['payload']
            old_incident=self.store.receipt(old['incident'],kind='incident')['payload']
            old_key=digest(dict(diagnosis=old_id,source=old_incident['source'],block_event=old_incident['block_event']))
            old_path=self.journal.root/(digest(old_key+':resume')+'.json')
            if old_path.exists() and json.loads(old_path.read_bytes())['state']=='done':attempts+=1
        if attempts>=2:raise EffectBlocked('two recoveries without changed evidence; require new diagnosis or changed preconditions')
        def fresh():
            target=kb.get_task(conn,source['source'])
            latest=kb.latest_run(conn,target.id)
            event=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind IN ('blocked','gave_up') ORDER BY id DESC LIMIT 1",(target.id,)).fetchone()
            if (target.status!='blocked' or not latest or latest.id!=source['source_run'] or not event or event[0]!=source['block_event']
                    or target.assignee!=incident['binding']['actor']
                    or target.workspace_path!=source['workspace']
                    or digest(json.loads(target.body))!=incident['binding']['contract']):
                raise EffectBlocked('diagnosis is stale for the current source impediment')
            if not incident['binding']['reviewing'] and self.store.capture(Path(target.workspace_path))!=source['snapshot']:
                raise EffectBlocked('source workspace changed after the diagnostic snapshot')
        guidance='DIAG '+receipt_id+' '+json.dumps(data['verdict'],sort_keys=True)
        def comment_observed():
            row=conn.execute('SELECT id FROM task_comments WHERE task_id=? AND author=? AND body=?',
                (source['source'],task.assignee,guidance)).fetchone()
            return {'comment':row[0]} if row else None
        def comment():
            fresh();return {'comment':kb.add_comment(conn,source['source'],task.assignee,guidance)}
        self.journal.do(key+':guidance',identity,comment,comment_observed)
        def resumed():
            row=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind='unblocked' AND id>? ORDER BY id LIMIT 1",
                (source['source'],source['block_event'])).fetchone()
            return {'event':row[0]} if row and comment_observed() else None
        def resume():
            fresh()
            if not kb.unblock_task(conn,source['source']):raise EffectBlocked('native resume refused')
            return resumed()
        self.journal.do(key+':resume',identity,resume,resumed)

    def reconcile(self,conn,settle):
        if not self.project.technical_roles:return {}
        issues={}
        for task in self.cards(conn):
            try:
                body=json.loads(task.body or '{}')
                if body.get('kind')=='diagnostic' and task.status=='done':self.apply(conn,task)
                elif task.status=='blocked':self.discover(conn,task,settle)
            except (ValueError,EffectBlocked,Pending,OSError) as error:issues[task.id]=type(error).__name__
        return issues

    def status(self,conn):
        if not self.project.technical_roles:return []
        kb,_,_=native();incidents={}
        for task in self.cards(conn):
            body=json.loads(task.body or '{}')
            if body.get('kind')!='diagnostic':continue
            key=body['inputs']['incident'];record=self.store.receipt(key,kind='incident')
            target=kb.get_task(conn,body['source']);state='blocked'
            if target.status in ('ready','running','review'):state='revalidating'
            if target.status=='done':
                last=kb.latest_run(conn,target.id);metadata=last.metadata if last else {}
                name='tests' if record['binding']['kind']=='tests' else 'delivery'
                state='evidence_missing'
                if metadata and metadata.get(name):
                    evidence=self.store.receipt(metadata[name],kind='tests_frozen' if name=='tests' else 'delivery_review')
                    if (evidence['binding']['task']==target.id and evidence['binding']['contract']==record['binding']['contract']
                            and evidence['payload']['project']==self.project.fingerprint()):state='resolved'
            previous=incidents.get(key)
            if previous and previous['stage']=='cto' and body['stage']=='lead':continue
            incidents[key]=dict(source=target.id,diagnostic=task.id,stage=body['stage'],state=state,
                owner=target.assignee if state=='revalidating' else task.assignee,delivery_approval=False)
        return list(incidents.values())


def register_diagnostic(sandbox,quality,on_terminal):
    from tools.registry import registry
    operations=Diagnostic(sandbox,quality)
    finding=dict(type='object',additionalProperties=False,required=['path','line','detail'],properties=dict(
        path={'type':'string'},line={'type':'integer','minimum':1},detail={'type':'string','minLength':1,'maxLength':2000}))
    schemas=dict(diagnostic_validate=dict(type='object',additionalProperties=False,required=['hypothesis'],properties=dict(
        hypothesis={'type':'string','minLength':1,'maxLength':2000},replacements=dict(type='object',minProperties=1,maxProperties=16,
            additionalProperties={'type':'string','maxLength':131072}))),
        diagnostic_decide=dict(type='object',additionalProperties=False,required=['action','reason','findings'],properties=dict(
            action={'type':'string','enum':['resume','escalate','hold']},reason={'type':'string','minLength':1,'maxLength':2000},
            findings=dict(type='array',minItems=1,maxItems=8,items=finding))))
    def handler(method,terminal):
        def invoke(args,**kwargs):
            result=method(args)
            if terminal and on_terminal:on_terminal(result)
            return json.dumps(result)
        return invoke
    for name,method in (('diagnostic_validate',operations.validate),('diagnostic_decide',operations.decide)):
        registry.register(name=name,toolset='fabriquinha_delivery',schema=dict(name=name,parameters=schemas[name],
            description='Technical diagnosis only. Read immutable evidence, run a fixed disposable SPIKE, propose guidance or escalate. '
                'Never edit the author, weaken tests, approve delivery or send technical decisions to the CEO.'),
            handler=handler(method,name=='diagnostic_decide'))
    return set(schemas),operations
