"""One corrective package after failed deployed QA; native cards own its lifecycle.

V1 is deliberately limited to the last serialized package and expected-text QA
corrections. No graph reset, test deletion, arbitrary exception or old approval.
"""
import json
from .artifacts import digest
from .board import Run
from .effects import EffectBlocked,write_json
from .intake import DraftTools,text,texts
from .kanban_lane import native
from .quality import Quality,suite_report,preview_evidence
from .recovery import Recovery,browser_refusal_context

# Controller source revision, never model-supplied. Changed only for a qualified
# repair-protocol fix, not for documents, timeouts or another identical retry.
REPAIR_PROTOCOL='qa-text-handoff-1'
FIXTURE_PROTOCOL='unpublished-fixture-1'
SUBMISSION_PROTOCOL='complete-control-set-3'
SUBMISSION_PROTOCOLS=('complete-control-set-1','complete-control-set-2',SUBMISSION_PROTOCOL)


def protocol_failure(data):
    prefix='activity ended without a controller-validated native handoff; SDK status '
    message=data.get('failure')
    if not isinstance(message,str) or not message.startswith(prefix):return None
    try:value=json.loads(message[len(prefix):])
    except ValueError:return None
    if (not isinstance(value,dict) or value.get('code')!='missing_terminal_operation'
            or value.get('failed') is not False or type(value.get('api_calls')) is not int
            or not 0<=value['api_calls']<=1000):return None
    return {key:value[key] for key in ('code','failed','api_calls','output_limit','compressions','ineffective_compressions') if key in value}


def held_incident(project,store,incident_key,decision_key,current_snapshot):
    """Common immutable admission facts for technical succession.

    This grants no retry, test-write authority or approval. Callers must still
    verify native current state, new evidence and independent scoped review.
    Old incident/decision/experiment bindings must agree before any proposal.
    """
    incident=store.receipt(incident_key,kind='incident');data=incident['payload'];binding=incident['binding']
    decision=store.receipt(decision_key,kind='diagnostic_decision');choice=decision['payload'];actor=decision['binding']
    cto=(project.technical_roles or {}).get('cto')
    if (not cto or binding.get('kind') not in ('tests','implementation','integration')
            or type(binding.get('reviewing')) is not bool
            or data.get('project')!=project.fingerprint() or data.get('source_state')!='triage'
            or data.get('source')!=binding.get('task') or data.get('source_run')!=binding.get('number')
            or data.get('resume_allowed') is not False or data.get('controller_effects')!=[]
            or data.get('snapshot')!=current_snapshot
            or actor.get('kind')!='diagnostic' or actor.get('reviewing') is not False
            or actor.get('actor')!=cto or actor.get('release')!=binding.get('release')
            or choice.get('project')!=project.fingerprint() or choice.get('incident')!=incident_key
            or choice.get('action')!='hold' or choice.get('delivery_approval') is not False):
        raise ValueError('exact triaged source and CTO hold required for technical succession')
    experiment=store.receipt(choice['experiment'],kind='diagnostic_experiment')
    if (experiment['binding']!=actor or experiment['payload'].get('incident')!=incident_key
            or experiment['payload'].get('project')!=project.fingerprint()
            or experiment['payload'].get('snapshot')!=current_snapshot):
        raise ValueError('exact CTO experiment required; never a replacement for negative controls')
    return incident,decision


def review_failure(project,store,incident_key,decision_key,handoff):
    """Bind a held review to the author's immutable handoff, never its workspace.

    Used as admission evidence for a successor proposal, not as permission to
    approve, edit tests or reset the native source. Native freshness and new
    independent evidence remain required when materializing the proposal.
    """
    incident=store.receipt(incident_key,kind='incident')
    source=incident['binding']
    if source.get('reviewing') is not True or source.get('kind') not in ('tests','implementation'):
        raise ValueError('held delivery review required')
    record=(Quality(project,store,None,None).test_evidence(handoff) if source['kind']=='tests'
            else store.receipt(handoff,kind='green'))
    expected=Run(**{**source,'actor':source['author'],'reviewing':False})
    inherited=incident['payload'].get('reassessment_review')
    if inherited and not expected.same_subject(record['binding']):
        expected=reassessment_origin(project,store,Run(**source),inherited,handoff)
    if (not expected.same_subject(record['binding'])
            or record['payload'].get('project')!=project.fingerprint()):
        raise ValueError('exact author handoff required for review succession')
    snapshot=record['payload']['snapshot']
    held_incident(project,store,incident_key,decision_key,snapshot)
    return dict(source=source['task'],source_run=source['number'],source_contract=source['contract'],
        snapshot=snapshot,handoff=handoff,incident=incident_key,reviewed_diagnosis=decision_key,
        delivery_approval=False,requires_independent_plan_review=True)


def review_observation(report):
    """Compare observed outcomes, not volatile exception wording or prose."""
    cases=report.get('cases')
    if not isinstance(cases,list) or not cases or len(cases)!=len(set(cases)):
        raise ValueError('complete diagnostic case inventory required')
    failures=[]
    for failure in report.get('failures',[]):
        frames=failure.get('frames',[])
        if failure.get('case') not in cases or failure.get('assertion') is not True or not frames:
            raise ValueError('observed assertion frames required')
        failures.append((failure['case'],tuple((f['file'],f['function'],f['line']) for f in frames)))
    return dict(cases=sorted(cases),failures=sorted(failures),
        **{key:sorted(report.get(key,[])) for key in ('errors','skips','expected_failures','unexpected_successes')})


