"""Native diagnostic control construction -> fixed sandbox -> independent referral.

Separate storage and child issue. Never registers a policy, resets an author,
adopts a diagnostic bundle as a delivery, or grants a worker Docker authority.
"""
import hashlib
import json
import time
import os
import re
import urllib.error
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from generic_harness_calibration import digest,require
import calibration_response_contract as wire
import calibration_objection_contract as review_wire
from structured_response_contract import _unique
import diagnostic_control_transport as transport
import diagnostic_control_transport_probe as transport_probe
import structured_rejection_receipts
try:import generic_calibration_seam_job as jobs
except ImportError:from broker import generic_calibration_seam_job as jobs


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_control_experiments(issue_id TEXT,author_task TEXT,config TEXT,state TEXT,PRIMARY KEY(issue_id,author_task))')


def register(con,cfg):
    initialize(con);c=cfg['source'];row=con.execute('SELECT config,state FROM calibration_control_experiments WHERE issue_id=? AND author_task=?',(c['issue_id'],c['author_task'])).fetchone()
    if row:require(json.loads(row[0])==cfg);return json.loads(row[1])
    state=dict(stage='issue_pending',owner=c['cto'],required_action='Create isolated diagnostic controls SPIKE',
        author_restarted=False,execution_authorized=False,delivery_approval=False)
    con.execute('INSERT INTO calibration_control_experiments VALUES(?,?,?,?)',(c['issue_id'],c['author_task'],json.dumps(cfg,sort_keys=True),json.dumps(state,sort_keys=True)));con.commit();return state


def producer_context(cfg):
    c=cfg['source'];paths=['/evidence/'+root+'/'+p for root in ('candidate','previous') for p in c['test_files']]
    return wire.context('bundle',paths,digest(cfg),engine=c['calibration_engine'])


def review_context(cfg,s):return review_wire.context(digest(cfg['source']),digest(cfg),digest(s['result']))


def validate_transport(value):
    require(set(value)=={'protocol','proxy_image','probe'} and value['protocol']=='diagnostic_control_data_carrier_v1'
        and bool(re.fullmatch('sha256:[a-f0-9]{64}',value['proxy_image'])))
    p=value['probe'];require(p['operation']=='fixed_diagnostic_control_transport_v1' and p['protocol']==value['protocol']
        and p['passed'] is True and p['sources']==transport_probe.source_hashes() and set(p['checks'])==transport_probe.CHECKS
        and all(v is True for v in p['checks'].values()) and type(p['model_calls']) is int and p['model_calls']==0
        and all(p[k] is False for k in ('product_tests_executed','historical_cause_proven','author_retry_authorized','execution_authorized','delivery_approval')))
    return value


def instruction(cfg,s,phase):
    c=cfg['source']
    if phase=='producer':
        try:import generic_calibration_workflow as workflow
        except ImportError:from broker import generic_calibration_workflow as workflow
        body=workflow.instruction(c).split('\n',2)[2]
        note=wire.capsule(producer_context(cfg))+('ISOLATED DIAGNOSTIC DATA ONLY, not a delivery submission. '
            'Positive references must exercise test bodies; each negative must fail its declared assertion, never setup/teardown. '
            'The original author and delivery remain blocked.\n')+body
        if s.get('transport'):note+='\n'+transport.MARKER+':'+producer_context(cfg)['source_sha256']+'\n'
    else:
        r=s['result']['receipt'];m=r.get('measurements',{});p=s['bundle'].get('policy',{})
        summary=dict(positive=m.get('positive'),negatives=m.get('negative_controls'),
            negative_failure_phases=r.get('negative_failure_phases'),criteria={n['id']:n['criteria'] for n in p.get('negatives',[])})
        note=review_wire.capsule(review_context(cfg,s))+('INDEPENDENT LEAD REVIEW OF ACTUAL ISOLATED EXPERIMENT. '
            'The frozen full harness now ran on independent reference controls. Evaluate actual positive/negative counts and failure phases. '
            'refer_to_cto permits only one new data proposal on the same original snapshot, never author retry or product approval. '
            'All later immutable policy review, calibration, Red/Green, regression, PR/CI/deploy/QA gates remain required. '
            'No tools or edits. retain_technical_hold if these measured facts are insufficient. reason<=200 chars.\nMeasured facts: '
            +json.dumps(summary,separators=(',',':')))
    require(len(note)<=3800);return note


