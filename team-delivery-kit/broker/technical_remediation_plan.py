"""Persistent CTO plan -> independent Tech Lead review for exhausted recovery.

Only planning workers are dispatched. Implementation remains blocked until a
separate, validated remediation execution adapter consumes the exact plan.
"""
import hashlib
import json
import time
import urllib.error
from jsonschema import Draft202012Validator
from remediation_plan_contract import schema
from execution_context import validate as validate_capsule
try:
    import handoffs, handoff_runtime, native, service_mode_schema_evidence
    from incremental_provisioning import NativeIssues
except ImportError:
    from broker import handoffs, handoff_runtime, native, service_mode_schema_evidence
    from broker.incremental_provisioning import NativeIssues


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class DispatchObservationRequired(RuntimeError):
    """An uncertain remote write must be observed, not repeated."""


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS technical_remediation_plans('
                'source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def criteria(capsule):
    text = validate_capsule(capsule)['description']
    prefix = ' Acceptance: '
    if text.count(prefix)!=1:
        raise ValueError('one approved acceptance list required')
    values,_ = json.JSONDecoder().raw_decode(text.split(prefix,1)[1])
    if (not isinstance(values,list) or not 1<=len(values)<=32
            or any(not isinstance(v,str) or not 1<=len(v)<=600 for v in values)
            or len(set(values))!=len(values)):
        raise ValueError('bounded unchanged approved criteria required')
    return {'A'+str(i).zfill(2):v for i,v in enumerate(values,1)}


def register(b, source):
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            prior=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            parser_repair=None
            if prior:
                prior_state=json.loads(prior['state'])
                if (json.loads(prior['config'])=={} and prior_state.get('stage')=='blocked'
                        and prior_state.get('category')=='KeyError'
                        and prior_state.get('required_action')=='CTO diagnose rejected remediation intake; no identical retry'
                        and not prior_state.get('issue_id') and not prior_state.get('wakeup_id')
                        and not prior_state.get('initial_root_parser_repair_attempted')):
                    # One changed implementation, before any remote effect. A
                    # failed qualification keeps this attempt fenced durably.
                    parser_repair=dict(operation='initial_review_root_parser_repair_v1',previous=prior_state,
                                       new_worker_authorized=False,revision_depth_reset=False)
                    prior_state={**prior_state,'initial_root_parser_repair_attempted':True}
                    con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',
                                (json.dumps(prior_state,sort_keys=True),source))
                    con.commit()
                else:return prior_state
            row=handoffs.load(con,source)
            if not row or row['stage']!='test_revision_required':raise ValueError('current exhausted revision proposal required')
            data=json.loads(row['data']);route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            original=con.execute('SELECT state FROM service_mode_schema_experiments WHERE source_task=?',(source,)).fetchone()
            experiment=json.loads(original[0]) if original else {}
            receipt=data.get('service_mode_schema_evidence')
            if (experiment.get('stage')!='complete' or experiment.get('receipt')!=receipt
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
                    or (data.get('decision') or {}).get('action')!='request_test_revision'
                    or data.get('target')!=route['cto'] or data.get('technical_replan_certificate')):
                raise ValueError('idle source-bound exhausted CTO diagnosis required')
            lineage=[];issue=row['issue_id']
            original_base_sha=None
            while True:
                trial=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
                if not trial:break
                trial=json.loads(trial[0])
                if trial.get('initial_review') is True:
                    if ('parent_issue' in trial or 'old_red' in trial or 'cto_decision' in trial
                            or trial.get('base_sha')!=original_base_sha):
                        raise ValueError('authentic initial test review root required')
                    break
                if not {'parent_issue','base_sha'}<=set(trial):
                    raise ValueError('explicit sponsored revision ancestry required')
                lineage.append(issue);issue=trial['parent_issue']
                if original_base_sha is None:original_base_sha=trial['base_sha']
                if issue in lineage or len(lineage)>2:raise ValueError('ambiguous recovery ancestry')
            if len(lineage)!=2:raise ValueError('exactly two preserved revision generations required')
            if parser_repair and (not trial or trial.get('initial_review') is not True):
                raise ValueError('changed root parser repair requires actual initial review record')
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            service_mode_schema_evidence.validate_proof(receipt['proof'],red['red']['test_sha256']['tests/test_service_mode_indicator.py'])
            paths=sorted('/evidence/candidate/'+p for p in receipt['proof']['input_sha256'])
            capsule=validate_capsule(route['execution_context'])
            config=dict(source_task=source,source_issue=row['issue_id'],root_issue=issue,
                original_depth=2,revision_lineage=lineage,cto=route['cto'],reviewer=route['techlead'],
                original_author=route['author'],contract_sha256=route['contract_sha256'],
                context_sha256=capsule['sha256'],criteria=criteria(capsule),volume=receipt['volume'],
                experiment=receipt,diagnostic_task=data['recipient_task'],diagnostic_wakeup=data['wakeup_id'],
                required_paths=paths)
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        task=native.task_record(settings,config['diagnostic_task'],config['cto']);reads=fx.read_evidence(task)
        if (task.get('status')!='completed' or task.get('issue_id')!=config['source_issue']
                or task.get('wakeup_id')!=config['diagnostic_wakeup'] or fx.decision(task)!=data['decision']
                or config['cto']==config['reviewer']
                or any(settings['agents'].get(a)!='planning' for a in (config['cto'],config['reviewer']))
                or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in paths)
                or any(r.get('status') in ('queued','running') for r in native.issue_task_runs(settings,config['source_issue']))):
            raise ValueError('independent authentic CTO and complete immutable source reads required')
        base=b.issue_base(config['source_issue'])
        if base['base_sha']!=original_base_sha:raise ValueError('original recovery base moved')
        config['base']=base
        config['diagnostic_read_evidence']=reads
        state=dict(stage='issue_intent',owner=config['cto'],execution_authorized=False,release_homologated=False)
        if parser_repair:state['intake_repair']=parser_repair
        with b.db() as con:
            current=handoffs.load(con,source)
            current_route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            if (current!=row or current_route!=route
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('source changed before replan registration')
            if parser_repair:
                stored=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
                if json.loads(stored['config'])!={} or json.loads(stored['state'])!=prior_state:
                    raise ValueError('parser repair intent drift')
                con.execute('UPDATE technical_remediation_plans SET config=?,state=? WHERE source_task=?',
                            (json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True),source))
            else:
                con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',
                            (source,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))
            route['enabled']=False;con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),row['issue_id']))
            data['exhausted_revision_proposal']=data['test_revision_proposal']
            data['required_action']='cto_propose_distinct_remediation_then_independent_techlead_review'
            data['technical_remediation_plan']=dict(source_task=source,original_depth=2,execution_authorized=False)
            handoffs.save(con,source,row['issue_id'],'technical_decision_required',route['cto'],data,time.time())
        return state


