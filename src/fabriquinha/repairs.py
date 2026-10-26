"""One corrective package after failed deployed QA; native cards own its lifecycle.

V1 is deliberately limited to the last serialized package and expected-text QA
corrections. No graph reset, test deletion, arbitrary exception or old approval.
"""
import json
from .artifacts import digest
from .board import Run
from .effects import EffectBlocked
from .intake import DraftTools,text,texts
from .kanban_lane import native
from .quality import Quality,suite_report,preview_evidence
from .recovery import Recovery,browser_refusal_context


def reviewed(project,store,key):
    record=store.receipt(key,kind='plan_review');scope=record['binding']
    proposed=store.receipt(record['payload']['plan'],kind='work_plan')
    body=proposed['payload'].get('repair_body',{});context=store.receipt(body.get('repair_context'),kind='repair_context')
    author=project.coordination_roles['lead']
    if (record['payload']['project']!=project.fingerprint() or proposed['payload']['project']!=project.fingerprint()
            or not scope.get('reviewing') or scope.get('author')!=author or scope.get('actor') not in project.reviewers_for(author)
            or scope['actor']==author or record['payload']['verdict']['decision']!='approve'
            or record['payload']['verdict']['findings'] or scope['task']!=proposed['binding']['task']
            or scope['contract']!=digest(body) or proposed['binding']['contract']!=scope['contract']
            or proposed['binding']['actor']!=author or proposed['binding']['reviewing']
            or context['payload']['project']!=project.fingerprint() or scope['release']!=context['binding']['release']
            or proposed['binding']['release']!=scope['release']):
        raise ValueError('exact independent corrective-plan review required')
    proposal=repair_document(proposed['payload']['document'],context['payload'])
    return dict(review=key,proposal=proposal,context=context['payload'],context_id=body['repair_context'],task=scope['task'])


def repair_authority(project,store,board,run):
    reader=getattr(board,'repair_input',None)
    key=reader(run) if reader else None
    if not isinstance(key,str):return None
    result=reviewed(project,store,key)
    if store.receipt(key)['binding']['release']!=run.release:raise ValueError('foreign repair release')
    return result


def repair_document(value,context):
    if not isinstance(value,dict) or set(value)!={'classification','reason','test_paths'}:
        raise ValueError('repair classification, brief-grounded reason and explicit test paths required')
    if value['classification'] not in ('product','test_contract','infrastructure','scope'):raise ValueError('classify product, test_contract, infrastructure or scope')
    text(value['reason']);texts(value['test_paths'],maximum=20)
    paths=value['test_paths']
    if len(set(paths))!=len(paths) or not set(paths)<=set(context['qa_paths']):raise ValueError('only existing recorded QA paths may be proposed')
    if bool(paths)!=(value['classification']=='test_contract'):raise ValueError('product fixes cannot authorize test changes')
    return value


def validate_revision(project,store,quality,record):
    data=record['payload'];authority=reviewed(project,store,data['authority']);context=authority['context']
    if (record['kind']!='test_revision' or data['project']!=project.fingerprint()
            or record['binding']['kind']!='tests' or record['binding']['reviewing']
            or record['binding']['release']!=store.receipt(data['authority'])['binding']['release']
            or data['baseline']!=context['snapshot'] or data['historical_tests']!=context['tests']
            or authority['proposal']['classification']!='test_contract'):
        raise ValueError('revision must identify the reviewed correction and unchanged historical TDD')
    quality.correction_diff(data['baseline'],data['snapshot'],authority['proposal']['test_paths'])
    previous=quality.frozen_plan(store.receipt(context['tests'],kind='tests_frozen'))
    if (data['historical_red']!=previous['red'] or data['control_cases']!=previous['control_cases']
            or set(data['cases'])!=set(previous['cases']) or data['new_cases']!=previous['new_cases']):
        raise ValueError('historical coverage and control targets must remain intact')
    job=store.receipt(data['validation_job'],kind='suite_job');facts=job['payload'];identity=facts['identity']
    if (job['binding']!=record['binding'] or identity['binding']!=record['binding']
            or identity['project']!=project.fingerprint() or identity['snapshot']!=data['snapshot']
            or identity['phase']!='green' or identity['image']!=project.validation_image):raise ValueError('exact correction validation required')
    preview_evidence(project,store,facts,data['snapshot'],'green');report=suite_report(facts)
    if report['failures'] or set(report['cases'])!=set(data['cases']):raise ValueError('complete correction suite required')


