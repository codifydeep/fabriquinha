"""Persistent producer incident -> CTO -> fixed experiment -> independent review.

Only a sponsored data submission can resume; no author execution, test change,
Red/Green, merge, deploy or delivery approval is conferred by this lane.
"""
import hashlib
import json
import os
import time
import uuid
import urllib.error
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from generic_harness_calibration import digest,require
import calibration_incident_contract as contract
import structured_rejection_receipts
from calibration_transport_probe import SOURCES,source_hashes
try:import handoffs,calibration_incident_job as jobs
except ImportError:from broker import handoffs,calibration_incident_job as jobs


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_incidents(incident_id TEXT PRIMARY KEY,config TEXT,state TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS calibration_incident_occurrences(incident_id TEXT,execution_id TEXT,config TEXT,PRIMARY KEY(incident_id,execution_id))')
    con.execute('CREATE TABLE IF NOT EXISTS calibration_incident_enrollment_errors(issue_id TEXT,author_task TEXT,source_state_sha256 TEXT,category TEXT,at REAL,PRIMARY KEY(issue_id,author_task))')
    con.execute('CREATE TABLE IF NOT EXISTS calibration_incident_lookup_events(id INTEGER PRIMARY KEY,issue_id TEXT,author_task TEXT,source_state_sha256 TEXT,category TEXT,at REAL)')


def prepare(c,s,task,binding,rejection,sources):
    for value in (c['issue_id'],c['author_task'],c['cto'],c['reviewer'],task['id'],binding['request_id']):
        require(str(uuid.UUID(value))==value)
    require(c['cto']!=c['reviewer'] and s.get('stage')=='blocked' and s.get('category')=='bundle_task_failed'
        and s.get('execution_authorized') is False and s.get('delivery_approval') is False
        and task.get('id')==s.get('observed_task') and task.get('wakeup_id')==s.get('wakeup_id')
        and task.get('status')=='failed' and task.get('agent_id')==c['cto'] and task.get('issue_id')==c['issue_id']
        and binding.get('task_id')==task['id'] and binding.get('issue_id')==c['issue_id']
        and binding.get('agent_id')==c['cto'] and binding.get('status')=='closed'
        and binding.get('scope','').split(':')[-2:]==['planning',task['id']])
    expected=structured_rejection_receipts.from_event(dict(event='model_proxy_request',status=502,
        category='structured_decision_response_invalid',execution_id=binding['request_id'],call_number=rejection.get('call_number'),
        structured_rejection_category=rejection.get('category'),structured_rejection_diagnostic=rejection.get('diagnostic')))
    require(expected==rejection and rejection['category']=='calibration_response_invalid'
        and isinstance(rejection['diagnostic'],dict) and set(sources)==set(SOURCES))
    diagnostic=rejection['diagnostic']
    # Response/task IDs are occurrences, not a fresh retry budget. Only a new
    # source/validator or closed diagnostic class creates a distinct incident.
    failure_class={k:v for k,v in diagnostic.items() if k!='upstream_sha256'}
    key=digest(dict(source=digest(c),validators=sources,failure_class=failure_class))
    return dict(incident_id=key,source_config_sha256=digest(c),source_state_sha256=digest(s),
        origin_issue_id=c['issue_id'],author_task=c['author_task'],cto=c['cto'],reviewer=c['reviewer'],
        failed_task=task['id'],failed_execution=binding['request_id'],old_wakeup=s['wakeup_id'],
        manifest_sha256=c['prepared']['manifest_sha256'],rejection=rejection,validator_sources=sources)


def register(con,cfg):
    initialize(con);key=cfg['incident_id']
    row=con.execute('SELECT config,state FROM calibration_incidents WHERE incident_id=?',(key,)).fetchone()
    old=con.execute('SELECT config FROM calibration_incident_occurrences WHERE incident_id=? AND execution_id=?',
        (key,cfg['failed_execution'])).fetchone()
    if old:require(json.loads(old[0])==cfg)
    else:
        con.execute('INSERT INTO calibration_incident_occurrences VALUES(?,?,?)',(key,cfg['failed_execution'],json.dumps(cfg,sort_keys=True)))
    if row:
        original,state=map(json.loads,row)
        if original!=cfg and not old:
            state.update(stage='blocked',owner=original['cto'],category='repeated_incident_without_new_evidence',
                current_source_state_sha256=cfg['source_state_sha256'],
                required_action='CTO obtain genuinely changed evidence; identical incident cannot sponsor another submission')
            con.execute('UPDATE calibration_incidents SET state=? WHERE incident_id=?',(json.dumps(state,sort_keys=True),key))
    else:
        state=dict(stage='issue_pending',owner=cfg['cto'],execution_authorized=False,delivery_approval=False,
            required_action='Create one source-bound transport SPIKE; no author retry')
        con.execute('INSERT INTO calibration_incidents VALUES(?,?,?)',(key,json.dumps(cfg,sort_keys=True),json.dumps(state,sort_keys=True)))
    con.commit();return state


def context(cfg,s,phase):
    return contract.context(phase,digest(cfg),cfg['source_config_sha256'],
        digest(s['prior_hold']['value']) if phase=='evidence_diagnosis' else
        digest(s['cto_decision']['value']) if phase=='review' else None,digest(s['probe']) if phase!='diagnosis' else None)


def instruction(cfg,s,phase):
    diagnostic=cfg['rejection']['diagnostic']
    facts=dict(failed_task=cfg['failed_task'],failed_execution=cfg['failed_execution'],
        diagnostic=diagnostic,manifest_sha256=cfg['manifest_sha256'])
    note=contract.capsule(context(cfg,s,phase))+(
        'TECHNICAL TRANSPORT INCIDENT ONLY. '+('Independent Tech Lead evidence review. ' if phase=='review' else 'CTO diagnosis. ')+
        'Analyze only these controller-supplied receipts. No tools, product decisions, file edits, tests, '
        'shell, administration or credentials. Historical response bytes were not preserved: their hash '
        'does NOT prove a root cause. historical_cause_proven must remain false. The only permitted '
        'experiment is fixed_transport_probe_v1: synthetic terminal trailers and durable sanitized receipt '
        'checks in a no-network/no-credentials disposable container. It does not execute product tests. '
        'No assertion weakening, baseline changes, author restart or retry-budget reset. '
        'Return only the exact incident JSON schema. reason<=900 characters. '+
        ('Choose request_transport_probe or retain_technical_hold. ' if phase=='diagnosis' else
         'A new fixed experiment has now run; do not require the lost historical response to evaluate CURRENT transport. '
         'Choose submit_probe_for_review to let the independent Tech Lead evaluate a data-only submission, '
         'or retain_technical_hold with the remaining measurable concern. This is not historical root-cause proof. '
         if phase=='evidence_diagnosis' else
         'Choose sponsor_data_submission only if the actual experiment supports one NEW calibration data submission '
         'on the SAME immutable snapshot, with every later calibration/TDD/review gate unchanged; otherwise retain_technical_hold. ')+
        'All authorization/approval flags remain false. Facts: '+json.dumps(facts,separators=(',',':')))
    if phase!='diagnosis':
        proof=json.loads(s['probe']['output'])
        if phase=='review':note+='\nCTO proposal: '+json.dumps(s['cto_decision']['value'],separators=(',',':'))
        else:note+='\nPrior hold preserved: '+json.dumps(s['prior_hold']['value'],separators=(',',':'))
        note+='\nActual fixed experiment: '+json.dumps({k:proof[k] for k in ('operation','passed','checks','historical_cause_proven','product_tests_executed')},separators=(',',':'))
    require(len(note)<=3800);return note


def validate_decision(cfg,s,phase,task,decision):
    actor=cfg['reviewer'] if phase=='review' else cfg['cto']
    require(decision['task_id']==task['id'] and decision['agent_id']==actor and task.get('agent_id')==actor
        and task.get('issue_id')==s['issue_id'] and task.get('wakeup_id')==s['wakeup_id'] and task.get('status')=='completed')
    Draft202012Validator(contract.schema(context(cfg,s,phase))).validate(decision['value'])


def advance(con,key,fx,*,now=None):
    now=time.time() if now is None else now
    row=con.execute('SELECT config,state FROM calibration_incidents WHERE incident_id=?',(key,)).fetchone()
    require(row is not None);cfg,s=map(json.loads,row)
    probe_applicable=cfg['rejection']['diagnostic']['category']=='invalid_transport_or_tool'
    enrich=(probe_applicable and s['stage']=='blocked' and s.get('category')=='technical_hold_retained'
        and s.get('observed_phase')=='diagnosis' and not s.get('evidence_addendum_consumed'))
    if s['stage']=='resubmission_sponsored' or (s['stage']=='blocked' and not enrich):return s
    def save(**changes):
        s.update(changes);con.execute('UPDATE calibration_incidents SET state=? WHERE incident_id=?',(json.dumps(s,sort_keys=True),key));con.commit();return s
    def hold(category):return save(stage='blocked',owner=cfg['cto'],category=category,
        required_action='CTO diagnose '+category+'; preserve evidence, no identical dispatch or author retry')
    try:fx.verify(cfg)
    except (ValueError,KeyError,TypeError):return hold('incident_source_changed')
    if enrich:
        try:
            require(s['decision']['value']['action']=='retain_technical_hold')
            getattr(fx,'verify_hold',lambda *_:None)(cfg,s)
        except (ValueError,KeyError,TypeError,ValidationError):return hold('incident_hold_binding_rejected')
        return save(stage='evidence_probe_pending',prior_hold=s['decision'],evidence_addendum_consumed=True,
            required_action='Controller collect one new fixed transport experiment; preserve CTO hold, no repeated diagnosis on identical evidence')
    if s['stage'] in ('issue_pending','observe_issue'):
        first=s['stage']=='issue_pending'
        if first and not fx.reserve():return save(required_action='Await proxy reserve of 32 calls; no spend or wakeup attempted')
        if first:save(stage='observe_issue',observation_started=now,required_action='Observe exact SPIKE issue creation; never duplicate')
        try:issue=fx.issue(cfg,first)
        except (TimeoutError,urllib.error.URLError):issue=None
        if issue is None:
            return hold('incident_issue_unobserved') if now-s['observation_started']>=600 else s
        return save(stage='diagnosis_dispatch',issue_id=issue['id'],identifier=issue.get('identifier'),
            required_action='CTO diagnose fixed experiment scope; no tool authority')
    if s['stage'] in ('probe_pending','evidence_probe_pending'):
        if not probe_applicable:return hold('incident_experiment_not_applicable')
        enrichment=s['stage']=='evidence_probe_pending'
        try:
            result=fx.probe(cfg,s)
            require(hashlib.sha256(result['output'].encode()).hexdigest()==result['output_sha256'])
            jobs.validate(json.loads(result['output']),cfg['validator_sources'])
        except TimeoutError:return s
        except (ValueError,KeyError,TypeError):return hold('incident_experiment_rejected')
        return save(stage='evidence_diagnosis_dispatch' if enrichment else 'review_dispatch',probe=result,
            owner=cfg['cto'] if enrichment else cfg['reviewer'],
            required_action='CTO evaluate genuinely new fixed experiment; prior hold preserved' if enrichment else
                'Tech Lead independently review exact CTO decision and actual fixed experiment')
    if s['stage']=='resume_pending':
        try:
            check=getattr(fx,'verify_decisions',lambda *_:None);check(cfg,s)
            return sponsor(con,cfg,s,now)
        except (ValueError,KeyError,TypeError,ValidationError):return hold('incident_sponsorship_binding_rejected')
    phase='evidence_diagnosis' if 'evidence_diagnosis' in s['stage'] else 'review' if 'review' in s['stage'] else 'diagnosis'
    if s['stage'] in (phase+'_dispatch','observe_'+phase+'_dispatch'):
        try:instruction(cfg,s,phase)
        except ValueError:return hold('incident_instruction_bounds')
        first=s['stage']==phase+'_dispatch'
        if first and not fx.reserve():return save(required_action='Await proxy reserve of 32 calls; no spend or wakeup attempted')
        if first:save(stage='observe_'+phase+'_dispatch',marker=digest(dict(incident=digest(cfg),phase=phase,
            context=contract.digest(context(cfg,s,phase)))),observation_started=now,
            required_action='Observe exact '+phase+' handoff; no duplicate native task')
        try:wake=fx.wake(cfg,s,phase,first)
        except (TimeoutError,urllib.error.URLError):wake=None
        if wake is None:return hold('incident_wakeup_unobserved') if now-s['observation_started']>=600 else s
        return save(stage=phase+'_wait',wakeup_id=wake['id'],dispatched_at=s['observation_started'])
    require(s['stage']==phase+'_wait')
    matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']]
    if len(matches)>1:return hold('incident_duplicate_native_runs')
    if not matches or matches[0].get('status') in ('queued','dispatched','running'):
        return hold('incident_native_deadline') if now-s['dispatched_at']>=1800 else s
    task=matches[0]
    if s.get('observed_task')!=task['id']:save(observed_task=task['id'],observed_phase=phase)
    if task.get('status')!='completed':return hold('incident_native_failed')
    try:
        decision=fx.decision(cfg,s,phase,task);validate_decision(cfg,s,phase,task,decision)
    except TimeoutError:return s
    except (ValueError,KeyError,TypeError,ValidationError):return hold('incident_native_decision_rejected')
    if decision['value']['action']=='retain_technical_hold':
        return save(stage='blocked',owner=cfg['cto'],category='technical_hold_retained',decision=decision,
            required_action='CTO provide a new evidence-backed hypothesis; no identical submission')
    if phase=='diagnosis':return save(stage='probe_pending',cto_decision=decision,
        required_action='Controller execute fixed local transport experiment; no agent-supplied commands')
    if phase=='evidence_diagnosis':return save(stage='review_dispatch',cto_decision=decision,
        cto_decision_phase=phase,owner=cfg['reviewer'],
        required_action='Tech Lead independently review new CTO decision and exact fixed experiment; no inherited approval')
    return save(stage='resume_pending',review_decision=decision,owner=cfg['cto'],
        required_action='Consume exact independent sponsorship once; preserve original author and all delivery gates')


def sponsor(con,cfg,s,now):
    source=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
        (cfg['origin_issue_id'],cfg['author_task'])).fetchone();require(source is not None)
    c,prior=map(json.loads,source)
    require(digest(c)==cfg['source_config_sha256'] and digest(prior)==cfg['source_state_sha256']
        and prior['stage']=='blocked' and prior['observed_task']==cfg['failed_task']
        and s['cto_decision']['value']['action']==('submit_probe_for_review' if s.get('cto_decision_phase')=='evidence_diagnosis' else 'request_transport_probe')
        and s['cto_decision']['agent_id']==cfg['cto'] and s['review_decision']['agent_id']==cfg['reviewer']
        and s['cto_decision']['task_id']!=s['review_decision']['task_id']
        and s['review_decision']['value']['action']=='sponsor_data_submission')
    require(hashlib.sha256(s['probe']['output'].encode()).hexdigest()==s['probe']['output_sha256'])
    proof=json.loads(s['probe']['output']);jobs.validate(proof,cfg['validator_sources'])
    parent=handoffs.load(con,cfg['author_task']);data=json.loads(parent['data']) if parent else {}
    require(parent and parent['issue_id']==cfg['origin_issue_id'] and parent['stage']=='test_first_blocked'
        and data.get('calibration_prerequisite')==prior)
    receipt=dict(operation='independent_calibration_data_sponsorship_v1',incident_id=cfg['incident_id'],
        incident_sha256=digest(cfg),source_config_sha256=digest(c),prior_state=prior,cto_decision=s['cto_decision'],
        review_decision=s['review_decision'],probe=s['probe'],submission_limit=1,old_limits_preserved=True,
        author_restarted=False,tests_executed=False,execution_authorized=False,delivery_approval=False,at=now)
    if s.get('cto_decision_phase')=='evidence_diagnosis':
        require(s.get('evidence_addendum_consumed') is True and s['prior_hold']['value']['action']=='retain_technical_hold'
            and s['prior_hold']['task_id']!=s['cto_decision']['task_id'])
        receipt.update(prior_hold=s['prior_hold'],cto_decision_phase='evidence_diagnosis',evidence_addendum_limit=1)
    updated={k:v for k,v in prior.items() if k in ('capability_recovery_sha256','local_recovery_sha256','protocol_recovery_sha256')}
    updated.update(stage='bundle_dispatch',owner=cfg['cto'],incident_resume_id=cfg['incident_id'],incident_resume_sha256=digest(receipt),
        execution_authorized=False,delivery_approval=False,required_action='CTO one independently sponsored data submission; no author retry')
    data.update(calibration_prerequisite=updated,resolved_calibration_incident=cfg['incident_id'],
        author_retry_authorized=False,delivery_approval=False,required_action=updated['required_action'])
    data.pop('error',None);data.pop('calibration_incident',None)
    s.update(stage='resubmission_sponsored',sponsorship=receipt,submission_consumed=True)
    with con:
        con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(updated,sort_keys=True),cfg['origin_issue_id'],cfg['author_task']))
        con.execute('UPDATE calibration_incidents SET state=? WHERE incident_id=?',(json.dumps(s,sort_keys=True),cfg['incident_id']))
        handoffs.save(con,cfg['author_task'],cfg['origin_issue_id'],'test_first_validation_pending',cfg['cto'],data,now,commit=False)
    return s