def validate_result(config,state,task,body,reads):
    role='cto' if state['stage']=='awaiting_plan' else 'reviewer'
    if (task.get('status')!='completed' or task.get('issue_id')!=state['issue_id']
            or task.get('agent_id')!=config[role] or task.get('wakeup_id')!=state['wakeup_id']
            or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in config['required_paths'])):
        raise ValueError('exact independent full-read planning execution required')
    sha=digest(config) if role=='cto' else state['plan_sha256']
    Draft202012Validator(schema('plan' if role=='cto' else 'review',sha,sorted(config['criteria']))).validate(body)
    if role=='cto':
        if body['action']=='retain_hold':
            if body['steps']:raise ValueError('hold cannot contain execution steps')
            return False
        if len(body['steps'])!=3:raise ValueError('complete recovery chain required')
        for i,(step,scope) in enumerate(zip(body['steps'],('new_tests_only','product_only','controller_only')),1):
            if (step['id']!='R'+str(i) or step['depends_on']!= ([] if i==1 else ['R'+str(i-1)])
                    or step['edit_scope']!=scope or set(step['criteria'])!=set(config['criteria'])):
                raise ValueError('unchanged full acceptance coverage and strict recovery dependencies required')
        return True
    return body['decision']=='approve_plan'


def instruction(config,state):
    common=('DELIVERY_STRUCTURED_DECISION_V1:technical\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['required_paths']))
    if state['stage']=='plan_dispatch':
        note=('CTO: propose a DISTINCT technical remediation plan, not a third recursive revision. '
            'Read all source. R1 repairs only the newly authored harness, preserving every test method/assertion and baseline; '
            'verify separate initial/settled observations and count only /service-mode. Require independent test review and genuine Red '
            'on the original base. R2 implements only after approved frozen tests. R3 requires full suite, independent product review, '
            'PR/CI, deploy and browser QA on the same SHA. Include ALL acceptance IDs in ALL steps. '
            'No edits, retry reset, CEO technical question, execution or delivery approval. '
            'Return compact schema JSON or retain_hold with no steps.\nDELIVERY_REMEDIATION_PLAN_V1:'+digest(config)+'\n'+
            ''.join('DELIVERY_REMEDIATION_CRITERION:'+k+'\n' for k in sorted(config['criteria'])))
        note+='\nDELIVERY_TYPED_REMEDIATION_V1:plan:'+digest(config)
        if state.get('plan_revisions'):
            note=('CTO: inspect source and correct the rejected plan. Preserve ALL criteria, immutable baseline/snapshots, '
                  'Red, independent reviews and same-SHA PR/CI/deploy/QA. R1 tests; R2 product; R3 controller, strictly dependent. '
                  'Distinct proposal or retain_hold; no edits, reset or execution. reason<=600, objective<=240. '
                  '\nDELIVERY_REMEDIATION_PLAN_V1:'+digest(config)+'\n'+
                  ''.join('DELIVERY_REMEDIATION_CRITERION:'+k+'\n' for k in sorted(config['criteria']))+
                  'DELIVERY_TYPED_REMEDIATION_V1:plan:'+digest(config)+'\n')
            try:import planning_revision_context
            except ImportError:from broker import planning_revision_context
            note+=planning_revision_context.reference(config,state)
    else:
        note=('INDEPENDENT TECH LEAD: review this EXACT CTO plan against ALL approved acceptance and immutable source. '
            'Reject weakened/removal of tests, omitted criteria, permission to edit frozen files, depth reset, bypassed Red/reviews/CI/QA, '
            'or product workaround for a defective harness. Approve only a distinct fully scoped recovery contract. '
            'No editing, execution or delivery authority. Plan data: '+json.dumps(state['plan'],separators=(',',':'))+
            '\nDELIVERY_REMEDIATION_REVIEW_V1:'+state['plan_sha256'])
        note+='\nDELIVERY_TYPED_REMEDIATION_V1:review:'+state['plan_sha256']
        note+='\nDELIVERY_REMEDIATION_LENGTH_FEEDBACK_V1'
        note+=('\nPHASE CONTRACT: this is plan review, not test or delivery review. '
            'Assess the proposed future R1/R2/R3 steps and their gates. Current frozen tests '
            'are deliberately unchanged. R1 Red, repaired tests and product Green cannot '
            'exist yet because plan approval grants no execution authority. Do not reject '
            'merely for their current absence when the plan explicitly requires them before '
            'product edits. Request changes for a concrete missing or contradictory planned '
            'gate, scope, dependency or acceptance criterion, not a gate already present. '
            'Approve only a sound plan; unsupported test-defect certainty still requires '
            'an explicit experiment or evidence-producing R1 step. Approval never proves '
            'that experiment succeeded or waives the later independent test review.')
    if config.get('amendment',{}).get('kind')=='timer_provenance':
        note+='\nTIMER ATTRIBUTION EVIDENCE: '+json.dumps(config['experiment']['proof']['facts'],separators=(',',':'))
        note+=' The unchanged harness counts legitimate board polling as a probe interval. '
        note+='R1 must preserve every method/assertion and repair attribution behaviorally, not subtract a constant, '
        note+='ignore timers, hard-code source lines or remove polling from product. Calibration must accept legitimate '
        note+='background polling and reject probe timeout/interval callbacks, including indicator-only callbacks. '
        note+='This observation is not Green. Fresh Red, independent test/product reviews and every R2/R3 gate remain.'
    elif config.get('amendment',{}).get('kind')=='request_scope':
        note+='\nCONTRACT AMENDMENT: the fixed immutable experiment reproduced three assertion failures because '
        note+='the NEW-test helper counted all page requests instead of GET /service-mode. The in-memory scoped '
        note+='helper passed the same tests, background traffic and all duplicate/negative controls. Propose a NEW '
        note+='tests-only submission preserving every method/assertion. Require background-traffic calibration, '
        note+='genuine Red on the original base and independent test review. This experiment is not Green. '
        note+='No depth reset, historical approval, product workaround or CEO technical question. All R2/R3 gates remain.'
    elif config.get('amendment') and config['amendment'].get('kind')!='inherited_frozen_suite':
        note+='\nCONTRACT AMENDMENT: the immutable embedded NEW-test harness fails Node syntax compilation; '
        note+='do not rewrite product to accommodate invalid test code. Repair harness only in a NEW submission, '
        note+='preserving every method/assertion, original base and depth 2. Require harness compilation and '
        note+='behavioral negative controls before genuine Red and independent test review. Historical approvals '
        note+='do not approve this amended submission. All R2/R3 gates and every criterion remain required.'
    if config.get('intake_kind') == 'exhausted_frozen_suite_v1':
        if state['stage'] == 'plan_dispatch' and not state.get('plan_revisions'):
            note = ('CTO: independently diagnose this frozen full-suite failure and propose a DISTINCT '
                'recovery contract, or retain_hold if NEW-test repair is unsupported. A numeric mismatch '
                'does not prove a test defect. Read ALL selected immutable source files. Never make '
                'product generate extra requests to accommodate a contradictory NEW expectation. '
                'R1 repairs only originally NEW tests in a fresh submission, preserving baseline '
                'tests and behavioral coverage; require genuine Red on the original Git base and '
                'independent test review. R2 product implementation follows only approved immutable tests. '
                'R3 full Green, independent product review, PR/CI, deploy and browser QA on the same SHA. '
                'ALL acceptance IDs in ALL strictly dependent steps. No edits, third recursive revision, '
                'depth/attempt reset, execution, delivery approval or CEO technical question. '
                'Return compact schema JSON or retain_hold with no steps.\n'
                'DELIVERY_REMEDIATION_PLAN_V1:' + digest(config) + '\n' +
                ''.join('DELIVERY_REMEDIATION_CRITERION:' + k + '\n' for k in sorted(config['criteria'])) +
                'DELIVERY_TYPED_REMEDIATION_V1:plan:' + digest(config))
    if config.get('amendment',{}).get('kind')=='inherited_frozen_suite':
        note+='\nGENERIC INHERITED-SUITE RECOVERY: the paired immutable experiment reproduced the same '
        note+='full-suite failure without changing observations. It proves no test defect or Green. '
        note+='Assess the actual NEW harness and product; do not apply service-mode recipes. '
        note+='Preserve every existing test method/assertion. Propose behavioral experiment/negative controls '
        note+='within fresh R1, or retain_hold if unsupported. No baseline edits or weakened expectations.'
    if state['stage']=='plan_dispatch':
        note+='\nDELIVERY_REMEDIATION_PLAN_LENGTH_FEEDBACK_V1\n'
    result=common+note
    if config.get('intake_kind')=='rejected_remediation_r1_v1':
        note=('R1 was rejected by independent review and CTO requested a correction. '
            'Preserve all original criteria, base, test methods and assertions. '
            'Propose a fresh R1/R2/R3 plan; no recursive revision, depth reset or old approval reuse. '
            'R1 repairs the NEW tests only and requires fresh Red and independent review. '
            'R2 product-only follows approved exact tests; R3 requires full Green, independent review, '
            'PR/CI/deploy/browser QA on the same SHA. Include ALL acceptance IDs in EACH step. '
            'Return compact schema JSON or retain_hold.\n'
            'CTO correction claim (assess immutable source, not unquestionable truth): '+json.dumps(config['diagnostic_decision']['reason'])+'\n'+
            'DELIVERY_REMEDIATION_PLAN_V1:'+digest(config)+'\n'+
            ''.join('DELIVERY_REMEDIATION_CRITERION:'+k+'\n' for k in sorted(config['criteria']))+
            'DELIVERY_TYPED_REMEDIATION_V1:plan:'+digest(config)+'\n') if state['stage']=='plan_dispatch' else note
        result=common+note
    # Intake-specific notes replace the generic note above. Bind the bounded
    # transport correction only AFTER that replacement, so every plan intake
    # receives the same durable one-attempt policy without weakening its schema.
    if state['stage']=='plan_dispatch':
        marker='DELIVERY_REMEDIATION_PLAN_LENGTH_FEEDBACK_V1'
        if marker not in result:
            result+='\n'+marker+'\n'
        result+='\nProse limits: reason<=600 characters; each objective<=240 characters. Preserve all gates and criteria.\n'
        if state.get('plan_validation_feedback'):
            result+='\nCONTROLLER VALIDATION FEEDBACK: '+json.dumps(state['plan_validation_feedback'],separators=(',',':'))+'\n'
    prefix='DELIVERY_PLANNING_START '+('0'*64)+'\nSource: '+config['source_task']+'\n'
    if len(result)+len(prefix)>4000:raise ValueError('split remediation context before dispatch')
    return result


def advance(config,state,runs,fx,now=None):
    now=time.time() if now is None else now
    if state['stage'] in ('plan_approved','blocked'):return state
    if state['stage']=='issue_intent':
        try:item=fx.issue(config)
        except (TimeoutError,urllib.error.URLError):
            return {**state,'stage':'observe_issue','observation_started':now}
        return {**state,'issue_id':item['id'],'identifier':item.get('identifier'),'stage':'plan_dispatch'}
    if state['stage']=='observe_issue':
        try:item=fx.issue(config,allow_create=False)
        except (TimeoutError,urllib.error.URLError):
            if now-state['observation_started']<600:return state
            item=None
        if item is None:
            return {**state,'stage':'blocked','owner':config['cto'],
                    'required_action':'CTO reconcile absent or unobservable exact replan issue; no repeated POST'}
        return {**state,'issue_id':item['id'],'identifier':item.get('identifier'),'stage':'plan_dispatch'}
    if state['stage'] in ('plan_dispatch','review_dispatch'):
        role='cto' if state['stage']=='plan_dispatch' else 'reviewer'
        try:
            wake=fx.wake(config,state,config[role],instruction(config,state))
        except DispatchObservationRequired:
            return {**state,'stage':'observe_dispatch','dispatch_phase':state['stage'],
                    'owner':config[role],'observation_started':now}
        if wake is None:return state
        return {**state,'stage':'awaiting_plan' if role=='cto' else 'awaiting_review',
                'owner':config[role],'wakeup_id':wake['id'],'dispatched_at':now}
    if state['stage']=='observe_dispatch':
        phase=state['dispatch_phase'];target=config['cto' if phase=='plan_dispatch' else 'reviewer']
        previous={**state,'stage':phase}
        try:
            wake=fx.observe_wake(config,previous,target,instruction(config,previous))
        except (TimeoutError,urllib.error.URLError):
            if now-state['observation_started']<600:return state
            wake=None
        if wake is None:
            return {**state,'stage':'blocked','owner':config['cto'],
                    'required_action':'CTO reconcile absent or unobservable exact wakeup; no repeated POST'}
        return {**state,'stage':'awaiting_plan' if phase=='plan_dispatch' else 'awaiting_review',
                'owner':target,'wakeup_id':wake['id'],'dispatched_at':state['observation_started']}
    tasks=[t for t in runs if t.get('wakeup_id')==state['wakeup_id']]
    if len(tasks)>1:raise ValueError('duplicate recovery planning wakeup')
    if not tasks or tasks[0]['status'] in ('queued','running'):
        age=now-state['dispatched_at']
        if age>=1800 or (not tasks and age>=600):
            return {**state,'stage':'blocked','owner':config['cto'],
                    'category':'PlanningProgressDeadline','observed_task':tasks[0]['id'] if tasks else None,
                    'required_action':'CTO inspect exact native planning/wakeup state; no identical restart'}
        return state
    task=fx.task(tasks[0]['id'],state['owner'])
    body=fx.result(task);reads=fx.reads(task)
    correction=semantic_plan_correction(config,state,task,body,reads)
    if correction is not None:return correction
    accepted=validate_result(config,state,task,body,reads)
    if not accepted:
        if state['stage']=='awaiting_review':
            revisions=state.get('plan_revisions',[])+[dict(plan=state['plan'],plan_sha256=state['plan_sha256'],
                plan_task=state['plan_task'],plan_wakeup=state['plan_wakeup'],review=body,
                review_task=task['id'],review_wakeup=state['wakeup_id'])]
            new={**state,'plan_revisions':revisions,'owner':config['cto'],'decision_task':task['id']}
            if len(revisions)>2:
                return {**new,'stage':'blocked','required_action':'CTO diagnose exhausted distinct plan corrections; no identical retry'}
            new.update(stage='plan_dispatch',required_action='CTO revise exact independently rejected plan')
            for field in ('wakeup_id','dispatched_at'):new.pop(field,None)
            return new
        return {**state,'stage':'blocked','owner':config['cto'],'decision_task':task['id'],
                'required_action':'CTO resolve retained hold or rejected recovery plan; no identical retry'}
    if state['stage']=='awaiting_plan':
        if any(digest(body)==r['plan_sha256'] for r in state.get('plan_revisions',[])):
            return {**state,'stage':'blocked','owner':config['cto'],'decision_task':task['id'],
                    'required_action':'CTO proposal repeats independently rejected plan; no identical retry'}
        return {**state,'stage':'review_dispatch','plan':body,'plan_sha256':digest(body),
                'plan_task':task['id'],'plan_wakeup':state['wakeup_id'],'owner':config['reviewer']}
    return {**state,'stage':'plan_approved','review':body,'review_task':task['id'],
            'owner':config['reviewer'],'required_action':'provision_exact_reviewed_remediation_contract_without_resetting_ancestry'}


def semantic_plan_correction(config,state,task,body,reads):
    """Return exact incomplete proposals to CTO twice, never approve or edit them."""
    if state['stage']!='awaiting_plan':return None
    try:validate_result(config,state,task,body,reads)
    except ValueError as error:
        if str(error) not in ('complete recovery chain required',
                'unchanged full acceptance coverage and strict recovery dependencies required'):raise
    else:return None
    # validate_result already proved native identity, complete reads and schema.
    history=state.get('plan_validation_rejections',[])
    fingerprint=digest(body)
    repeated=any(x['proposal_sha256']==fingerprint for x in history)
    entry=dict(task_id=task['id'],wakeup_id=state['wakeup_id'],proposal=body,
        proposal_sha256=fingerprint,execution_authorized=False)
    updated={**state,'plan_validation_rejections':history+[entry],'owner':config['cto']}
    if repeated or len(history)>=2:
        return {**updated,'stage':'blocked','category':'PlanSemanticCorrectionExhausted',
            'required_action':'CTO diagnose repeated or exhausted incomplete proposal; no identical retry'}
    feedback=dict(category='incomplete_recovery_chain',rejected_proposal_sha256=fingerprint,
        required_step_ids=['R1','R2','R3'],required_dependencies=[[],['R1'],['R2']],
        required_scopes=['new_tests_only','product_only','controller_only'],
        required_criteria_in_every_step=sorted(config['criteria']),attempt=len(history)+1,attempt_limit=2,
        execution_authorized=False)
    updated.update(stage='plan_dispatch',plan_validation_feedback=feedback,
        review_protocol='typed-remediation-semantic-correction-'+digest(feedback),
        required_action='CTO correct exact incomplete proposal; independent review still required')
    for field in ('wakeup_id','dispatched_at','category'):updated.pop(field,None)
    return updated


class Effects:
    def __init__(self,b):
        self.b=b;self.settings=json.loads((b.STATE/'native.json').read_text())
        self.native=handoff_runtime.Effects(b,self.settings);self.issues=NativeIssues(self.settings)
    def issue(self,c,*,allow_create=True):
        parent=self.issues.request('/issues/'+c['root_issue'])
        description=('TECHNICAL REMEDIATION PLANNING ONLY; original failed attempts and two revision generations remain preserved.\n'
            'Source: '+c['source_task']+'\nEvidence: '+digest(c)+'\nApproved acceptance (unchanged):\n'+
            '\n'.join(k+': '+v for k,v in c['criteria'].items())+
            '\nControlled diagnostic experiment facts: '+json.dumps(c['experiment']['proof']['facts'],separators=(',',':'))+
            '\nNo implementation, frozen-test editing, revision reset, release approval, merge or deployment authority. '
            'CTO proposes a scoped recovery; Tech Lead reviews independently. Preserve all historical receipts and baseline tests.')
        return self.issues.ensure(dict(title='Technical remediation plan '+digest(c)[:12],description=description,
            parent_issue_id=c['root_issue'],project_id=parent.get('project_id'),stage=1,status='todo'),allow_create=allow_create)
    def wake(self,c,s,target,note):
        try:
            return native.ensure_planning_start(self.settings,s['issue_id'],target,c['source_task'],
                digest(dict(evidence=digest(c),stage=s['stage'],plan=s.get('plan_sha256'),revision=len(s.get('plan_revisions',[])),protocol=s.get('review_protocol','typed-remediation-v1'))),note,
                allow_create=self.native.remaining_calls()>=16)
        except (TimeoutError,urllib.error.URLError):
            raise DispatchObservationRequired() from None
    def observe_wake(self,c,s,target,note):
        return native.ensure_planning_start(self.settings,s['issue_id'],target,c['source_task'],
            digest(dict(evidence=digest(c),stage=s['stage'],plan=s.get('plan_sha256'),revision=len(s.get('plan_revisions',[])),protocol=s.get('review_protocol','typed-remediation-v1'))),note,allow_create=False)
    def task(self,tid,agent):return native.task_record(self.settings,tid,agent)
    def reads(self,task):return self.native.read_evidence(task)
    def result(self,task):
        raw=(task.get('result') or {}).get('output')
        if not isinstance(raw,str) or not 1<=len(raw)<=6000:
            raise ValueError('bounded completed recovery JSON required')
        return json.loads(raw)
    def publish(self,c,s):
        if not s.get('issue_id'):return
        handoff_runtime.publish(self.b,dict(issue_id=s['issue_id'],enabled=True,techlead=c['reviewer']),
            dict(stage=s['stage'],owner=s['owner'],source_task=c['source_task'],
                data=json.dumps(dict(required_action=s.get('required_action') or s['stage']))))


def mounts(b,binding):
    try:import generic_calibration_workflow
    except ImportError:from broker import generic_calibration_workflow
    calibration=generic_calibration_workflow.mounts(b,binding)
    if calibration:return calibration
    with b.db() as con:
        initialize(con)
        matches=[(json.loads(r[0]),json.loads(r[1])) for r in con.execute('SELECT config,state FROM technical_remediation_plans')
                 if json.loads(r[1]).get('issue_id')==binding['issue_id']]
    if not matches:return []
    if len(matches)!=1:raise ValueError('ambiguous remediation evidence')
    c,s=matches[0]
    if s['stage'] not in ('plan_dispatch','review_dispatch','observe_dispatch','awaiting_plan','awaiting_review') or s['owner']!=binding['agent_id']:
        raise ValueError('current readonly recovery role required')
    if c.get('intake_kind')=='rejected_remediation_r1_v1':
        try:import remediation_r1_feedback
        except ImportError:from broker import remediation_r1_feedback
        with b.db() as con:remediation_r1_feedback.validate_parent(con,c)
        labels=(b.docker('GET','/volumes/'+c['volume']) or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.test-first-task')!=c['source_task']:
            raise ValueError('immutable rejected R1 evidence ownership drift')
        return [dict(Type='volume',Source=c['volume'],Target='/evidence/candidate',ReadOnly=True)]
    labels=(b.docker('GET','/volumes/'+c['volume']) or {}).get('Labels',{})
    generic = c.get('intake_kind') == 'exhausted_frozen_suite_v1'
    completed=c.get('diagnostic_snapshot_kind')=='completed_frozen_validation' and (generic or c.get('amendment',{}).get('kind') in ('request_scope','timer_provenance'))
    if completed:
        with b.db() as con:
            snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(c['source_task'],)).fetchone()
            if generic:
                diagnosis=con.execute('SELECT receipt FROM frozen_suite_failures WHERE task_id=?',(c['source_task'],)).fetchone()
            else:
                diagnosis=con.execute('SELECT receipt FROM completed_validation_diagnoses WHERE source_task=?',(c['source_task'],)).fetchone()
        if (not snapshot or snapshot['volume']!=c['volume'] or snapshot['status']!='complete'
                or not diagnosis or json.loads(diagnosis[0]).get('volume')!=c['volume']
                or (not generic and json.loads(diagnosis[0]).get('status')!='diagnostic_only_not_approved')
                or (generic and any(c.get('historical_failure',{}).get(k)!=v for k,v in json.loads(diagnosis[0]).items()))):
            raise ValueError('exact completed validation diagnostic evidence required')
    if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=c['source_task']
            or not completed and labels.get('delivery-kit.diagnostic-only')!='true'):
        raise ValueError('immutable recovery snapshot ownership drift')
    return [dict(Type='volume',Source=c['volume'],Target='/evidence/candidate',ReadOnly=True)]