class RepairTools(DraftTools):
    repair=True
    def body(self):
        kb,api,_=native()
        with api.connect_closing() as conn:return json.loads(kb.get_task(conn,self.run.task).body)

    def evidence(self):
        result=super().evidence();context=self.a.store.receipt(self.body()['repair_context'],kind='repair_context')
        if context['binding']['release']!=self.run.release:raise ValueError('foreign corrective context')
        result.update(repair=context['payload'],contract='Classify the actual QA failure against the approved brief. Submit only classification, reason and test_paths using repair_submit. No new brief or release plan. Product corrections preserve tests; technical corrections may revise only expected text in explicitly listed QA files. Infrastructure/scope classifications are explicit holds, never permission to alter product or business scope. Review independently; never remove coverage.')
        return result

    def submit(self,args):
        if self.run.reviewing:raise ValueError('review cannot replace the correction proposal')
        document=repair_document(args,self.evidence()['repair']);body=self.body()
        receipt=self.a.store.record('work_plan',self.run.binding(),dict(project=self.a.project.fingerprint(),
            approval=self.a.board.input(self.run,'approved_brief'),document=document,repair_body=body))
        self.a.board.review(self.run,'Independent review of scoped corrective classification and test authority',{'plan':receipt})
        return dict(status='repair_review_requested',plan=receipt,delivery_approval=False)

    def review(self,args):
        evidence=self.evidence()
        if not self.run.reviewing or self.run.actor==self.run.author:raise ValueError('independent correction review required')
        if not isinstance(args,dict) or set(args)!={'decision','reason','findings'} or args['decision'] not in ('approve','changes'):
            raise ValueError('structured correction review required')
        text(args['reason']);texts(args['findings'],maximum=8)
        if (args['decision']=='approve')!=(not args['findings']):raise ValueError('changes need findings; approval cannot retain findings')
        repair_document(evidence['plan'],evidence['repair'])
        receipt=self.a.store.record('plan_review',self.run.binding(),dict(project=self.a.project.fingerprint(),verdict=args,
            plan=self.a.board.input(self.run,'plan',review_handoff=True)))
        self.a.board.finish_review(self.run,args['reason'],{'plan_review':receipt},changes=args['decision']=='changes')
        return dict(status='repair_approved' if args['decision']=='approve' else 'changes_requested',review=receipt,delivery_approval=False)