def advance(con,issue,author,fx,*,now=None):
    now=time.time() if now is None else now
    cfg,s=map(json.loads,con.execute('SELECT config,state FROM calibration_control_experiments WHERE issue_id=? AND author_task=?',(issue,author)).fetchone());c=cfg['source']
    legacy=s['stage']=='blocked' and s.get('category')=='diagnostic_evidence_rejected' and not s.get('producer_task')
    if s['stage']=='referred' or (s['stage']=='blocked' and not legacy):return s
    def save(**changes):
        s.update(changes);con.execute('UPDATE calibration_control_experiments SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),issue,author));con.commit();return s
    def hold(category):return save(stage='blocked',category=category,owner=c['cto'],
        required_action='CTO diagnose '+category+' using preserved diagnostic evidence; no source reset or identical retry')
    def recover(task):
        if s.get('transport_recovery'):return hold('diagnostic_protocol_recovery_exhausted')
        proof=getattr(fx,'native_failure',lambda *_:None)(cfg,s,task)
        if proof is None:return hold('diagnostic_failure_evidence_unavailable')
        require(proof['operation']=='diagnostic_producer_transport_failure_v1' and proof['task_id']==task['id']
            and proof['wakeup_id']==s['wakeup_id'] and proof['diagnostic_sha256']==digest(cfg)
            and proof['source_sha256']==digest(c) and proof['binding_closed'] is True
            and all(proof[k] is False for k in ('execution_authorized','delivery_approval')))
        save(native_failure=proof,observed_task=task['id'])
        r=proof['receipt'];d=r.get('diagnostic',{})
        require(structured_rejection_receipts.from_event(dict(event='model_proxy_request',status=502,
            category='structured_decision_response_invalid',execution_id=proof['execution_id'],call_number=r['call_number'],
            structured_rejection_category=r['category'],structured_rejection_diagnostic=d))==r)
        if not (proof['initial_transport'] is None and r['category']=='calibration_response_invalid'
                and d.get('version')=='calibration-constraint-v2' and d.get('failure_code')=='invalid_json'):
            return hold('diagnostic_native_failure_not_protocol_recoverable')
        protocol=getattr(fx,'transport',lambda:None)()
        if protocol is None:return hold('diagnostic_transport_unavailable')
        validate_transport(protocol)
        recovery=dict(failure=proof,protocol=protocol,attempt_limit=1,execution_authorized=False,delivery_approval=False)
        return save(stage='producer_dispatch',category='diagnostic_transport_recovery',transport=protocol,transport_recovery=recovery,
            required_action='One new diagnostic task using qualified data-carrier protocol; original failed task and source budgets preserved')
    if 'started' not in s:save(started=now)
    try:
        fx.verify(cfg)
        if legacy:
            if 'failure_observation_started' not in s:save(failure_observation_started=now)
            matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']]
            require(len(matches)==1 and matches[0].get('agent_id')==c['cto'] and matches[0].get('issue_id')==s['issue_id'])
            if matches[0].get('status')!='failed':return hold('diagnostic_data_rejected')
            return recover(matches[0])
        if s['stage'] in ('issue_pending','observe_issue'):
            first=s['stage']=='issue_pending'
            if first:save(stage='observe_issue',phase_started=now)
            try:child=fx.issue(cfg,first)
            except (TimeoutError,urllib.error.URLError):child=None
            if child is None:return hold('diagnostic_issue_unobserved') if now-s['phase_started']>=600 else s
            return save(stage='producer_dispatch',issue_id=child['id'],identifier=child.get('identifier'),
                required_action='CTO construct independent control data in isolated diagnostic task; no product edits')
        if s['stage'] in ('experiment_pending','observe_experiment'):
            if s['stage']=='experiment_pending':save(stage='observe_experiment',phase_started=now)
            result=fx.measure(cfg,s);fx.validate_measurement(cfg,s,result)
            if not result['receipt']['functional_controls_passed']:return save(stage='blocked',category='diagnostic_controls_failed',
                owner=c['cto'],result=result,required_action='CTO diagnose measured failing reference controls; preserve bytes and original source; no identical retry')
            return save(stage='review_dispatch',result=result,owner=c['reviewer'],required_action='Independent Lead review measured full-harness reference controls')
        phase='producer' if s['stage'].startswith('producer') else 'review'
        require(s['stage'] in tuple(phase+'_'+suffix for suffix in ('dispatch','observe','wait')))
        actor=c['cto'] if phase=='producer' else c['reviewer'];require(c['cto']!=c['reviewer'])
        if phase=='producer' and s['stage']=='producer_dispatch':
            protocol=getattr(fx,'transport',lambda:None)()
            if protocol:
                validate_transport(protocol);require(not s.get('transport') or s['transport']==protocol);save(transport=protocol)
            elif s.get('transport'):return hold('diagnostic_transport_unavailable')
        note=instruction(cfg,s,phase)
        if s['stage'] in (phase+'_dispatch',phase+'_observe'):
            first=s['stage']==phase+'_dispatch'
            if first and not fx.reserve():return save(required_action='Await diagnostic model reserve; no wakeup attempted')
            if first:save(stage=phase+'_observe',marker=digest(dict(config=cfg,phase=phase,instruction=note)),phase_started=now)
            try:wake=fx.wake(cfg,s,phase,first)
            except (TimeoutError,urllib.error.URLError):wake=None
            if wake is None:return hold('diagnostic_wakeup_unobserved') if now-s['phase_started']>=600 else s
            return save(stage=phase+'_wait',wakeup_id=wake['id'],owner=actor,required_action='Observe exact native diagnostic '+phase+'; never duplicate wakeup')
        matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']];require(len(matches)<=1)
        if not matches or matches[0].get('status') in ('queued','dispatched','running'):
            return hold('diagnostic_native_deadline') if now-s['phase_started']>=1800 else s
        task=matches[0];require(task.get('agent_id')==actor and task.get('issue_id')==s['issue_id'] and task['id']!=author)
        if phase=='producer' and task.get('status')=='failed':return recover(task)
        require(task.get('status')=='completed')
        if phase=='producer':
            bundle=fx.collect(cfg,s,task)
            if bundle['operation']=='diagnostic_control_objection_v1':return save(stage='blocked',category='diagnostic_native_objection',
                owner=c['cto'],objection=bundle,required_action='CTO diagnose explicit control-construction objection; no source retry')
            require(bundle['operation']=='generic_calibration_proposal_bundle_v1')
            return save(stage='experiment_pending',bundle=bundle,producer_task=task['id'],producer_wakeup=s['wakeup_id'],
                required_action='Controller run fixed isolated experiment; no policy registration or delivery authority')
        decision=fx.decision(cfg,s,task);require(decision['task_id']==task['id'] and decision['agent_id']==actor)
        Draft202012Validator(review_wire.schema(review_context(cfg,s))).validate(decision['value'])
        if decision['value']['action']=='retain_technical_hold':return save(stage='blocked',category='diagnostic_review_hold',
            decision=decision,owner=c['cto'],required_action='CTO address independent measured-evidence objection; diagnostic budget spent')
        return save(stage='referred',decision=decision,required_action='JIT verify measured independent referral before one source data proposal; no author retry')
    except (TimeoutError,urllib.error.URLError):
        start=s.get('failure_observation_started',now) if legacy else s.get('phase_started',s['started'])
        return hold('diagnostic_observation_deadline') if now-start>=1800 else s
    except (ValueError,KeyError,TypeError,ValidationError):
        return hold('diagnostic_failure_evidence_rejected' if legacy else 'diagnostic_evidence_rejected')


class Effects:
    def __init__(self,b):
        try:import calibration_objection_runtime as objections,native
        except ImportError:from broker import calibration_objection_runtime as objections,native
        self.b=b;self.parent=objections.Effects(b);self.plans=self.parent.plans;self.native=native
    def transport(self):
        if not os.environ.get('BROKER_DIAGNOSTIC_CONTROL_PROXY_IMAGE'):return None
        program='import sys,json;sys.path.insert(0,"/");import diagnostic_control_transport_probe as p;print(json.dumps(p.run(),sort_keys=True))'
        proof,image=self.proxy_read(program)
        value=dict(protocol='diagnostic_control_data_carrier_v1',proxy_image=image,probe=proof)
        validate_transport(value);return value
    def carrier_evidence(self,execution):
        program='import sys,json;sys.path.insert(0,"/");import model_proxy as m,diagnostic_control_transport as d;print(json.dumps(d.read(m.COUNTER_PATH,sys.argv[1])))'
        return self.proxy_read(program,[execution])[0]
    def proxy_read(self,program,arguments=()):
        expected=os.environ.get('BROKER_DIAGNOSTIC_CONTROL_PROXY_IMAGE')
        require(isinstance(expected,str) and bool(re.fullmatch('sha256:[a-f0-9]{64}',expected)))
        try:import provider_diagnosis_recovery as provider
        except ImportError:from broker import provider_diagnosis_recovery as provider
        proxy=provider.proxy_info(self.b);require(proxy['Image']==expected and proxy.get('HostConfig',{}).get('ReadonlyRootfs') is True)
        entry=self.b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,AttachStderr=False,Tty=True,Cmd=['python','-B','-c',program,*arguments]))
        conn=self.b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('POST','/v1.45/exec/'+entry['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),{'Content-Type':'application/json'})
            response=conn.getresponse();raw=response.read(32769);require(response.status==200 and len(raw)<=32768)
        finally:conn.close()
        outcome=self.b.docker('GET','/exec/'+entry['Id']+'/json');require(outcome and not outcome.get('Running') and outcome.get('ExitCode')==0)
        require(provider.proxy_info(self.b)['Id']==proxy['Id']);return json.loads(raw),proxy['Image']
    def native_failure(self,cfg,s,task):
        try:import calibration_incidents as incidents
        except ImportError:from broker import calibration_incidents as incidents
        c=cfg['source'];actual=self.plans.task(task['id'],c['cto']);binding=self.binding(actual,c['cto'])
        require(actual.get('status')=='failed' and actual.get('failure_reason')=='agent_error.provider_server_error'
            and actual.get('agent_id')==c['cto']
            and actual.get('issue_id')==s['issue_id'] and actual.get('wakeup_id')==s['wakeup_id']
            and wire.request(dict(messages=[dict(role='user',content=actual.get('handoff_note',''))]))==producer_context(cfg))
        reads=self.plans.reads(actual)
        for path in producer_context(cfg)['required_paths']:
            observed=reads.get(path,{});require(type(observed.get('lines')) is int and observed['lines']>0 and observed['lines']==observed.get('total_lines'))
        receipt,_=incidents.Effects(self.b).evidence(binding['request_id'])
        return dict(operation='diagnostic_producer_transport_failure_v1',task_id=actual['id'],execution_id=binding['request_id'],
            wakeup_id=s['wakeup_id'],diagnostic_sha256=digest(cfg),source_sha256=digest(c),binding_closed=True,
            receipt=receipt,initial_transport=transport.binding(dict(messages=[dict(role='user',content=actual.get('handoff_note',''))])),
            required_read_evidence={p:reads[p] for p in producer_context(cfg)['required_paths']},execution_authorized=False,delivery_approval=False)
    def verify(self,cfg):
        self.parent.verify(cfg['objection_config']);c=cfg['source']
        with self.b.db() as con:original,state=map(json.loads,con.execute('SELECT config,state FROM calibration_objections WHERE issue_id=? AND author_task=?',(c['issue_id'],c['author_task'])).fetchone())
        require(original==cfg['objection_config'] and original['source']==c and state['decision']==cfg['hold']
            and {k:state['experiment'][k] for k in ('proposal','review')}==cfg['plan_evidence'])
        self.parent.verify_decision(original,state)
        for phase,key in (('design','proposal'),('review','review')):
            receipt=cfg['plan_evidence'][key];task=self.plans.task(receipt['task_id'],receipt['agent_id'])
            require(self.parent.experiment_decision(original,state,task,phase)==receipt)
        require(cfg['plan_evidence']['review']['value']['action']=='retain_technical_hold')
    def reserve(self):return self.plans.native.remaining_calls()>=32
    def issue(self,cfg,first):
        parent=self.plans.issues.request('/issues/'+cfg['parent_issue_id'])
        return self.plans.issues.ensure(dict(title='SPIKE isolated reference controls '+digest(cfg['source'])[:12],
            description='Diagnostic control construction and full frozen harness measurements only. Source '+digest(cfg['source'])+
                ' remains blocked. No author reset, policy registration or product approval.',
            parent_issue_id=cfg['parent_issue_id'],project_id=parent.get('project_id'),stage=1,status='todo'),allow_create=first)
    def wake(self,cfg,s,phase,first):
        c=cfg['source'];actor=c['cto'] if phase=='producer' else c['reviewer'];require(self.plans.settings['agents'].get(actor)=='planning')
        return self.native.ensure_planning_start(self.plans.settings,s['issue_id'],actor,c['author_task'],s['marker'],instruction(cfg,s,phase),allow_create=first)
    def runs(self,cfg,s):return self.native.issue_task_runs(self.plans.settings,s['issue_id'])
    def binding(self,task,actor):
        with self.b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(task['id'],)).fetchall();require(len(rows)==1);r=dict(rows[0])
            if r['status'] in ('creating','starting','running','closing'):raise TimeoutError('observe diagnostic native lease')
            require(r['status']=='closed' and r['agent_id']==actor and r['issue_id']==task['issue_id']
                and r['scope'].split(':')[-2:]==['planning',task['id']]);return r
    def collect(self,cfg,s,task):
        try:import generic_calibration_proposal as proposal,remediation_runtime_guard as guard
        except ImportError:from broker import generic_calibration_proposal as proposal,remediation_runtime_guard as guard
        c=cfg['source'];actual=self.plans.task(task['id'],c['cto']);binding=self.binding(actual,c['cto'])
        if s.get('transport'):require(self.transport()==s['transport'])
        require(actual.get('status')=='completed' and actual.get('issue_id')==s['issue_id'] and actual.get('wakeup_id')==s['wakeup_id']
            and wire.request(dict(messages=[dict(role='user',content=actual.get('handoff_note',''))]))==producer_context(cfg))
        raw=(actual.get('result') or {}).get('output');require(isinstance(raw,str) and 1<=len(raw.encode())<=786432)
        body=json.loads(raw,object_pairs_hook=_unique);Draft202012Validator(wire.schema(producer_context(cfg))).validate(body)
        carrier=None
        if s.get('transport'):
            receipts=self.carrier_evidence(binding['request_id']);require(len(receipts)==1);carrier=receipts[0]
            require(carrier['source_sha256']==producer_context(cfg)['source_sha256'] and carrier['payload_sha256']==digest(body)
                and carrier['execution_id']==binding['request_id'] and all(carrier[k] is False for k in ('worker_tool_executed','execution_authorized','delivery_approval')))
        reads=self.plans.reads(actual)
        required=producer_context(cfg)['required_paths'] if body['action']=='calibration_objection' else proposal.source_paths(body)
        for path in required:
            observed=reads.get(path,{});require(type(observed.get('lines')) is int and observed['lines']>0 and observed['lines']==observed.get('total_lines'))
        producer=dict(task_id=task['id'],actor=c['cto'],wakeup_id=s['wakeup_id'],execution_id=binding['request_id'],
            diagnostic_issue_id=s['issue_id'],artifact_sha256=hashlib.sha256(raw.encode()).hexdigest(),read_evidence={p:reads[p] for p in required})
        if carrier:producer['data_carrier_receipt']=carrier
        if body['action']=='calibration_objection':return dict(operation='diagnostic_control_objection_v1',reason=body['reason'],producer=producer,
            execution_authorized=False,delivery_approval=False)
        value=guard.qualified(self.b,c['issue_id']);require(digest(value)==c['execution_sha256'])
        with self.b.db() as con:route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()[0])
        record=proposal.bundle(body,value,route,c['prepared'],expected_engine=c['calibration_engine'])
        return {**record,'producer':producer,'candidate_volume':c['candidate_volume']}
    def measure(self,cfg,s):
        with self.b.db() as con:r=jobs.run(self.b,con,cfg['source'],kind='controls',bundle=s['bundle'])
        return {**r,'receipt':json.loads(r['output'])}
    def validate_measurement(self,cfg,s,result):
        from calibration_control_experiment_probe import validate
        require(result['approval'] is False and type(result['exit_code']) is int and result['exit_code']==0
            and hashlib.sha256(result['output'].encode()).hexdigest()==result['output_sha256']
            and json.loads(result['output'])==result['receipt']);validate(result['receipt'],cfg['source'],s['bundle'])
    def decision(self,cfg,s,task):
        return self.parent.read_decision(cfg,s,task,cfg['source']['reviewer'],review_wire,review_context(cfg,s))