def reconcile_review_changes(b,source):
    """Controller maintenance: consume the SAME rejected review, not invent one."""
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            c,s=map(json.loads,row)
            if s.get('review_feedback_reconciliation'):return s
            if (s.get('stage')!='blocked' or s.get('category') or s.get('review_task')
                    or not s.get('decision_task') or s.get('plan_revisions')
                    or s.get('required_action')!='CTO resolve retained hold or rejected recovery plan; no identical retry'
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('idle legacy independent review rejection required')
        fx=Effects(b);task=fx.task(s['decision_task'],c['reviewer'])
        runs=native.issue_task_runs(fx.settings,s['issue_id'])
        if (any(t['status'] in ('queued','running') for t in runs)
                or [t['id'] for t in runs if t.get('wakeup_id')==s['wakeup_id']]!=[task['id']]):
            raise ValueError('one unchanged terminal independent review required')
        body=fx.result(task);pending={**s,'stage':'awaiting_review','owner':c['reviewer']}
        if body.get('decision')!='request_changes' or validate_result(c,pending,task,body,fx.reads(task)):
            raise ValueError('same exact rejected plan required')
        new=advance(c,pending,[task],fx)
        new['review_feedback_reconciliation']=dict(previous=s,review_task=task['id'],model_calls=0,
            delivery_approval=False,revision_depth_reset=False)
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=s:
                raise ValueError('review rejection changed')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new


def reconcile_semantic_plan_failure(b,source):
    """Consume the same legacy incomplete plan under the new bounded feedback.

    No synthesized proposal, review or evidence. Dispatch remains supervisor-owned.
    """
    with b.LOCK:
        with b.db() as con:
            c,s=map(json.loads,con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone())
            if s.get('semantic_feedback_reconciliation'):return s
            if (s.get('stage')!='blocked' or s.get('category')!='ValueError' or s.get('plan')
                    or s.get('execution_authorized') is not False
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('idle legacy incomplete plan hold required')
        fx=Effects(b);runs=native.issue_task_runs(fx.settings,s['issue_id'])
        matches=[t for t in runs if t.get('wakeup_id')==s['wakeup_id']]
        if len(matches)!=1 or any(t['status'] in ('queued','dispatched','running') for t in runs):
            raise ValueError('one completed legacy planning wakeup required')
        task=fx.task(matches[0]['id'],c['cto'])
        with b.db() as con:
            bound=con.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                (task['id'],c['cto'],s['issue_id'])).fetchall()
        if len(bound)!=1 or bound[0]['status']!='closed':raise ValueError('closed exact completed plan required')
        new=semantic_plan_correction(c,{**s,'stage':'awaiting_plan'},task,fx.result(task),fx.reads(task))
        if new is None or new['stage']!='plan_dispatch':raise ValueError('changed bounded semantic correction required')
        new['semantic_feedback_reconciliation']=dict(previous=s,task_id=task['id'],model_calls=0,
            execution_authorized=False,revision_depth_reset=False)
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=s:
                raise ValueError('semantic plan hold changed')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new


def capture_plan_length_failure(b,source):
    """Bind a durable proxy rejection to the exact closed native plan task.

    Capturing evidence does not dispatch or accept a plan. Unknown failures
    remain held; no conclusion is inferred from an ACP error alone.
    """
    try:import execution_diagnosis_recovery
    except ImportError:from broker import execution_diagnosis_recovery
    with b.LOCK:
        with b.db() as con:
            c,s=map(json.loads,con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone())
            if s.get('format_diagnosis'):return s['format_diagnosis']
            if (s.get('stage')!='blocked' or s.get('category')!='ValueError' or s.get('plan')
                    or s.get('plan_length_recovery') or s.get('execution_authorized') is not False
                    or not (c.get('amendment') or c.get('intake_kind')=='rejected_remediation_r1_v1')
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('idle unapproved failed planning task required')
        fx=Effects(b);runs=native.issue_task_runs(fx.settings,s['issue_id'])
        matches=[t for t in runs if t.get('wakeup_id')==s['wakeup_id']]
        if len(matches)!=1 or any(t['status'] in ('queued','dispatched','running') for t in runs):
            raise ValueError('one terminal planning wakeup required')
        task=fx.task(matches[0]['id'],c['cto']);reads=fx.reads(task)
        if (task.get('status')!='failed' or task.get('agent_id')!=c['cto']
                or task.get('issue_id')!=s['issue_id'] or task.get('wakeup_id')!=s['wakeup_id']
                or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in c['required_paths'])):
            raise ValueError('authentic failed plan and complete immutable reads required')
        with b.db() as con:
            bindings=con.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                (task['id'],c['cto'],s['issue_id'])).fetchall()
        if len(bindings)!=1 or bindings[0]['status']!='closed':raise ValueError('exact closed planning binding required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        rejection=execution_diagnosis_recovery.format_rejection(b,bindings[0]['request_id'],expected_image=proxy['Image'])
        rejection={**rejection,'execution_id':bindings[0]['request_id']}
        if (rejection.get('category')!='typed_schema_maxLength' or rejection.get('operation')!='rejected_typed_decision_adapter_v1'
                or rejection.get('delivery_approval') is not False or rejection.get('worker_tool_executed') is not False):
            raise ValueError('durable length-only rejection required')
        diagnostic=dict(category='typed_schema_maxLength',request_id=bindings[0]['request_id'],failed_task=task['id'],
            retry_authorized=False,rejection=rejection,proxy_image=proxy['Image'],read_evidence=reads)
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=s:
                raise ValueError('planning hold changed during capture')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',
                (json.dumps({**s,'format_diagnosis':diagnostic},sort_keys=True),source))
        return diagnostic