def qualified_resume(con,c,s):
    row=con.execute('SELECT config,state FROM calibration_incidents WHERE incident_id=?',(s['incident_resume_id'],)).fetchone()
    require(row is not None);cfg,state=map(json.loads,row);r=state['sponsorship']
    require(state['submission_consumed'] is True and r['submission_limit']==1 and r['source_config_sha256']==digest(c)
        and digest(r)==s['incident_resume_sha256'] and r['incident_sha256']==digest(cfg)
        and all(r[k] is False for k in ('author_restarted','tests_executed','execution_authorized','delivery_approval')))
    return r


def projection(con,issue,author,source_state):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_incidents'").fetchone():return None
    matches=[]
    for row in con.execute('SELECT config,state FROM calibration_incidents'):
        cfg,s=map(json.loads,row)
        if (cfg['origin_issue_id']==issue and cfg['author_task']==author
                and s.get('current_source_state_sha256',cfg['source_state_sha256'])==digest(source_state)
                and s['stage']!='resubmission_sponsored'):
            matches.append(dict(incident_id=cfg['incident_id'],stage=s['stage'],issue_id=s.get('issue_id'),identifier=s.get('identifier'),
                owner=s['owner'],required_action=s['required_action'],author_retry_authorized=False,delivery_approval=False))
    require(len(matches)<=1)
    projected=matches[0] if matches else None
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_incident_enrollment_errors'").fetchone():
        error=con.execute('SELECT source_state_sha256,category FROM calibration_incident_enrollment_errors WHERE issue_id=? AND author_task=?',
            (issue,author)).fetchone()
        if error and error[0]==digest(source_state) and error[1]!='lookup_recovered':
            if projected is None:
                row=con.execute('SELECT config FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',(issue,author)).fetchone()
                require(row is not None)
                projected=dict(incident_id=None,stage='enrollment_blocked',issue_id=None,identifier=None,owner=json.loads(row[0])['cto'],
                    author_retry_authorized=False,delivery_approval=False)
            projected.update(observation_error=error[1],required_action='CTO/platform recover exact proxy/native evidence lookup; retain handoff, never restart author')
    return projected