class Repairs:
    def __init__(self,releases):
        self.r=releases;self.project=releases.project;self.store=releases.store

    def context(self,conn,item,anchor,services,spec):
        kb,_,_=native();card=item['cards']['integration'];task=kb.get_task(conn,card['id'])
        if task.status not in ('blocked','triage'):return None
        row=kb.latest_run(conn,task.id)
        if not row or not row.ended_at:return None
        recovery=Recovery(self.project,self.store,self.r.board)
        if recovery.expired_effects(task.id):raise EffectBlocked('settle controller effects before corrective work')
        origin,handoff=recovery.handoff(conn,task)
        if not handoff.get('rollout'):return None
        author=origin['implementer'];source=Run(task.id,row.id,row.profile,'integration',True,author,
            json.loads(task.body)['release'],digest(json.loads(task.body)))
        matches=[]
        for path in (self.store.root/'receipts').glob('*.json'):
            record=self.store.receipt(path.stem)
            if record['kind']=='browser_job' and record['binding']==source.binding():matches.append(path.stem)
        if not matches:return None
        key=sorted(matches)[-1];failure=browser_refusal_context(self.store,self.project,source.binding(),key)
        if failure['infrastructure_error']:return None
        rollout=self.store.receipt(handoff['rollout'],kind='rollout');artifact=self.store.receipt(rollout['payload']['candidate'],kind='artifact')
        payload=artifact['payload'];job=self.store.receipt(key)['payload']['identity']
        if (not source.same_subject({**rollout['binding'],'actor':source.actor,'reviewing':True})
                or payload['snapshot']!=job['snapshot'] or payload['commit']!=job['commit']):raise ValueError('exact failed deployed candidate required')
        repository,_=services(author,task=task.id)
        if repository.remote_head(self.project.branch)!=payload['commit'] or repository.snapshot(payload['commit'])!=payload['snapshot']:
            raise EffectBlocked('release base moved after failed QA; scoped repair cannot guess a rebase')
        freeze,_,_=self.r.closed(item['cards']['tests']['id'],'tests','tests_frozen')
        delivery,review,_=self.r.closed(item['cards']['implementation']['id'],'delivery','delivery_review')
        green=self.store.receipt(review['payload']['green'],kind='green')
        integrated=self.store.receipt(payload['integrated'],kind='integrated')
        publication=self.store.receipt(integrated['payload']['publication'],kind='publication')['payload']
        if (payload['review']!=delivery or green['payload']['freeze']!=freeze
                or review['payload']['verdict']['decision']!='approve' or review['payload']['verdict']['findings']
                or review['payload']['snapshot']!=payload['snapshot'] or integrated['payload']['commit']!=payload['commit']):
            raise ValueError('failed QA must retain its exact independently reviewed implementation and TDD')
        result=dict(project=self.project.fingerprint(),source=task.id,source_run=row.id,source_contract=source.contract,
            snapshot=payload['snapshot'],commit=payload['commit'],artifact=rollout['payload']['candidate'],tests=freeze,
            browser_job=key,failure=failure,package=item['package'],prior=item,
            architecture=spec['document']['architecture'],observability=spec['document']['observability'],
            prior_base_commit=publication['base_sha'],prior_base_snapshot=repository.snapshot(publication['base_sha']),
            qa_paths=[p for p in self.store.manifest(payload['snapshot']) if p.startswith(self.project.tests_dir+'/')
                      and (p.rsplit('/',1)[-1]=='qa.json' or p.rsplit('/',1)[-1].startswith('qa.') and p.endswith('.json'))])
        return self.store.record('repair_context',self.r.binding(anchor),result)

    def reconcile(self,conn,anchor,spec,graph,services):
        """Replace only a failed final package in the acceptance view, never history."""
        kb,_,_=native();item=graph['items'][-1]
        # Existing corrective cards remain discoverable after QA succeeds.
        rows=conn.execute('SELECT id,body FROM tasks ORDER BY created_at,id').fetchall()
        existing=[kb.get_task(conn,row['id']) for row in rows if json.loads(row['body'] or '{}').get('repair_of')==item['cards']['integration']['id']]
        if not existing:
            context=self.context(conn,item,anchor,services,spec)
            if not context:return graph
            if item.get('repair_depth',0)>=2:raise EffectBlocked('two corrective packages reached; CTO diagnosis required, no identical automatic repetition')
            data=self.store.receipt(context)['payload']
            body=dict(version=1,kind='plan',release=self.r.binding(anchor)['release'],anchor=anchor.id,
                repair_of=data['source'],repair_context=context,inputs={'approved_brief':spec['approval']})
            task_id=kb.create_task(conn,title='REPAIR '+data['package']['title'],body=json.dumps(body),
                assignee=self.project.coordination_roles['lead'],workspace_kind='scratch',completion_contract='local-only',
                parents=[spec['task']],max_retries=2,max_runtime_seconds=600,
                idempotency_key=digest([self.project.fingerprint(),data['source'],data['commit'],'repair']))
            existing=[kb.get_task(conn,task_id)]
        if len(existing)!=1:raise ValueError('one corrective proposal per source required')
        task=existing[0]
        if task.status!='done':return graph
        key,_,_=self.r.closed(task.id,'plan_review','plan_review');authority=reviewed(self.project,self.store,key);context=authority['context']
        if authority['proposal']['classification'] not in ('product','test_contract'):
            raise EffectBlocked('Reviewed '+authority['proposal']['classification']+' impediment: '+authority['proposal']['reason']+'; no product package or repeat model dispatch authorized')
        repository,_=services(self.project.delivery_roles['integration'],task=context['source'])
        path=self.r.folder(anchor)/('repair-'+task.id+'.json')
        if not path.exists() and repository.remote_head(self.project.branch)!=context['commit']:
            raise EffectBlocked('corrective base changed before materialization')
        package={**item['package'],'id':'repair-'+task.id.replace('_','-'),'depends_on':[]}
        seed=self.store.record('release_seed',self.r.binding(anchor),dict(project=self.project.fingerprint(),
            plan_review=key,commit=context['commit'],snapshot=context['snapshot']))
        revised=dict(task=task.id,review=key,approval=spec['approval'],brief=spec['brief'],
            document=dict(architecture=spec['document']['architecture'],observability=spec['document']['observability'],tasks=[package]),
            repair=dict(review=key,context=authority['context_id'],plan=task.id))
        _,replacement=self.r.materialize(conn,anchor,revised,services,path=path,seed=seed)
        replacement['items'][0].update(repair_context=authority['context_id'],repair_depth=item.get('repair_depth',0)+1)
        effective={**graph,'items':[*graph['items'][:-1],replacement['items'][0]]}
        return self.reconcile(conn,anchor,spec,effective,services)