def review_reassessment(project,store,incident,decision,handoff,evidence):
    """Require changed observed results, not another hypothesis or receipt ID."""
    facts=review_failure(project,store,incident,decision,handoff)
    held=store.receipt(decision,kind='diagnostic_decision')
    prior=store.receipt(held['payload']['experiment'],kind='diagnostic_experiment')
    current=store.receipt(evidence,kind='diagnostic_experiment')
    scope,data=current['binding'],current['payload']
    if (scope.get('kind')!='diagnostic' or scope.get('reviewing') is not False
            or scope.get('actor')!=project.technical_roles['cto']
            or scope.get('release')!=held['binding']['release']
            or data.get('project')!=project.fingerprint() or data.get('incident')!=incident
            or data.get('source_snapshot',data.get('snapshot'))!=facts['snapshot']
            or not isinstance(data.get('report'),dict) or not data['report']
            or data['report']==prior['payload'].get('report')
            or not isinstance(data.get('job'),str) or not data['job']):
        raise ValueError('new scoped CTO observation required; new wording is insufficient')
    observation=store.receipt(data['job'],kind='suite_job')
    if (observation['binding']!=scope or observation['payload'].get('report')!=data['report']
            or observation['payload'].get('identity',{}).get('snapshot')!=data['snapshot']
            or observation['payload'].get('identity',{}).get('project')!=project.fingerprint()):
        raise ValueError('new observation requires its exact controller job')
    previous_outcomes=review_observation(prior['payload']['report'])
    current_outcomes=review_observation(data['report'])
    if (current_outcomes['cases']!=previous_outcomes['cases']
            or any(current_outcomes[key] for key in ('errors','skips','expected_failures','unexpected_successes'))):
        raise ValueError('experiment must execute the same complete assertions; unreached behavior is not confirmation')
    if current_outcomes==previous_outcomes:
        raise ValueError('new observed outcome required; changed wording is insufficient')
    if data['snapshot']!=facts['snapshot']:
        # Reuse the same exact protection as disposable product mutations. A
        # diagnostic candidate is evidence only, never the successor delivery.
        Quality(project,store,None,None).protect(facts['snapshot'],data['snapshot'],exact_tests=True)
    return {**facts,'new_evidence':evidence,
        'observation_identity':digest([facts['snapshot'],current_outcomes])}


def submission_failure(project,store,incident_key,decision_key,tests,current_snapshot):
    """Read-only admission facts; never releases triage or creates a task.

    Only a pre-review implementation with an exact control or missing-terminal refusal
    and completed CTO diagnosis can become a scoped continuation proposal.
    The native source/run/state and idle effects still need controller checks.
    """
    from .recovery import control_refusal_context
    incident,decision=held_incident(project,store,incident_key,decision_key,current_snapshot)
    data,binding=incident['payload'],incident['binding']
    if binding.get('kind')!='implementation' or binding.get('reviewing') is not False:
        raise ValueError('exact triaged implementation and CTO hold required for submission repair')
    quality=Quality(project,store,None,None)
    freeze=store.receipt(tests,kind='tests_frozen');frozen=quality.frozen_plan(freeze)
    if freeze['binding']['release']!=binding['release']:
        raise ValueError('independently frozen tests must belong to this release')
    refusal=None;protocol=None
    if data.get('control_refusal'):
        refusal=control_refusal_context(store,project,binding,data['control_refusal'],current_snapshot)
        record=store.receipt(data['control_refusal'],kind='control_refusal')
        green=store.receipt(record['payload']['green'],kind='green')['payload']
        if (not refusal['matches_current_snapshot'] or not refusal['missing']
                or green['freeze']!=tests or set(green['cases'])!=set(frozen['cases'])
                or not set(refusal['missing'])<=set(frozen['control_cases'])
                or not set(refusal['coverage'])<=set(frozen['cases'])):
            raise ValueError('unchanged snapshot and exact independently frozen control targets required')
    else:
        protocol=protocol_failure(data)
        if protocol is None:raise ValueError('exact control refusal or missing-terminal SDK failure required')
    quality.protect(frozen['snapshot'],current_snapshot,exact_tests=True)
    return dict(source=data['source'],source_run=data['source_run'],source_contract=binding['contract'],
        snapshot=current_snapshot,tests=tests,incident=incident_key,reviewed_diagnosis=decision_key,
        control_refusal=refusal,**({'protocol_failure':protocol} if protocol else {}),delivery_approval=False,requires_independent_plan_review=True,
        requires_fresh_green_and_controls=True)


def fixture_failure(project,store,incident,decision,tests,current_snapshot):
    """Only an unintegrated, independently frozen new fixture is eligible."""
    from .executor import browser_contract
    if browser_contract(project,store)!=2:raise ValueError('shared Python acceptance required')
    facts=submission_failure(project,store,incident,decision,tests,current_snapshot)
    quality=Quality(project,store,None,None)
    frozen=quality.frozen_plan(store.receipt(tests,kind='tests_frozen'))
    quality.protect(frozen['baseline'],frozen['snapshot'])
    baseline=store.manifest(frozen['baseline']);snapshot=store.manifest(frozen['snapshot'])
    prefix=project.tests_dir+'/acceptance_'
    eligible=sorted(path for path in snapshot if path not in baseline and path.startswith(prefix)
                    and path.endswith('.py') and '/' not in path[len(project.tests_dir)+1:])
    if not eligible:raise ValueError('only new unpublished acceptance fixtures may be proposed')
    return {**facts,'implementation_snapshot':current_snapshot,'snapshot':frozen['snapshot'],
            'red_baseline':frozen['baseline'],'qa_paths':eligible}


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
        if (data.get('submission_protocol') not in SUBMISSION_PROTOCOLS or body.get('repair_protocol')!=data.get('submission_protocol')
                or body.get('repair_of')!=facts['source']
                or any(data.get(k)!=facts[k] for k in ('source','source_run','source_contract'))):
            raise ValueError('exact scoped submission proposal required')
    if context['payload'].get('repair_kind')=='review':
        data=context['payload']
        facts=review_reassessment(project,store,data['incident'],data['reviewed_diagnosis'],
            data['handoff'],data['new_evidence'])
        if body.get('repair_of')!=facts['source'] or any(data.get(k)!=v for k,v in facts.items()):
            raise ValueError('exact observed review succession required')
    if context['payload'].get('repair_kind')=='fixture':
        data=context['payload']
        facts=fixture_failure(project,store,data['incident'],data['reviewed_diagnosis'],data['tests'],data['implementation_snapshot'])
        if (body.get('repair_protocol')!=FIXTURE_PROTOCOL or body.get('repair_of')!=facts['source']
                or any(data.get(k)!=facts[k] for k in facts)):
            raise ValueError('exact reviewed unpublished-fixture proposal required')
    return dict(review=key,proposal=proposal,context=context['payload'],context_id=body['repair_context'],task=scope['task'])