PROXY_QUERY='''import sys,json;sys.path.insert(0,"/")
import model_proxy as m,structured_rejection_receipts as r
import hashlib,calibration_incident_contract as incident_contract
from calibration_transport_probe import source_hashes
print(json.dumps(dict(receipts=r.read(m.COUNTER_PATH,sys.argv[1]),sources=source_hashes(),
 incident_contract_sha256=hashlib.sha256(open(incident_contract.__file__,"rb").read()).hexdigest())))
'''


class Effects:
    def __init__(self,b):
        try:import generic_calibration_workflow as workflow,provider_diagnosis_recovery as provider,native
        except ImportError:from broker import generic_calibration_workflow as workflow,provider_diagnosis_recovery as provider,native
        self.b=b;self.workflow=workflow;self.provider=provider;self.native=native
        self.source=workflow.Effects(b);self.plans=self.source.plans
    def evidence(self,execution):
        proxy=self.provider.proxy_info(self.b)
        entry=self.b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,AttachStderr=False,Tty=True,
            Cmd=['python','-c',PROXY_QUERY,execution]))
        conn=self.b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('POST','/v1.45/exec/'+entry['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),{'Content-Type':'application/json'})
            response=conn.getresponse();raw=response.read(32769);require(response.status==200 and len(raw)<=32768)
        finally:conn.close()
        outcome=self.b.docker('GET','/exec/'+entry['Id']+'/json')
        require(outcome and not outcome.get('Running') and outcome.get('ExitCode')==0)
        value=json.loads(raw);require(value['sources']==source_hashes() and len(value['receipts'])==1)
        require(value['incident_contract_sha256']==hashlib.sha256(open(contract.__file__,'rb').read()).hexdigest())
        require(self.provider.proxy_info(self.b)['Id']==proxy['Id'])
        return value['receipts'][0],proxy['Image']
    def verify(self,cfg):
        with self.b.db() as con:
            row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
                (cfg['origin_issue_id'],cfg['author_task'])).fetchone();require(row is not None);c,s=map(json.loads,row)
        require(digest(c)==cfg['source_config_sha256'] and digest(s)==cfg['source_state_sha256'])
        self.source.verify(c)
        require(self.workflow.request(self.b,c['issue_id'],c['author_task'])==s and source_hashes()==cfg['validator_sources'])
        proxy=self.provider.proxy_info(self.b)
        expected=os.environ.get('BROKER_CALIBRATION_INCIDENT_PROXY_IMAGE',cfg['proxy_image'])
        require(proxy['Image']==expected and proxy.get('HostConfig',{}).get('ReadonlyRootfs') is True)
        # The historical receipt retains its original proxy image. An explicitly
        # pinned companion upgrade must prove the same durable rejection and
        # validator bytes plus byte-identical current incident contracts.
        if proxy['Image']!=cfg['proxy_image']:
            rejection,image=self.evidence(cfg['failed_execution'])
            require(rejection==cfg['rejection'] and image==expected)
    def reserve(self):return self.plans.native.remaining_calls()>=32
    def issue(self,cfg,first):
        from_text='SPIKE TRANSPORT ONLY. Source-bound incident '+digest(cfg)+'. Parent remains blocked; no product implementation or approval. '
        parent=self.plans.issues.request('/issues/'+cfg['origin_issue_id'])
        return self.plans.issues.ensure(dict(title='SPIKE calibration transport '+cfg['incident_id'][:12],
            description=from_text+'CTO diagnosis -> controller fixed offline experiment -> independent Tech Lead sponsorship. '
                'Historical cause is unknown; preserve failed execution '+cfg['failed_task']+' and every delivery gate.',
            parent_issue_id=cfg['origin_issue_id'],project_id=parent.get('project_id'),stage=1,status='todo'),allow_create=first)
    def wake(self,cfg,s,phase,first):
        actor=cfg['reviewer'] if phase=='review' else cfg['cto']
        require(self.plans.settings['agents'].get(actor)=='planning')
        return self.native.ensure_planning_start(self.plans.settings,s['issue_id'],actor,cfg['author_task'],s['marker'],
            instruction(cfg,s,phase),allow_create=first)
    def runs(self,cfg,s):return self.native.issue_task_runs(self.plans.settings,s['issue_id'])
    def decision(self,cfg,s,phase,task):
        actor=cfg['reviewer'] if phase=='review' else cfg['cto'];actual=self.plans.task(task['id'],actor)
        require(actual.get('status')=='completed' and actual.get('issue_id')==s['issue_id']
            and actual.get('wakeup_id')==s['wakeup_id'])
        with self.b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (task['id'],)).fetchall();require(len(rows)==1);binding=dict(rows[0])
            if binding['status'] in ('creating','starting','running','closing'):raise TimeoutError('observe same incident lease')
            require(binding['status']=='closed' and binding['agent_id']==actor and binding['issue_id']==s['issue_id']
                and binding['scope'].split(':')[-2:]==['planning',task['id']])
            require(con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',
                (binding['request_id'],)).fetchone()[0]==0)
        require(contract.request(dict(messages=[dict(role='user',content=actual.get('handoff_note',''))]))==context(cfg,s,phase))
        from structured_response_contract import _unique
        raw=(actual.get('result') or {}).get('output');require(isinstance(raw,str) and 1<=len(raw)<=4096)
        value=json.loads(raw,object_pairs_hook=_unique)
        decision=dict(value=value,task_id=task['id'],agent_id=actor,execution_id=binding['request_id'])
        validate_decision(cfg,s,phase,actual,decision);return decision
    def probe(self,cfg,s):
        with self.b.db() as con:return jobs.run(self.b,con,cfg['incident_id'],cfg['validator_sources'])
    def verify_hold(self,cfg,s):
        saved=s.get('prior_hold') or s['decision'];task=self.plans.task(saved['task_id'],cfg['cto'])
        require(self.decision(cfg,{**s,'wakeup_id':task['wakeup_id']},'diagnosis',task)==saved)
    def verify_decisions(self,cfg,s):
        if s.get('cto_decision_phase')=='evidence_diagnosis':self.verify_hold(cfg,s)
        for phase,key in ((s.get('cto_decision_phase','diagnosis'),'cto_decision'),('review','review_decision')):
            saved=s[key];task=self.plans.task(saved['task_id'],saved['agent_id'])
            phase_state={**s,'wakeup_id':task['wakeup_id']}
            require(self.decision(cfg,phase_state,phase,task)==saved)
        with self.b.db() as con:
            row=con.execute('SELECT identity,state FROM calibration_incident_jobs WHERE incident_id=?',(cfg['incident_id'],)).fetchone()
        require(row is not None);identity,job=map(json.loads,row)
        name,payload=jobs.payload(self.b,cfg['incident_id'])
        require(identity==dict(name=name,payload=payload,sources=cfg['validator_sources'])
            and job['stage']=='complete' and job['result']==s['probe'])
    def publish(self,cfg,s):
        if not s.get('issue_id'):return
        try:import handoff_runtime
        except ImportError:from broker import handoff_runtime
        handoff_runtime.publish(self.b,dict(issue_id=s['issue_id'],enabled=True,techlead=cfg['reviewer']),
            dict(stage=s['stage'],owner=s['owner'],source_task=cfg['author_task'],
                data=json.dumps(dict(required_action=s['required_action']))))