def reconcile_plan_length_failure(b,source,rejection):
    """One changed transport policy after a correlated plan-schema rejection.

    Trusted operator supplies the sanitized proxy receipt. An invalid plan is
    never accepted; the native framework dispatches a fresh readonly proposal.
    """
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            c,s=map(json.loads,row)
            if s.get('plan_length_recovery'):return s
            diagnostic=s.get('format_diagnosis') or {};shape=rejection.get('response_shape') or {}
            if (s.get('stage')!='blocked' or s.get('category')!='ValueError'
                    or not (c.get('amendment') or c.get('intake_kind')=='rejected_remediation_r1_v1')
                    or diagnostic.get('category')!='typed_schema_maxLength' or diagnostic.get('retry_authorized') is not False
                    or rejection.get('execution_id')!=diagnostic.get('request_id')
                    or rejection.get('category')!='typed_schema_maxLength'
                    or rejection.get('operation')!='rejected_typed_decision_adapter_v1'
                    or rejection.get('delivery_approval') is not False or rejection.get('worker_tool_executed') is not False
                    or shape.get('parsed') is not True or shape.get('terminal') is not True
                    or shape.get('submissions')!=1 or shape.get('expected_tool') is not True
                    or shape.get('arguments_json_valid') is not True or shape.get('arguments_schema_valid') is not False
                    or shape.get('content_shape')!='empty' or shape.get('content_chars')!=0
                    or s.get('execution_authorized') is not False or s.get('plan')
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('idle exact rejected readonly plan length failure required')
            bindings=con.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) '
                'WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                (diagnostic['failed_task'],c['cto'],s['issue_id'])).fetchall()
            if len(bindings)!=1 or bindings[0]['request_id']!=diagnostic['request_id'] or bindings[0]['status']!='closed':
                raise ValueError('exact closed planning transport required')
        fx=Effects(b);task=fx.task(diagnostic['failed_task'],c['cto']);reads=fx.reads(task)
        if (task['status']!='failed' or task['issue_id']!=s['issue_id'] or task['wakeup_id']!=s['wakeup_id']
                or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in c['required_paths'])
                or any(t['status'] in ('queued','dispatched','running') for t in native.issue_task_runs(fx.settings,s['issue_id']))):
            raise ValueError('authentic failed plan with complete reads and no pending task required')
        candidate={**s,'stage':'plan_dispatch','owner':c['cto'],'review_protocol':'typed-remediation-plan-length-feedback-v1'}
        if '\nDELIVERY_REMEDIATION_PLAN_LENGTH_FEEDBACK_V1\n' not in instruction(c,candidate):
            raise ValueError('changed bounded plan feedback instruction required')
        proof=dict(operation='correlated_remediation_plan_length_recovery_v1',previous=s,
            rejection=rejection,config_sha256=digest(c),attempt_limit=1,
            implementation_authorized=False,limits_increased=False,revision_depth_reset=False)
        new={**candidate,'plan_length_recovery':proof,'required_action':'CTO fresh readonly plan under one bounded prose correction; independent review remains required'}
        for field in ('wakeup_id','dispatched_at','category'):new.pop(field,None)
        with b.db() as con:
            current=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            if list(map(json.loads,current))!=[c,s] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
                raise ValueError('plan hold changed before recovery registration')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new