def reassessment_origin(project,store,run,approval,handoff):
    """Resolve old authorship through an independently reviewed succession.

    Does not copy/rebind a Red or Green receipt. The caller must additionally
    verify that this exact approval is an input of the current native card.
    No approval from the original delivery is inherited by the successor.
    """
    authority=reviewed(project,store,approval);context=authority['context']
    incident=store.receipt(context['incident'],kind='incident');origin=incident['binding']
    if (context.get('repair_kind')!='review' or authority['proposal']['classification']!='reassess'
            or context.get('handoff')!=handoff or run.reviewing is not True
            or run.task==origin['task'] or run.kind!=origin['kind']
            or run.release!=origin['release'] or run.author!=origin['author']
            or run.actor==run.author or run.actor not in project.reviewers_for(run.author)
            or run.number<=origin['number']):
        raise ValueError('independent successor bound to the exact reassessed handoff required')
    record=(Quality(project,store,None,None).test_evidence(handoff) if run.kind=='tests'
            else store.receipt(handoff,kind='green'))
    author=record['binding']
    if (author['actor']!=run.author or author['author']!=run.author or author['reviewing'] is not False
            or author['kind']!=run.kind or author['release']!=run.release
            or author['number']>=run.number or record['payload']['project']!=project.fingerprint()):
        raise ValueError('exact original author receipt required')
    return Run(**author)


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
    allowed=(('reassess','infrastructure','scope') if context.get('repair_kind')=='review' else
             ('submission','infrastructure','scope') if context.get('repair_kind')=='submission' else
             ('test_contract','infrastructure','scope') if context.get('repair_kind')=='fixture' else
             ('product','test_contract','infrastructure','scope'))
    if value['classification'] not in allowed:raise ValueError('permitted corrective classifications: '+', '.join(allowed))
    text(value['reason']);texts(value['test_paths'],maximum=20)
    paths=value['test_paths']
    if len(set(paths))!=len(paths) or not set(paths)<=set(context['qa_paths']):raise ValueError('only existing recorded QA paths may be proposed')
    if bool(paths)!=(value['classification']=='test_contract'):raise ValueError('product fixes cannot authorize test changes')
    return value