def handle(b,con,original,state):
    c=original['source'];cfg=dict(source=c,objection_config=original,hold=state['decision'],
        plan_evidence={k:state['experiment'][k] for k in ('proposal','review')},parent_issue_id=state['issue_id'])
    register(con,cfg);fx=Effects(b);result=advance(con,c['issue_id'],c['author_task'],fx)
    state.update(owner=result['owner'],required_action=(result.get('identifier') or 'Diagnostic')+': '+result['required_action'],
        control_diagnostic={k:result.get(k) for k in ('stage','category','identifier','issue_id')})
    if result['stage']=='referred':
        state.update(stage='resume_pending',resume_started=time.time(),diagnostic_referral=referral(cfg,result))
    con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',(json.dumps(state,sort_keys=True),c['issue_id'],c['author_task']));con.commit()
    if result.get('issue_id'):
        try:import handoff_runtime
        except ImportError:from broker import handoff_runtime
        handoff_runtime.publish(b,dict(issue_id=result['issue_id'],enabled=True,techlead=c['reviewer']),
            dict(stage=result['stage'],owner=result['owner'],source_task=c['author_task'],data=json.dumps(dict(required_action=result['required_action']))))
    return result


def referral(cfg,s):
    require(s['stage']=='referred' and s['decision']['value']['action']=='refer_to_cto'
        and s['result']['receipt']['functional_controls_passed'] is True)
    require(s['decision']['agent_id']==cfg['source']['reviewer'])
    Draft202012Validator(review_wire.schema(review_context(cfg,s))).validate(s['decision']['value'])
    return dict(operation='measured_reference_control_referral_v1',source_sha256=digest(cfg['source']),
        config_sha256=digest(cfg),bundle_sha256=digest(s['bundle']),result_sha256=digest(s['result']),decision_sha256=digest(s['decision']),
        source_author_red_executed=False,execution_authorized=False,delivery_approval=False)