def reconcile_correction_context(b,source):
    """Restore an undispatched correction from the SAME valid rejected review.

    The full rejected revision remains in storage and is presented through an
    exact dispatch-bound reference; no criteria or framework limit is increased.
    """
    with b.LOCK:
        with b.db() as con:
            c,s=map(json.loads,con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone())
            if s.get('correction_context_recovery'):return s
            history=s.get('plan_revisions') or []
            if (s.get('stage')!='blocked' or s.get('category')!='ValueError' or not 1<=len(history)<=2
                    or s.get('wakeup_id') or s.get('execution_authorized') is not False
                    or s.get('decision_task')!=history[-1].get('review_task')
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('idle undispatched rejected-review correction required')
        last=history[-1];fx=Effects(b);task=fx.task(last['review_task'],c['reviewer']);body=fx.result(task)
        pending={**s,'stage':'awaiting_review','owner':c['reviewer'],'wakeup_id':last['review_wakeup'],
                 'plan_sha256':last['plan_sha256']}
        if (body!=last['review'] or body.get('decision')!='request_changes'
                or validate_result(c,pending,task,body,fx.reads(task))
                or any(t['status'] in ('queued','dispatched','running') for t in native.issue_task_runs(fx.settings,s['issue_id']))):
            raise ValueError('same exact independent rejection required')
        candidate={**s,'stage':'plan_dispatch','owner':c['cto']};note=instruction(c,candidate)
        try:import planning_revision_context
        except ImportError:from broker import planning_revision_context
        probe={**candidate,'stage':'awaiting_plan','wakeup_id':'local-qualification-only'}
        expanded=planning_revision_context.expand(note,s['issue_id'],dict(agent_id=c['cto'],wakeup_id=probe['wakeup_id']),
            lambda _:dict(config=json.dumps(c),state=json.dumps(probe)))
        if json.dumps(last,sort_keys=True,separators=(',',':')) not in expanded:
            raise ValueError('lossless exact plan/review presentation required')
        candidate['correction_context_recovery']=dict(previous=s,operation='registered_correction_context_repair_v1',
            review_task=task['id'],instruction_sha256=hashlib.sha256(note.encode()).hexdigest(),
            context_sha256=planning_revision_context.digest(last),expanded_note_characters=len(expanded),
            note_characters=len(note),framework_limit=4000,limits_increased=False,implementation_authorized=False)
        candidate.pop('category',None)
        candidate['required_action']='CTO correct exact independently rejected plan; complete artifacts preserved'
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=s:
                raise ValueError('correction context changed before registration')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(candidate,sort_keys=True),source))
        return candidate


