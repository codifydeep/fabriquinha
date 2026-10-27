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

# Controller source revision, never model-supplied. Changed only for a qualified
# repair-protocol fix, not for documents, timeouts or another identical retry.
REPAIR_PROTOCOL='qa-text-handoff-1'
SUBMISSION_PROTOCOL='complete-control-set-1'


def submission_failure(project,store,incident_key,decision_key,tests,current_snapshot):
    """Read-only admission facts; never releases triage or creates a task.

    Only a pre-review implementation with an exact negative-control refusal
    and completed CTO diagnosis can become a scoped continuation proposal.
    The native source/run/state and idle effects still need controller checks.
    """
    from .recovery import control_refusal_context
    incident=store.receipt(incident_key,kind='incident');data=incident['payload'];binding=incident['binding']
    decision=store.receipt(decision_key,kind='diagnostic_decision');choice=decision['payload'];actor=decision['binding']
    cto=(project.technical_roles or {}).get('cto')
    if (not cto or binding.get('kind')!='implementation' or binding.get('reviewing') is not False
            or data.get('project')!=project.fingerprint() or data.get('source_state')!='triage'
            or data.get('source')!=binding.get('task') or data.get('source_run')!=binding.get('number')
            or data.get('resume_allowed') is not False or data.get('controller_effects')!=[]
            or data.get('snapshot')!=current_snapshot
            or actor.get('kind')!='diagnostic' or actor.get('reviewing') is not False
            or actor.get('actor')!=cto or actor.get('release')!=binding.get('release')
            or choice.get('project')!=project.fingerprint() or choice.get('incident')!=incident_key
            or choice.get('action')!='hold' or choice.get('delivery_approval') is not False):
        raise ValueError('exact triaged implementation and CTO hold required for submission repair')
    experiment=store.receipt(choice['experiment'],kind='diagnostic_experiment')
    if (experiment['binding']!=actor or experiment['payload'].get('incident')!=incident_key
            or experiment['payload'].get('project')!=project.fingerprint()
            or experiment['payload'].get('snapshot')!=current_snapshot):
        raise ValueError('exact CTO experiment required; never a replacement for negative controls')
    refusal=control_refusal_context(store,project,binding,data['control_refusal'],current_snapshot)
    record=store.receipt(data['control_refusal'],kind='control_refusal')
    green=store.receipt(record['payload']['green'],kind='green')['payload']
    quality=Quality(project,store,None,None)
    freeze=store.receipt(tests,kind='tests_frozen');frozen=quality.frozen_plan(freeze)
    if (not refusal['matches_current_snapshot'] or not refusal['missing']
            or green['freeze']!=tests or freeze['binding']['release']!=binding['release']
            or set(green['cases'])!=set(frozen['cases'])
            or not set(refusal['missing'])<=set(frozen['control_cases'])
            or not set(refusal['coverage'])<=set(frozen['cases'])):
        raise ValueError('unchanged snapshot and exact independently frozen control targets required')
    quality.protect(frozen['snapshot'],current_snapshot,exact_tests=True)
    return dict(source=data['source'],source_run=data['source_run'],source_contract=binding['contract'],
        snapshot=current_snapshot,tests=tests,incident=incident_key,reviewed_diagnosis=decision_key,
        control_refusal=refusal,delivery_approval=False,requires_independent_plan_review=True,
        requires_fresh_green_and_controls=True)


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
    if context['payload'].get('repair_kind')=='submission':
        data=context['payload']
        facts=submission_failure(project,store,data['incident'],data['reviewed_diagnosis'],data['tests'],data['snapshot'])
        if (data.get('submission_protocol')!=SUBMISSION_PROTOCOL or body.get('repair_protocol')!=SUBMISSION_PROTOCOL
                or body.get('repair_of')!=facts['source']
                or any(data.get(k)!=facts[k] for k in ('source','source_run','source_contract'))):
            raise ValueError('exact scoped submission proposal required')
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
    allowed=('submission','infrastructure','scope') if context.get('repair_kind')=='submission' else ('product','test_contract','infrastructure','scope')
    if value['classification'] not in allowed:raise ValueError('permitted corrective classifications: '+', '.join(allowed))
    text(value['reason']);texts(value['test_paths'],maximum=20)
    paths=value['test_paths']
    if len(set(paths))!=len(paths) or not set(paths)<=set(context['qa_paths']):raise ValueError('only existing recorded QA paths may be proposed')
    if bool(paths)!=(value['classification']=='test_contract'):raise ValueError('product fixes cannot authorize test changes')
    return value