def handle(b,con,c,s):
    """Automatic enrollment of a proved producer-response incident only."""
    initialize(con);fx=Effects(b)
    require(fx.workflow.request(b,c['issue_id'],c['author_task'])==s)
    task=fx.plans.task(s['observed_task'],c['cto'])
    if task.get('status')!='failed':return None
    rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
        (task['id'],)).fetchall();require(len(rows)==1);binding=dict(rows[0])
    if binding['status']!='closed':return None
    # Once enrolled, observe the durable record rather than requerying the proxy
    # or spending model calls on the same failure at every tick.
    old=con.execute('SELECT i.incident_id FROM calibration_incidents i JOIN calibration_incident_occurrences o '
        'ON i.incident_id=o.incident_id WHERE o.execution_id=?',(binding['request_id'],)).fetchall()
    if old:
        require(len(old)==1);key=old[0][0]
    else:
        rejection,image=fx.evidence(binding['request_id']);cfg=prepare(c,s,task,binding,rejection,source_hashes())
        cfg['proxy_image']=image;register(con,cfg);key=cfg['incident_id']
    state=advance(con,key,fx)
    row=con.execute('SELECT config FROM calibration_incidents WHERE incident_id=?',(key,)).fetchone()
    try:fx.publish(json.loads(row[0]),state)
    except (ValueError,RuntimeError,TimeoutError,urllib.error.URLError) as error:
        state['publication_error']=dict(category=type(error).__name__,delivery_approval=False)
        con.execute('UPDATE calibration_incidents SET state=? WHERE incident_id=?',(json.dumps(state,sort_keys=True),key));con.commit()
    old=con.execute('SELECT category FROM calibration_incident_enrollment_errors WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    if old and old[0]!='lookup_recovered':
        con.execute('INSERT INTO calibration_incident_lookup_events(issue_id,author_task,source_state_sha256,category,at) VALUES(?,?,?,?,?)',
            (c['issue_id'],c['author_task'],digest(s),'lookup_recovered',time.time()))
        con.execute('UPDATE calibration_incident_enrollment_errors SET category=?,at=? WHERE issue_id=? AND author_task=?',
            ('lookup_recovered',time.time(),c['issue_id'],c['author_task']));con.commit()
    return state


def enrollment_error(con,c,s,error):
    initialize(con)
    old=con.execute('SELECT source_state_sha256,category FROM calibration_incident_enrollment_errors WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    if old and tuple(old)==(digest(s),type(error).__name__):return
    con.execute('INSERT INTO calibration_incident_lookup_events(issue_id,author_task,source_state_sha256,category,at) VALUES(?,?,?,?,?)',
        (c['issue_id'],c['author_task'],digest(s),type(error).__name__,time.time()))
    con.execute('INSERT OR REPLACE INTO calibration_incident_enrollment_errors VALUES(?,?,?,?,?)',
        (c['issue_id'],c['author_task'],digest(s),type(error).__name__,time.time()));con.commit()