def tick(b):
    try:import generic_calibration_workflow
    except ImportError:from broker import generic_calibration_workflow
    generic_calibration_workflow.tick(b)
    try:import frozen_diagnosis_format_recovery
    except ImportError:from broker import frozen_diagnosis_format_recovery
    frozen_diagnosis_format_recovery.tick(b)
    try:import frozen_adjudication_spike
    except ImportError:from broker import frozen_adjudication_spike
    frozen_adjudication_spike.tick(b)
    try:import inherited_suite_intake
    except ImportError:from broker import inherited_suite_intake
    inherited_suite_intake.tick(b)
    try:import planning_review_observation
    except ImportError:from broker import planning_review_observation
    planning_review_observation.tick(b)
    try:import remediation_r1_feedback
    except ImportError:from broker import remediation_r1_feedback
    remediation_r1_feedback.tick(b)
    try:import generic_remediation_driver
    except ImportError:from broker import generic_remediation_driver
    generic_remediation_driver.tick(b)
    try:import timer_scope_replan
    except ImportError:from broker import timer_scope_replan
    timer_scope_replan.tick(b)
    try:import remediation_preparation
    except ImportError:from broker import remediation_preparation
    remediation_preparation.tick(b)
    try:import remediation_r2_issue
    except ImportError:from broker import remediation_r2_issue
    remediation_r2_issue.tick(b)
    try:import remediation_r2_preparation
    except ImportError:from broker import remediation_r2_preparation
    remediation_r2_preparation.tick(b)
    try:import remediation_product_context
    except ImportError:from broker import remediation_product_context
    remediation_product_context.tick(b)
    try:import remediation_native_context
    except ImportError:from broker import remediation_native_context
    remediation_native_context.tick(b)
    try:import remediation_admission
    except ImportError:from broker import remediation_admission
    remediation_admission.tick(b)
    try:import remediation_dispatch
    except ImportError:from broker import remediation_dispatch
    remediation_dispatch.tick(b)
    with b.db() as con:
        initialize(con)
        busy=con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
        candidates=con.execute("SELECT source_task,data FROM delivery_handoffs WHERE stage='test_revision_required'").fetchall() if not busy else []
    for candidate in candidates:
        data=json.loads(candidate['data'])
        generic = not data.get('service_mode_schema_evidence')
        if generic:
            try:import exhausted_suite_intake
            except ImportError:from broker import exhausted_suite_intake
            with b.db() as con:
                if con.execute('SELECT 1 FROM technical_remediation_plans WHERE source_task=?',(candidate['source_task'],)).fetchone():continue
                if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='test_revision_trials'").fetchone():continue
                row=con.execute('SELECT issue_id FROM delivery_handoffs WHERE source_task=?',(candidate['source_task'],)).fetchone()
                base_row=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(row[0],)).fetchone()
                if not base_row:continue
                def load_trial(issue):
                    trial=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
                    return json.loads(trial[0]) if trial else None
                try:exhausted_suite_intake.ancestry(row[0],json.loads(base_row[0])['base_sha'],load_trial)
                except (ValueError,KeyError):continue
        try:
            if generic:exhausted_suite_intake.register(b,candidate['source_task'])
            else:register(b,candidate['source_task'])
        except Exception as error:
            with b.db() as con:
                initialize(con)
                # A repeated semantic rejection cannot become an unbounded
                # registration loop. No issue or worker was authorized.
                state=dict(stage='blocked',owner=data.get('target'),category=type(error).__name__,
                    required_action='CTO diagnose rejected remediation intake; no identical retry',
                    execution_authorized=False,release_homologated=False)
                con.execute('INSERT OR IGNORE INTO technical_remediation_plans VALUES(?,?,?)',
                    (candidate['source_task'],'{}',json.dumps(state,sort_keys=True)))
    with b.db() as con:
        rows=con.execute('SELECT source_task,config,state FROM technical_remediation_plans').fetchall()
    fx=Effects(b)
    for row in rows:
        c,s=json.loads(row['config']),json.loads(row['state'])
        if not c:continue
        if s['stage'] in ('blocked','plan_approved'):
            projection=s
            if s['stage']=='plan_approved' and c.get('intake_kind')=='exhausted_frozen_suite_v1':
                with b.db() as con:
                    driver=con.execute('SELECT state FROM generic_remediation_drivers WHERE source_task=?',(row['source_task'],)).fetchone()
                if driver:projection={**s,**json.loads(driver[0])}
            try:fx.publish(c,projection)
            except Exception:pass  # metadata cannot change the authoritative hold/approval
            continue
        with b.LOCK:
            try:
                runs=native.issue_task_runs(fx.settings,s['issue_id']) if s.get('issue_id') else []
                new=advance(c,s,runs,fx)
            except Exception as error:
                new={**s,'stage':'blocked','owner':c['cto'],'category':type(error).__name__,
                     'required_action':'CTO diagnose exact recovery planning failure; no identical retry'}
            with b.db() as con:
                current=con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(row['source_task'],)).fetchone()
                if json.loads(current[0])!=s:raise ValueError('concurrent remediation transition')
                con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',
                            (json.dumps(new,sort_keys=True),row['source_task']))
            try:fx.publish(c,new)
            except Exception:pass  # retry presentation on next tick; never restart a task