def context_view(store,value):
    """Model context needs failure facts, not private graph/workspace copies."""
    keys=('source','source_run','snapshot','commit','tests','browser_job','failure','package','qa_paths','failed_stage','retry_rule','prior_authority',
          'repair_kind','control_refusal','submission_contract')
    result={k:value[k] for k in keys if k in value}
    if value.get('reviewed_diagnosis'):
        result['prior_diagnosis']=store.receipt(value['reviewed_diagnosis'],kind='diagnostic_decision')['payload']['verdict']
    return result


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
        result.update(repair=context_view(self.a.store,context['payload']),contract='Classify the actual QA failure against the approved brief. Submit only classification, reason and test_paths using repair_submit. No new brief or release plan. Product corrections preserve tests; technical corrections may revise only expected text in explicitly listed QA files. Infrastructure/scope classifications are explicit holds, never permission to alter product or business scope. Review independently; never remove coverage.')
        from .executor import browser_contract
        if browser_contract(self.a.project,self.a.store)==2:
            result['contract']='Classify actual failure against the brief. Product repair preserves frozen Python tests and manifests. Technical revision of frozen Python acceptance is not qualified: report this controller capability as an infrastructure hold with the CTO as technical owner and no test_paths. Do not retry the same unsupported operation or ask the CEO to debug it. Business changes or removal of coverage require scoped CEO approval. New candidate tests may be corrected before independent freeze.'
        if context['payload'].get('repair_kind')=='submission':
            from .quality import CONTROL_SUBMISSION_CONTRACT
            result['contract']=('Review a bounded continuation after native implementation triage. '
                'Classify submission only when the recorded negative-control refusal can be addressed with a complete set; '
                'explain how the proposed continuation differs from the failed partial attempts. '
                'Otherwise classify infrastructure or scope and hold. test_paths must be empty. '
                'No new brief, test changes, breaker reset or approval of the previous Green. '
                'Independent approval authorizes only a replacement attempt with fresh Green, controls and review. '+CONTROL_SUBMISSION_CONTRACT)
            result['repair_classifications']=['submission','infrastructure','scope']
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

    def propose_submission(self,conn,anchor,spec,item,incident,decision):
        """Document-only native handoff; activation of replacement work is separate."""
        from .quality import CONTROL_SUBMISSION_CONTRACT
        kb,_,_=native()
        source=self.r.check_card(conn,item['cards']['implementation'])
        tests=self.r.check_card(conn,item['cards']['tests'])
        latest=kb.latest_run(conn,source.id)
        if source.status!='triage' or tests.status!='done' or not latest or not latest.ended_at:
            raise ValueError('settled triaged implementation and independently closed tests required')
        frozen,_,_=self.r.closed(tests.id,'tests','tests_frozen')
        facts=submission_failure(self.project,self.store,incident,decision,frozen,self.store.capture(source.workspace_path))
        if (facts['source']!=source.id or facts['source_run']!=latest.id
                or facts['source_contract']!=digest(json.loads(source.body))
                or json.loads(source.body).get('release_anchor')!=anchor.id):
            raise ValueError('native source changed since CTO diagnosis')
        if Recovery(self.project,self.store,self.r.board).expired_effects(source.id):
            raise EffectBlocked('settle controller effects before a submission proposal')
        context=self.store.record('repair_context',self.r.binding(anchor),dict(**facts,
            project=self.project.fingerprint(),repair_kind='submission',submission_protocol=SUBMISSION_PROTOCOL,
            submission_contract=CONTROL_SUBMISSION_CONTRACT,qa_paths=[],package=item['package'],
            architecture=spec['document']['architecture'],observability=spec['document']['observability']))
        body=dict(version=1,kind='plan',release=self.r.binding(anchor)['release'],anchor=anchor.id,
            repair_of=source.id,repair_context=context,repair_protocol=SUBMISSION_PROTOCOL,
            inputs={'approved_brief':spec['approval']})
        key=digest([self.project.fingerprint(),source.id,latest.id,SUBMISSION_PROTOCOL,'proposal'])
        existing=conn.execute('SELECT id,body FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if existing:
            if json.loads(existing['body'])!=body:raise ValueError('existing submission proposal differs; preserve it')
            return existing['id']
        if self.r.board.guard:self.r.board.guard()
        return kb.create_task(conn,title='REPAIR SUBMISSION '+item['package']['title'],body=json.dumps(body),
            assignee=self.project.coordination_roles['lead'],workspace_kind='scratch',completion_contract='local-only',
            parents=[spec['task']],max_retries=2,max_runtime_seconds=600,idempotency_key=key)

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

    def retry_context(self,conn,item,anchor,failed):
        """A new reviewed package after native triage, not a reset of that task."""
        kb,_,_=native();recovery=Recovery(self.project,self.store,self.r.board)
        if recovery.expired_effects(failed.id):raise EffectBlocked('settle failed corrective activity effects first')
        diagnosis=None
        for task in recovery.cards(conn):
            body=json.loads(task.body or '{}')
            if body.get('kind')!='diagnostic' or body.get('source')!=failed.id or body.get('stage')!='cto' or task.status!='done':continue
            row=kb.latest_run(conn,task.id)
            if row and row.metadata and row.metadata.get('diagnosis'):
                key=row.metadata['diagnosis'];record=self.store.receipt(key,kind='diagnostic_decision')
                incident=self.store.receipt(record['payload']['incident'],kind='incident')
                current=kb.latest_run(conn,failed.id)
                if (record['binding']['actor']==self.project.technical_roles['cto']
                        and record['payload']['project']==self.project.fingerprint()
                        and incident['payload']['source']==failed.id and current and current.ended_at
                        and incident['payload']['source_run']==current.id):diagnosis=key
        if not diagnosis:return None
        previous=self.store.receipt(item['repair_context'],kind='repair_context')
        latest=kb.latest_run(conn,failed.id)
        prior_review=json.loads(failed.body)['inputs']['repair_review'];authority=reviewed(self.project,self.store,prior_review)
        data={**previous['payload'],'source':failed.id,'source_run':latest.id,'source_contract':digest(json.loads(failed.body)),
              'prior':item,'failed_stage':json.loads(failed.body)['kind'],'reviewed_diagnosis':diagnosis,
              'prior_authority':dict(review=prior_review,proposal=authority['proposal']),
              'failed_workspace_snapshot':self.store.capture(failed.workspace_path),
              'retry_rule':'Prior package remains triaged. Review the diagnosis against the corrective authority; it cannot silently revoke approved QA-text correction. Reclassify and review a new bounded package, never repeat the old worker or declare success.'}
        return self.store.record('repair_context',self.r.binding(anchor),data)

    def reconcile(self,conn,anchor,spec,graph,services):
        """Replace only a failed final package in the acceptance view, never history."""
        kb,_,_=native();item=graph['items'][-1]
        failed=next((kb.get_task(conn,item['cards'][phase]['id']) for phase in ('tests','implementation')
                     if item.get('repair_context') and phase in item['cards']
                     and kb.get_task(conn,item['cards'][phase]['id']).status=='triage'),None)
        source=failed.id if failed else item['cards']['integration']['id']
        # Existing corrective cards remain discoverable after QA succeeds.
        rows=conn.execute('SELECT id,body FROM tasks ORDER BY created_at,id').fetchall()
        existing=[kb.get_task(conn,row['id']) for row in rows if json.loads(row['body'] or '{}').get('repair_of')==source]
        if not existing:
            context=self.retry_context(conn,item,anchor,failed) if failed else self.context(conn,item,anchor,services,spec)
            if not context:return graph
            attempts=item.get('repair_attempts',0) if item.get('repair_protocol')==REPAIR_PROTOCOL else 0
            if attempts>=2:raise EffectBlocked('two corrective packages under the same protocol; new technical evidence/preconditions required, no identical automatic repetition')
            data=self.store.receipt(context)['payload']
            body=dict(version=1,kind='plan',release=self.r.binding(anchor)['release'],anchor=anchor.id,
                repair_of=data['source'],repair_context=context,repair_protocol=REPAIR_PROTOCOL,inputs={'approved_brief':spec['approval']})
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
        protocol=json.loads(task.body).get('repair_protocol','legacy')
        attempts=item.get('repair_attempts',0) if item.get('repair_protocol')==protocol else 0
        replacement['items'][0].update(repair_context=authority['context_id'],repair_depth=item.get('repair_depth',0)+1,
            repair_protocol=protocol,repair_attempts=attempts+1)
        effective={**graph,'items':[*graph['items'][:-1],replacement['items'][0]]}
        return self.reconcile(conn,anchor,spec,effective,services)