def cached_referral(con,c,pointer):
    cfg,s=map(json.loads,con.execute('SELECT config,state FROM calibration_control_experiments WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone());require(cfg['source']==c and referral(cfg,s)==pointer)
    return cfg,s


def verify_referral(b,c,pointer):
    with b.db() as con:cfg,s=cached_referral(con,c,pointer)
    fx=Effects(b);fx.verify(cfg)
    producer=fx.plans.task(s['producer_task'],c['cto'])
    require(fx.collect(cfg,{**s,'wakeup_id':s['producer_wakeup']},producer)==s['bundle'])
    result=fx.measure(cfg,s);fx.validate_measurement(cfg,s,result);require(result==s['result'])
    reviewer=fx.plans.task(s['decision']['task_id'],c['reviewer']);require(fx.decision(cfg,s,reviewer)==s['decision'])


def lookup(b,issue):
    if not issue:return None
    with b.db() as con:
        initialize(con);matches=[tuple(map(json.loads,r)) for r in con.execute('SELECT config,state FROM calibration_control_experiments') if json.loads(r[1]).get('issue_id')==issue]
    require(len(matches)<=1);return matches[0] if matches else None


def prompt_contract(b,issue,task,note):
    current=lookup(b,issue)
    if current is None:return None
    cfg,s=current;c=cfg['source'];require(s['stage']=='producer_wait' and task.get('agent_id')==c['cto']
        and task.get('issue_id')==s['issue_id'] and task.get('wakeup_id')==s['wakeup_id'])
    fx=Effects(b);fx.verify(cfg);body=dict(messages=[dict(role='user',content=note)]);value=wire.request(body);require(value==producer_context(cfg))
    if s.get('transport'):require(transport.binding(body)==value and fx.transport()==s['transport'])
    else:require(transport.binding(body) is None)
    return value


def mounts(b,binding):
    current=lookup(b,binding['issue_id'])
    if current is None:return []
    cfg,s=current;c=cfg['source'];require(s['stage']=='producer_wait' and binding['agent_id']==c['cto'])
    with b.db() as con:
        rows=con.execute("SELECT n.* FROM native_bindings n JOIN leases l USING(request_id) WHERE n.issue_id=? AND n.agent_id=? AND l.status IN ('creating','starting','running')",(s['issue_id'],c['cto'])).fetchall()
        require(len(rows)==1);r=dict(rows[0]);require(r['scope'].split(':')[-2:]==['planning',r['task_id']])
    fx=Effects(b);fx.verify(cfg);task=fx.plans.task(r['task_id'],c['cto'])
    require(task.get('wakeup_id')==s['wakeup_id'] and task.get('issue_id')==s['issue_id'])
    return [dict(Type='volume',Source=c[role+'_volume'],Target='/evidence/'+role,ReadOnly=True) for role in ('candidate','previous')]