def context_view(store,value):
    """Model context needs failure facts, not private graph/workspace copies."""
    keys=('source','source_run','snapshot','commit','tests','browser_job','failure','package','qa_paths','failed_stage','retry_rule','prior_authority',
          'repair_kind','control_refusal','protocol_failure','submission_contract')
    result={k:value[k] for k in keys if k in value}
    if value.get('reviewed_diagnosis'):
        result['prior_diagnosis']=store.receipt(value['reviewed_diagnosis'],kind='diagnostic_decision')['payload']['verdict']
    if value.get('repair_kind') in ('submission','fixture'):
        frozen=store.receipt(value['tests'],kind='tests_frozen')['payload']
        result['protected_tests']=dict(receipt=value['tests'],snapshot=frozen['snapshot'],files=frozen['tests'],
            contract='Controller-recorded frozen paths and hashes; read-only evidence, not permission to change tests.')
    if value.get('repair_kind')=='fixture':
        paths=value['qa_paths'];manifest=store.manifest(value['snapshot'])
        if (not isinstance(paths,list) or not 1<=len(paths)<=20 or len(set(paths))!=len(paths)
                or any(p not in frozen['tests'] for p in paths)
                or value['snapshot']!=frozen['snapshot']
                or sum(manifest[p]['bytes'] for p in paths)>131072):
            raise ValueError('bounded exact frozen fixture sources required for proposal review')
        result['fixture_sources']={p:dict(sha256=manifest[p]['sha256'],text=(store.tree(value['snapshot'])/p).read_text()) for p in paths}
        result['fixture_syntax']='Add new local assignments and calls to methods or existing imported functions. New with blocks may manage setup resources, but may not wrap preserved statements. No new imports/helpers, rebinding, exits or changes to existing assertions.'
    if value.get('repair_kind')=='review':
        decision=store.receipt(value['reviewed_diagnosis'],kind='diagnostic_decision')
        prior=store.receipt(decision['payload']['experiment'],kind='diagnostic_experiment')
        current=store.receipt(value['new_evidence'],kind='diagnostic_experiment')
        result['observations']=dict(previous=prior['payload']['report'],current=current['payload']['report'],
            receipt=value['new_evidence'],snapshot=value['snapshot'],handoff=value['handoff'])
        result['authority']='Observed difference permits consideration, not approval. Preserve source triage and independently review the same author handoff.'
    if value.get('prior_proposal_review'):
        record=store.receipt(value['prior_proposal_review'],kind='plan_review')
        result['prior_proposal_hold']=dict(receipt=value['prior_proposal_review'],verdict=record['payload']['verdict'],
            contract='Historical reviewed hold, preserved unchanged. Reassess against current controller-verified brief_authority; this is not permission to implement.')
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
                'Classify submission only when the recorded control refusal or missing-terminal SDK failure can be addressed by a concrete changed approach; '
                'explain how the proposed continuation differs from the failed partial attempts. '
                'Otherwise classify infrastructure or scope and hold. test_paths must be empty. '
                'No new brief, test changes, breaker reset or approval of the previous Green. '
                'Independent approval authorizes only a replacement attempt with fresh Green, controls and review. '+CONTROL_SUBMISSION_CONTRACT)
            result['continuation_stage']=dict(
                reviewing='permission to create a replacement implementation task, not delivery acceptance',
                controller_support='An independently approved submission plan creates the replacement task and preserves original triage.',
                start_requires=['approved brief','unchanged source snapshot and frozen tests','independent approval of this continuation plan'],
                completion_requires=['new Green','one complete negative-control set','validated delivery_submit handoff','independent delivery review'],
                old_handoff_required=False,completion_evidence_required_before_start=False,
                contract='The old missing_terminal_operation records an incomplete attempt; it does not by itself prove an infrastructure defect. '
                    'Do not require the replacement handoff, mutations, Green or delivery review before creating the task that produces them. '
                    'When the recorded gaps can be addressed by completing implementation and a full mutation set, propose submission. '
                    'Infrastructure or scope holds require a separate actual impediment; never classify absent future completion evidence as a start impediment. '
                    'Approval of this plan never approves delivery or resets the original breaker.')
            result['repair_classifications']=['submission','infrastructure','scope']
        if context['payload'].get('repair_kind')=='fixture':
            result['contract']=('Classify the exact CTO diagnosis against the approved brief. '
                'test_contract proposes scoped corrections in listed unpublished acceptance files. '
                'Preserve integrated baseline, inventory, assertions, discovery and prior control targets. Imports/helpers are reviewable within approved candidate paths; a structural diff is advisory, not semantic approval. '
                'Inspect setup, action and assertion; a failing Red alone does not establish a product defect. '
                'Independent approval authorizes a new test candidate, fresh Red on the original base, and independent freeze; '
                'it does not approve tests, implementation or delivery. Infrastructure/scope remain visible holds. '
                'Do not change product, reset retries or ask the CEO to debug technical fixtures.')
            result['repair_classifications']=['test_contract','infrastructure','scope']
        if context['payload'].get('repair_kind')=='review':
            result['contract']=('Assess whether the new controller observation supports another independent review of the exact immutable handoff. '
                'Use reassess with no test_paths only when that observation addresses the impediment; otherwise hold as infrastructure or scope. '
                'This proposal cannot edit tests, approve code, reset triage, or waive delivery gates. Technical decisions belong to Lead/CTO.')
            result['repair_classifications']=['reassess','infrastructure','scope']
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

    def prepare_review_probe(self,conn,anchor,card,incident,decision,handoff):
        """One native CTO experiment per held review, with unchanged source."""
        kb,_,_=native();source=self.r.check_card(conn,card)
        facts=review_failure(self.project,self.store,incident,decision,handoff)
        latest=kb.latest_run(conn,source.id);body=json.loads(source.body)
        if (source.status!='triage' or not latest or not latest.ended_at
                or facts['source']!=source.id or facts['source_run']!=latest.id
                or facts['source_contract']!=digest(body) or body.get('release_anchor')!=anchor.id):
            raise ValueError('exact settled held review required for experiment')
        recovery=Recovery(self.project,self.store,self.r.board)
        if recovery.expired_effects(source.id):raise EffectBlocked('settle source effects before experiment')
        held=self.store.receipt(decision,kind='diagnostic_decision');scope=held['binding']
        task=kb.get_task(conn,scope['task']);closed=kb.latest_run(conn,scope['task'])
        if (not task or task.status!='done' or not closed or closed.id!=scope['number']
                or closed.outcome!='completed' or (closed.metadata or {}).get('diagnosis')!=decision
                or scope['contract']!=digest(json.loads(task.body))
                or task.assignee!=self.project.technical_roles['cto']):
            raise ValueError('completed native CTO hold required')
        data=self.store.receipt(incident,kind='incident')['payload']
        probe=dict(version=1,kind='diagnostic',release=body['release'],stage='cto',
            source=source.id,source_run=latest.id,block_event=data['block_event'],cause=data['cause'],
            inputs={'incident':incident,'held_review':decision},escalated_from=None,
            review_experiment=dict(handoff=handoff,anchor=anchor.id,
                objective='Test the held review hypothesis with a bounded product-only experiment on a disposable copy. '
                          'Keep all tests/configuration exact. Report observed differences and limitations; never approve delivery.'))
        key=digest([self.project.fingerprint(),source.id,latest.id,'review-experiment'])
        existing=conn.execute('SELECT id,body FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if existing:
            if json.loads(existing['body'])!=probe:raise ValueError('review experiment contract drift')
            return existing['id']
        if self.r.board.guard:self.r.board.guard()
        return kb.create_task(conn,title='SPIKE review '+source.title,body=json.dumps(probe),
            assignee=self.project.technical_roles['cto'],parents=[task.id],priority=100,
            workspace_kind='dir',workspace_path=str(self.store.tree(data['snapshot'])),
            completion_contract='local-only',max_retries=0,max_runtime_seconds=600,idempotency_key=key)

    def prepare_review_proposal(self,conn,anchor,card,incident,decision,handoff,evidence,*,approved_brief,graph):
        """Persist a blocked proposal; activation requires the qualified plan flow.

        No source transition or worker dispatch occurs here. The same observation
        on the same native execution resolves to the same immutable proposal.
        """
        kb,_,_=native();source=self.r.check_card(conn,card)
        facts=review_reassessment(self.project,self.store,incident,decision,handoff,evidence)
        from .intake import Intake
        business,_=Intake(self.project,self.store,self.r.board).approved(approved_brief)
        latest=kb.latest_run(conn,source.id)
        body=json.loads(source.body)
        if business['binding']['release']!=body['release']:
            raise ValueError('review succession requires the same approved business scope')
        if (source.status!='triage' or not latest or not latest.ended_at
                or facts['source']!=source.id or facts['source_run']!=latest.id
                or facts['source_contract']!=digest(body)
                or body.get('release_anchor')!=anchor.id):
            raise ValueError('exact settled native review required')
        if Recovery(self.project,self.store,self.r.board).expired_effects(source.id):
            raise EffectBlocked('settle controller effects before review succession')
        if sum(c['id']==source.id for i in graph['items'] for c in i['cards'].values())!=1:
            raise ValueError('unique review source in current graph required')
        prior=self.store.record('release_graph',self.r.binding(anchor),graph)
        context=self.store.record('repair_context',self.r.binding(anchor),
            dict(**facts,project=self.project.fingerprint(),repair_kind='review',qa_paths=[],prior_graph=prior))
        proposal=dict(version=1,kind='plan',release=body['release'],anchor=anchor.id,
            repair_of=source.id,repair_context=context,inputs={'approved_brief':approved_brief})
        key=digest([self.project.fingerprint(),source.id,latest.id,'review',facts['observation_identity']])
        existing=conn.execute('SELECT id,body FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if existing:
            previous=json.loads(existing['body'])
            old=self.store.receipt(previous['repair_context'],kind='repair_context')['payload']
            if ({**old,'new_evidence':facts['new_evidence']}!=dict(**facts,project=self.project.fingerprint(),repair_kind='review',qa_paths=[],prior_graph=prior)
                    or {**previous,'repair_context':context}!=proposal):
                raise ValueError('review succession proposal drift')
            return existing['id']
        if self.r.board.guard:self.r.board.guard()
        return kb.create_task(conn,title='REASSESS '+source.title,body=json.dumps(proposal),
            assignee=self.project.coordination_roles['lead'],workspace_kind='scratch',
            completion_contract='local-only',initial_status='blocked',max_retries=2,
            max_runtime_seconds=600,idempotency_key=key)

    def publish_review_handoff(self,conn,card,approval):
        """Transfer existing evidence through native review, never fake execution.

        The caller must first persist the complete successor graph. A stopped
        transfer can be repeated; an already claimed review is only observed.
        """
        kb,_,_=native();authority=reviewed(self.project,self.store,approval)
        data=authority['context'];body=card['body']
        self.r.check_card(conn,card)
        if (body.get('kind') not in ('tests','implementation') or data.get('repair_kind')!='review' or authority['proposal']['classification']!='reassess'
                or body.get('inputs',{}).get('reassessment_review')!=approval
                or card['id']==data['source']):
            raise ValueError('explicit independently reviewed successor required')
        plan=kb.get_task(conn,authority['task'])
        if (not plan or plan.status!='done' or plan.id not in card['parents']
                or self.r.closed(plan.id,'plan_review','plan_review')[0]!=approval):
            raise ValueError('native completed proposal parent required')
        source=kb.get_task(conn,data['source']);latest=kb.latest_run(conn,data['source'])
        if (not source or source.status!='triage' or not latest or not latest.ended_at
                or latest.id!=data['source_run'] or digest(json.loads(source.body))!=data['source_contract']):
            raise ValueError('settled original review changed')
        if Recovery(self.project,self.store,self.r.board).expired_effects(source.id):
            raise EffectBlocked('settle source effects before transferring review')
        row=conn.execute("SELECT r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
            "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id DESC LIMIT 1",(source.id,)).fetchone()
        prior=json.loads(row[0]) if row and row[0] else {}
        field='red' if body['kind']=='tests' else 'green'
        if prior.get(field)!=data['handoff']:
            raise ValueError('original native handoff must match approved evidence')
        record=(Quality(self.project,self.store,None,self.r.board).test_evidence(data['handoff'])
                if field=='red' else self.store.receipt(data['handoff'],kind='green'))
        scope=record['binding']
        # reviewed() already validates the full immutable origin chain, including
        # a prior transfer. The author receipt need not belong to the latest card.
        if (scope['actor']!=card['owner'] or scope['reviewing'] or scope['release']!=body['release']
                or scope['kind']!=body['kind'] or record['payload']['snapshot']!=data['snapshot']):
            raise ValueError('preserved exact author delivery required')
        metadata={field:data['handoff'],'reassessment_review':approval,'transfer_only':True}
        excluded=()
        if field=='green':
            controls=self.store.receipt(prior['controls'],kind='controls')
            if controls['binding']!=scope or controls['payload']['green']!=data['handoff']:
                raise ValueError('exact original controls required')
            metadata['controls']=prior['controls']
            frozen=self.store.receipt(record['payload']['freeze'],kind='tests_frozen')
            excluded=(frozen['payload']['test_author'],)
        # A durable native handoff is the acknowledgement. Never dispatch twice.
        transferred=conn.execute("SELECT r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
            "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id LIMIT 1",(card['id'],)).fetchone()
        if transferred:
            if json.loads(transferred[0])!=metadata:raise ValueError('successor handoff drift')
            return card['id']
        task=self.r.check_card(conn,card)
        if kb.latest_run(conn,task.id) is not None or task.status not in ('blocked','ready','todo'):
            raise EffectBlocked('successor already has unrelated activity')
        if self.r.board.guard:self.r.board.guard()
        if task.status=='blocked':
            if not kb.unblock_task(conn,task.id):raise ValueError('successor activation refused')
        if not kb.request_review(conn,task.id,reviewer=self.project.reviewer(card['owner'],exclude=excluded),
                summary='Reassessment transfer of preserved delivery; no new author execution',metadata=metadata):
            raise EffectBlocked('native review transfer awaits satisfied dependencies')
        return task.id

    def propose_fixture(self,conn,anchor,spec,item,incident,decision,graph):
        """A reviewed technical proposal, never an implicit retry or test edit."""
        kb,_,_=native()
        if graph.get('fixture_depth',0)>=1:
            raise EffectBlocked('fixture revision exhausted; require new technical diagnosis, no repeated proposal')
        source=self.r.check_card(conn,item['cards']['implementation'])
        tests=self.r.check_card(conn,item['cards']['tests']);latest=kb.latest_run(conn,source.id)
        if source.status!='triage' or tests.status!='done' or not latest or not latest.ended_at:
            raise ValueError('settled source triage and independently closed tests required')
        frozen,_,_=self.r.closed(tests.id,'tests','tests_frozen')
        facts=fixture_failure(self.project,self.store,incident,decision,frozen,self.store.capture(source.workspace_path))
        if (facts['source']!=source.id or facts['source_run']!=latest.id
                or facts['source_contract']!=digest(json.loads(source.body))
                or json.loads(source.body).get('release_anchor')!=anchor.id):
            raise ValueError('native fixture source changed since diagnosis')
        if Recovery(self.project,self.store,self.r.board).expired_effects(source.id):
            raise EffectBlocked('settle controller effects before fixture proposal')
        if sum(i['cards']['implementation']['id']==source.id for i in graph['items'])!=1:
            raise ValueError('unique fixture source in current graph required')
        prior=self.store.record('release_graph',self.r.binding(anchor),graph)
        context=self.store.record('repair_context',self.r.binding(anchor),dict(**facts,
            project=self.project.fingerprint(),repair_kind='fixture',prior_graph=prior,
            package=item['package'],architecture=spec['document']['architecture'],
            observability=spec['document']['observability']))
        body=dict(version=1,kind='plan',release=self.r.binding(anchor)['release'],anchor=anchor.id,
            repair_of=source.id,repair_context=context,repair_protocol=FIXTURE_PROTOCOL,
            inputs={'approved_brief':spec['approval']})
        key=digest([self.project.fingerprint(),source.id,latest.id,FIXTURE_PROTOCOL,'proposal'])
        existing=conn.execute('SELECT id,body FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if existing:
            if json.loads(existing['body'])!=body:raise ValueError('existing fixture proposal changed; preserve it')
            return existing['id']
        if self.r.board.guard:self.r.board.guard()
        return kb.create_task(conn,title='REVIEW FIXTURE '+item['package']['title'],body=json.dumps(body),
            assignee=self.project.coordination_roles['lead'],workspace_kind='scratch',completion_contract='local-only',
            parents=[spec['task']],max_retries=2,max_runtime_seconds=600,idempotency_key=key)

    def propose_submission(self,conn,anchor,spec,item,incident,decision,graph):
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
        if sum(i['cards']['implementation']['id']==source.id for i in graph['items'])!=1:
            raise ValueError('unique source in current release graph required')
        prior_review=None;prior_task=None
        # Explicit source-contract upgrades, never worker-selected retries.
        # Follow the newest predecessor; its context retains earlier decisions.
        legacy=None
        for protocol in reversed(SUBMISSION_PROTOCOLS[:-1]):
            legacy_key=digest([self.project.fingerprint(),source.id,latest.id,protocol,'proposal'])
            legacy=conn.execute('SELECT id,body FROM tasks WHERE idempotency_key=?',(legacy_key,)).fetchone()
            if legacy:break
        if legacy:
            prior_task=kb.get_task(conn,legacy['id'])
            if prior_task.status!='done':return prior_task.id
            prior_review,_,_=self.r.closed(prior_task.id,'plan_review','plan_review')
            previous=reviewed(self.project,self.store,prior_review)
            if previous['context']['source']!=source.id or previous['context']['source_run']!=latest.id:
                raise ValueError('legacy proposal source changed')
            if previous['proposal']['classification']=='submission':return prior_task.id
            if previous['proposal']['classification'] not in ('infrastructure','scope'):
                raise ValueError('only a preserved reviewed hold may receive corrected context')
        key=digest([self.project.fingerprint(),source.id,latest.id,SUBMISSION_PROTOCOL,'proposal'])
        existing=conn.execute('SELECT id,body FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        submission_contract=CONTROL_SUBMISSION_CONTRACT
        if existing:
            saved=json.loads(existing['body'])
            if not isinstance(saved,dict) or not isinstance(saved.get('repair_context'),str):
                raise ValueError('existing submission proposal differs; preserve it')
            prior=self.store.receipt(saved['repair_context'],kind='repair_context')
            if prior['binding']!=self.r.binding(anchor):raise ValueError('proposal context authority changed')
            submission_contract=prior['payload']['submission_contract']
        prior_graph=self.store.record('release_graph',self.r.binding(anchor),graph)
        context=self.store.record('repair_context',self.r.binding(anchor),dict(**facts,
            project=self.project.fingerprint(),repair_kind='submission',submission_protocol=SUBMISSION_PROTOCOL,
            prior_graph=prior_graph,prior_proposal_review=prior_review,
            submission_contract=submission_contract,qa_paths=[],package=item['package'],
            architecture=spec['document']['architecture'],observability=spec['document']['observability']))
        body=dict(version=1,kind='plan',release=self.r.binding(anchor)['release'],anchor=anchor.id,
            repair_of=source.id,repair_context=context,repair_protocol=SUBMISSION_PROTOCOL,
            inputs={'approved_brief':spec['approval']})
        if existing:
            if json.loads(existing['body'])!=body:raise ValueError('existing submission proposal differs; preserve it')
            return existing['id']
        if self.r.board.guard:self.r.board.guard()
        return kb.create_task(conn,title='REPAIR SUBMISSION '+item['package']['title'],body=json.dumps(body),
            assignee=self.project.coordination_roles['lead'],workspace_kind='scratch',completion_contract='local-only',
            parents=[spec['task']]+([prior_task.id] if prior_task else []),max_retries=2,max_runtime_seconds=600,idempotency_key=key)

    def materialize_submission(self,conn,anchor,graph,approval):
        """Immutable replacement tail; the source triage and completed tests remain."""
        from .executor import validation_files
        kb,_,_=native();authority=reviewed(self.project,self.store,approval);data=authority['context']
        fixture=data.get('repair_kind')=='fixture';reassessment=data.get('repair_kind')=='review'
        expected='reassess' if reassessment else 'test_contract' if fixture else 'submission'
        if data.get('repair_kind') not in ('submission','fixture','review') or authority['proposal']['classification']!=expected:
            raise EffectBlocked('independently approved continuation required')
        previous=self.store.receipt(data['prior_graph'],kind='release_graph')
        if previous['binding']!=self.r.binding(anchor) or previous['payload']!=graph:
            raise ValueError('proposal must refer to the exact unchanged release graph')
        if ((not reassessment and (graph.get('fixture_depth',0)>=1 if fixture else graph.get('submission_depth',0)>=2))
                or any(i.get('repair_context') for i in graph['items'])):
            raise EffectBlocked('bounded pre-publication continuation exhausted or incompatible with deployed repair')
        if graph.get('validation_bundle')!=validation_files(self.project,self.store)[0]:
            raise ValueError('continuation cannot change validation bundle')
        plan=kb.get_task(conn,authority['task'])
        if not plan or plan.status!='done' or self.r.closed(plan.id,'plan_review','plan_review')[0]!=approval:
            raise ValueError('native independent proposal completion required')
        path=self.r.folder(anchor)/('continuation-'+plan.id+'.json')
        source_phase=next((phase for i in graph['items'] for phase,c in i['cards'].items() if c['id']==data['source']),None)
        index=next((n for n,i in enumerate(graph['items']) if any(c['id']==data['source'] for c in i['cards'].values())),None)
        if source_phase not in ('tests','implementation'):raise ValueError('reviewable source phase required')
        replace_tests=fixture or reassessment and source_phase=='tests'
        if index is None:raise ValueError('continuation source missing from graph')
        if path.exists():
            record=self.store.receipt(json.loads(path.read_bytes())['receipt'],kind='release_graph')
            result=record['payload']
            if (record['binding']!=self.r.binding(anchor) or result.get('continuation_review')!=approval
                    or result.get('previous_graph')!=data['prior_graph']):raise ValueError('continuation pointer changed')
        else:
            for n,item in enumerate(graph['items']):
                for phase,card in item['cards'].items():
                    task=self.r.check_card(conn,card);latest=kb.latest_run(conn,task.id)
                    if n<index or n==index and phase=='tests' and (fixture or not replace_tests):
                        if task.status!='done':raise ValueError('completed prefix and frozen tests required')
                    elif task.id==data['source']:
                        if task.status!='triage' or not latest or latest.id!=data['source_run'] or not latest.ended_at:
                            raise ValueError('source triage changed before replacement')
                        if self.store.capture(task.workspace_path)!=(data['implementation_snapshot'] if fixture else data['snapshot']):raise ValueError('source snapshot changed')
                    elif latest is not None or task.status not in ('todo','ready','blocked'):
                        raise EffectBlocked('downstream activity already started; preserve it')
            mapping={};items=list(graph['items'][:index]);retired=[]
            for n,item in enumerate(graph['items'][index:],start=index):
                cards={}
                for phase in ('tests','implementation','integration'):
                    old=item['cards'][phase]
                    if n==index and phase=='tests' and not replace_tests:cards[phase]=old;continue
                    body=json.loads(json.dumps(old['body']));body['continuation_plan']=plan.id
                    for name,value in body['inputs'].items():
                        if value.startswith('parent:'):
                            _,parent,key=value.split(':',2);body['inputs'][name]='parent:'+mapping.get(parent,parent)+':'+key
                    if reassessment and old['id']==data['source']:
                        body['inputs']['reassessment_review']=approval
                    if fixture and n==index:
                        body['inputs']['repair_review']=approval
                        if phase=='tests':body['inputs']['baseline']=data['snapshot']
                    parents=[mapping.get(parent,parent) for parent in old['parents']]
                    # Hold all replacement work behind the independently closed proposal.
                    if plan.id not in parents:parents.append(plan.id)
                    workspace=self.store.root.parent/'work'/self.r.binding(anchor)['release']/('continuation-'+plan.id)/item['package']['id']/phase
                    workspace.mkdir(mode=0o777,parents=True,exist_ok=True);workspace.chmod(0o777)
                    if n==index and ((phase=='implementation' and not fixture and not reassessment) or (reassessment and phase==source_phase)):
                        if not any(workspace.iterdir()):self.store.checkout(data['snapshot'],workspace)
                        elif self.store.capture(workspace)!=data['snapshot']:raise ValueError('unfinished replacement workspace changed')
                    ident=kb.create_task(conn,title=phase.upper()+' '+item['package']['title'],body=json.dumps(body),
                        assignee=old['owner'],parents=parents,workspace_kind='dir',workspace_path=str(workspace),
                        completion_contract=old['completion_contract'],initial_status='blocked',max_retries=2,max_runtime_seconds=600,
                        idempotency_key=digest([self.r.binding(anchor)['release'],plan.id,item['package']['id'],phase,'submission']))
                    mapping[old['id']]=ident;retired.append(old['id'])
                    cards[phase]=dict(id=ident,body=body,parents=parents,workspace=str(workspace),owner=old['owner'],completion_contract=old['completion_contract'])
                items.append({**item,'cards':cards})
            result={**graph,'items':items,'previous_graph':data['prior_graph'],'continuation_review':approval,
                'superseded_cards':sorted(set(graph.get('superseded_cards',[]))|set(retired)),
                'submission_depth':graph.get('submission_depth',0)+(0 if fixture or reassessment else 1),
                **({'fixture_depth':graph.get('fixture_depth',0)+1} if fixture else {})}
            receipt=self.store.record('release_graph',self.r.binding(anchor),result);write_json(path,{'receipt':receipt})
        # Transfer review before releasing any downstream worker. On restart the
        # native handoff is acknowledged without creating another author run.
        if reassessment:
            self.publish_review_handoff(conn,result['items'][index]['cards'][source_phase],approval)
        # No worker may start until the whole replacement graph is durable.
        for item in result['items']:
            for card in item['cards'].values():
                task=self.r.check_card(conn,card)
                if task.status=='blocked' and kb.latest_run(conn,task.id) is None:
                    if self.r.board.guard:self.r.board.guard()
                    if not kb.unblock_task(conn,task.id):raise ValueError('native continuation activation refused')
        return result

    def advance_review_probes(self,conn,anchor,spec,graph):
        """Held review -> one CTO SPIKE -> evidence-bound Lead proposal."""
        kb,_,_=native();recovery=Recovery(self.project,self.store,self.r.board)
        for item in graph['items']:
            for phase in ('tests','implementation'):
                card=item['cards'][phase];source=kb.get_task(conn,card['id'])
                latest=kb.latest_run(conn,card['id'])
                if not source or source.status!='triage' or not latest or not latest.ended_at:continue
                holds=[]
                for task in recovery.cards(conn):
                    body=json.loads(task.body or '{}')
                    if (task.status!='done' or body.get('kind')!='diagnostic' or body.get('stage')!='cto'
                            or body.get('review_experiment') or body.get('source')!=source.id
                            or body.get('source_run')!=latest.id):continue
                    row=kb.latest_run(conn,task.id);key=(row.metadata or {}).get('diagnosis') if row else None
                    if not key:continue
                    decision=self.store.receipt(key,kind='diagnostic_decision')
                    incident=self.store.receipt(decision['payload']['incident'],kind='incident')
                    if decision['payload']['action']=='hold' and incident['binding'].get('reviewing') is True:
                        holds.append((row.id,key,decision['payload']['incident']))
                if not holds:continue
                _,hold,incident=max(holds)
                row=conn.execute("SELECT r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
                    "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id DESC LIMIT 1",(source.id,)).fetchone()
                handoff=json.loads(row[0])['red' if phase=='tests' else 'green'] if row else None
                probe=self.prepare_review_probe(conn,anchor,card,incident,hold,handoff)
                task=kb.get_task(conn,probe)
                if task.status in ('blocked','triage'):
                    raise EffectBlocked('CTO review experiment stopped; preserve incident and diagnose '+probe)
                if task.status!='done':continue
                run=kb.latest_run(conn,probe);key=(run.metadata or {}).get('diagnosis') if run else None
                if not key:raise EffectBlocked('CTO experiment ended without recorded diagnosis: '+probe)
                record=self.store.receipt(key,kind='diagnostic_decision')
                expected=Run(probe,run.id,task.assignee,'diagnostic',False,task.assignee,
                    json.loads(task.body)['release'],digest(json.loads(task.body)))
                data=record['payload']
                if (run.outcome!='completed' or record['binding']!=expected.binding()
                        or data.get('project')!=self.project.fingerprint() or data.get('incident')!=incident
                        or data.get('action')!='hold' or not data.get('experiment')):
                    raise ValueError('exact completed CTO experiment required; source remains held')
                proposal=self.prepare_review_proposal(conn,anchor,card,incident,hold,handoff,data['experiment'],
                    approved_brief=spec['approval'],graph=graph)
                proposed=kb.get_task(conn,proposal)
                if proposed.status=='blocked' and kb.latest_run(conn,proposal) is None:
                    if self.r.board.guard:self.r.board.guard()
                    if not kb.unblock_task(conn,proposal):raise ValueError('native reviewed-evidence proposal activation refused')

    def continue_review(self,conn,anchor,graph):
        """Discover completed reviewed successors from durable native records."""
        seen=set()
        while True:
            sources={c['id'] for i in graph['items'] for c in i['cards'].values()}
            candidates=[]
            for task in Recovery(self.project,self.store,self.r.board).cards(conn):
                body=json.loads(task.body or '{}')
                if (task.status!='done' or body.get('kind')!='plan' or body.get('anchor')!=anchor.id
                        or body.get('repair_of') not in sources or not body.get('repair_context')):continue
                context=self.store.receipt(body['repair_context'],kind='repair_context')['payload']
                if context.get('repair_kind')!='review':continue
                previous=self.store.receipt(context['prior_graph'],kind='release_graph')
                if previous['binding']!=self.r.binding(anchor) or previous['payload']!=graph:continue
                approval,_,_=self.r.closed(task.id,'plan_review','plan_review')
                candidates.append(approval)
            if not candidates:return graph
            if len(candidates)!=1 or candidates[0] in seen:
                raise EffectBlocked('ambiguous or circular review succession; require technical diagnosis')
            seen.add(candidates[0])
            graph=self.materialize_submission(conn,anchor,graph,candidates[0])

    def continue_submission(self,conn,anchor,spec,graph):
        """Reconcile a bounded pre-merge correction through existing plan roles."""
        kb,_,_=native()
        for item in graph['items']:
            source=kb.get_task(conn,item['cards']['implementation']['id'])
            if not source or source.status!='triage':continue
            latest=kb.latest_run(conn,source.id)
            if not latest or not latest.ended_at:continue
            decisions=[]
            for task in Recovery(self.project,self.store,self.r.board).cards(conn):
                body=json.loads(task.body or '{}')
                if (body.get('kind')!='diagnostic' or body.get('source')!=source.id
                        or body.get('source_run')!=latest.id or body.get('stage')!='cto' or task.status!='done'):continue
                row=kb.latest_run(conn,task.id);key=(row.metadata or {}).get('diagnosis') if row else None
                if not key:continue
                decision=self.store.receipt(key,kind='diagnostic_decision')
                incident=self.store.receipt(decision['payload']['incident'],kind='incident')
                if (incident['payload'].get('control_refusal') or protocol_failure(incident['payload'])) and incident['binding'].get('reviewing') is False:
                    decisions.append((decision['payload']['incident'],key))
            if not decisions:continue
            if len(decisions)!=1:raise ValueError('one exact CTO disposition required for continuation')
            propose=self.propose_fixture if graph.get('submission_depth',0)>=2 else self.propose_submission
            proposal=propose(conn,anchor,spec,item,*decisions[0],graph)
            task=kb.get_task(conn,proposal)
            if task.status!='done':return graph
            approval,_,_=self.r.closed(task.id,'plan_review','plan_review')
            replacement=self.materialize_submission(conn,anchor,graph,approval)
            return self.continue_submission(conn,anchor,spec,replacement)
        return graph

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
