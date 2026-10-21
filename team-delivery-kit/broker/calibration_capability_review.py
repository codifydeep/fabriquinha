"""Independent review of a claimed missing reference-fixture capability.

One fixed synthetic measurement and one native Lead decision can admit only a
separate diagnostic. Never approves the rejected CTO plan, renews the source
producer budget, changes candidate bytes or issues execution authority.
"""
import hashlib
import json
import os
import re
import time
import urllib.error

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from generic_harness_calibration import digest,require
import calibration_objection_contract as contract
import calibration_response_contract as wire
import reference_fixture_capability_probe as probe

FALSE_FLAGS=('author_retry_authorized','execution_authorized','delivery_approval','source_reset','retry_budget_reset')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_capability_reviews('
        'issue_id TEXT,author_task TEXT,config TEXT,state TEXT,PRIMARY KEY(issue_id,author_task))')


def configuration(original,parent,image):
    c=original['source'];experiment=parent.get('experiment',{});request=experiment.get('proposal',{});hold=parent.get('decision',{})
    require(parent.get('stage')=='blocked' and parent.get('category')=='experiment_requires_engineering_capability'
        and experiment.get('stage')=='blocked' and experiment.get('category')=='experiment_requires_engineering_capability'
        and c.get('calibration_engine')=='unittest_path_fixtures_v2' and c['cto']!=c['reviewer']
        and request.get('agent_id')==c['cto'] and request.get('value',{}).get('action')=='needs_engineering_capability'
        and hold.get('agent_id')==c['reviewer'] and hold.get('value',{}).get('action')=='retain_technical_hold'
        and len({request['task_id'],hold['task_id'],c['author_task']})==3
        and all(request['value'].get(k) is False and hold['value'].get(k) is False for k in FALSE_FLAGS[:3])
        and isinstance(image,str) and re.fullmatch('sha256:[a-f0-9]{64}',image))
    reads=original['objection']['read_evidence'];paths=sorted(reads)
    baseline={'/evidence/'+role+'/'+path for role in ('candidate','previous') for path in c['test_files']}
    require(set(paths)>baseline and all(type(v.get('lines')) is int and v['lines']>0
        and v['lines']==v.get('total_lines') for v in reads.values()))
    wire.context('bundle',paths,digest(c),engine=c['calibration_engine'])
    return dict(source=c,objection_config=original,hold=hold,capability_request=request,
        parent_issue_id=parent['issue_id'],required_paths=paths,image=image)


def register(con,cfg):
    initialize(con);c=cfg['source']
    row=con.execute('SELECT config,state FROM calibration_capability_reviews WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    if row:require(json.loads(row[0])==cfg);return json.loads(row[1])
    s=dict(stage='measure',owner=c['reviewer'],required_action='Measure existing reference capability in fixed synthetic sandbox',
        **{k:False for k in FALSE_FLAGS})
    con.execute('INSERT INTO calibration_capability_reviews VALUES(?,?,?,?)',
        (c['issue_id'],c['author_task'],json.dumps(cfg,sort_keys=True),json.dumps(s,sort_keys=True)));con.commit();return s


def context(cfg,s):return contract.context(digest(cfg['source']),digest(cfg['capability_request']),digest(s['measurement']))


def instruction(cfg,s):
    request=cfg['capability_request']['value']
    claim={k:request[k] for k in ('action','reason','hypothesis','method','expected_evidence')}
    facts=dict(engine=cfg['source']['calibration_engine'],checks=s['measurement']['checks'],
        positive=s['measurement']['measurements']['positive']['tests'],negatives=s['measurement']['negative_failure_phases'],
        synthetic=True,product_snapshot_used=False)
    note=contract.capsule(context(cfg,s))+(
        'INDEPENDENT LEAD CAPABILITY REVIEW, NOT A PRODUCT OR PLAN APPROVAL. No tools. '
        'The CTO requested engineering because the candidate lacks the desired feature. '
        'The fixed synthetic probe used the existing v2 executor, a frozen Python/Node harness and separate executable JS/HTML references. '
        'Positive references implemented absent synthetic behavior; negatives failed assertions; candidate bytes did not change. '
        'This does NOT prove current product controls or their feasibility. References are untrusted diagnostic data, not candidate edits. '
        'refer_to_cto permits ONE separate diagnostic control proposal under these semantics; it does NOT approve the rejected CTO plan '
        'or renew an ordinary producer/author budget. Choose it only if the measured existing capability justifies that diagnostic. '
        'Otherwise retain_technical_hold and state the actual missing capability. No test weakening, policy registration, Red/Green, merge or delivery approval. '
        'Return the exact capsule-bound JSON schema, reason<=200 characters, all authority flags false.\n'
        'Preserved CTO request: '+json.dumps(claim,sort_keys=True)+'\nFixed synthetic facts: '+json.dumps(facts,sort_keys=True))
    require(len(note)<=3800);return note


def measured(job):
    require(job.get('approval') is False and type(job.get('exit_code')) is int and job['exit_code']==0
        and job.get('validation_job_key') and job.get('output_sha256')==hashlib.sha256(job['output'].encode()).hexdigest())
    return probe.validate(json.loads(job['output']))


def advance(con,cfg,fx,*,now=None):
    now=time.time() if now is None else now;c=cfg['source'];register(con,cfg)
    s=json.loads(con.execute('SELECT state FROM calibration_capability_reviews WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()[0])
    if s['stage'] in ('blocked','permitted'):return s
    def save(**changes):
        s.update(changes);con.execute('UPDATE calibration_capability_reviews SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),c['issue_id'],c['author_task']));con.commit();return s
    def hold(category):return save(stage='blocked',category=category,owner=c['cto'],
        required_action='CTO resolve '+category+' with preserved capability request and evidence; no identical retry')
    if 'started' not in s:save(started=now)
    try:
        fx.verify(cfg)
        if s['stage']=='measure':
            job=fx.measure(cfg);value=measured(job)
            instruction(cfg,{**s,'measurement':value}) # Bounds before issuing any native task.
            return save(stage='issue_pending',measurement=value,measurement_job=job,phase_started=now)
        require(measured(s['measurement_job'])==s['measurement'])
        if s['stage'] in ('issue_pending','issue_observe'):
            first=s['stage']=='issue_pending'
            if first:save(stage='issue_observe',phase_started=now)
            child=fx.issue(cfg,first)
            if child is None:return hold('capability_issue_unobserved') if now-s['phase_started']>=600 else s
            return save(stage='review_dispatch',issue_id=child['id'],identifier=child.get('identifier'),
                required_action='Independent Lead assess measured capability; diagnostic permission only')
        if s['stage'] in ('review_dispatch','review_observe'):
            first=s['stage']=='review_dispatch'
            if first:
                if not fx.reserve():return s
                save(stage='review_observe',marker=digest(dict(config=digest(cfg),note=instruction(cfg,s))),phase_started=now)
            wake=fx.wake(cfg,s,first)
            if wake is None:return hold('capability_wakeup_unobserved') if now-s['phase_started']>=600 else s
            return save(stage='review_wait',wakeup_id=wake['id'],owner=c['reviewer'])
        require(s['stage']=='review_wait')
        matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']];require(len(matches)<=1)
        if not matches or matches[0].get('status') in ('queued','dispatched','running'):
            return hold('capability_review_deadline') if now-s['phase_started']>=1800 else s
        task=matches[0];require(task['status']=='completed' and task['agent_id']==c['reviewer'] and task['issue_id']==s['issue_id'])
        decision=fx.decision(cfg,s,task)
        require(decision['task_id']==task['id'] and decision['agent_id']==c['reviewer'])
        Draft202012Validator(contract.schema(context(cfg,s))).validate(decision['value'])
        save(decision=decision)
        if decision['value']['action']=='retain_technical_hold':return hold('capability_hold_retained')
        require(fx.measure(cfg)==s['measurement_job']) # Reauthenticate captured fixed-job proof before permission.
        receipt=dict(operation='independent_reference_capability_admission_v1',config_sha256=digest(cfg),
            capability_request=cfg['capability_request'],hold=cfg['hold'],measurement_job=s['measurement_job'],decision=decision,
            diagnostic_attempt_limit=1,**{k:False for k in FALSE_FLAGS})
        return save(stage='permitted',receipt=receipt,receipt_sha256=digest(receipt),owner=c['cto'],
            required_action='One separate untrusted reference diagnostic; source delivery remains blocked')
    except (TimeoutError,urllib.error.URLError):
        return hold('capability_evidence_deadline') if now-s.get('phase_started',s['started'])>=1800 else s
    except (ValueError,KeyError,TypeError,ValidationError):return hold('capability_evidence_rejected')


def qualified(con,cfg,state):
    initialize(con);c=cfg['source'];row=con.execute('SELECT config,state FROM calibration_capability_reviews WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone();require(row and list(map(json.loads,row))==[cfg,state])
    require(state['stage']=='permitted');r=state['receipt']
    require(r['operation']=='independent_reference_capability_admission_v1' and r['config_sha256']==digest(cfg)
        and state['receipt_sha256']==digest(r) and r['diagnostic_attempt_limit']==1
        and r['capability_request']==cfg['capability_request'] and r['hold']==cfg['hold']
        and r['measurement_job']==state['measurement_job'] and r['decision']==state['decision']
        and all(r[k] is False and state[k] is False for k in FALSE_FLAGS)
        and r['decision']['agent_id']==c['reviewer'] and r['decision']['value']['action']=='refer_to_cto'
        and measured(r['measurement_job'])==state['measurement'])
    Draft202012Validator(contract.schema(context(cfg,state))).validate(r['decision']['value']);return r


def diagnostic_configuration(cfg,s):
    require(s.get('stage')=='permitted' and s['receipt_sha256']==digest(s['receipt']))
    return dict(source=cfg['source'],objection_config=cfg['objection_config'],hold=cfg['hold'],parent_issue_id=s['issue_id'],
        capability_admission=dict(operation='reference_capability_diagnostic_v1',receipt_sha256=s['receipt_sha256'],
            required_paths=cfg['required_paths'],decision=s['decision']))


class Effects:
    def __init__(self,b):
        try:import calibration_objection_runtime as parent
        except ImportError:from broker import calibration_objection_runtime as parent
        self.b=b;self.parent=parent.Effects(b);self.plans=self.parent.plans;self.native=self.parent.native
    def verify(self,cfg):
        self.parent.verify(cfg['objection_config']);c=cfg['source']
        with self.b.db() as con:
            original,s=map(json.loads,con.execute('SELECT config,state FROM calibration_objections WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone())
        initial=s.get('stage')=='blocked' and s.get('category')=='experiment_requires_engineering_capability'
        descendant=(s.get('stage') in ('resume_pending','referred') and bool(s.get('diagnostic_referral'))
            and s.get('control_diagnostic',{}).get('stage')=='referred')
        expected=dict(source=original['source'],objection_config=original,hold=s['decision'],
            capability_request=s['experiment']['proposal'],parent_issue_id=s['issue_id'],
            required_paths=sorted(original['objection']['read_evidence']),image=os.environ['BROKER_REFERENCE_CAPABILITY_PROBE_IMAGE'])
        require(original==cfg['objection_config'] and expected==cfg and (initial or descendant)
            and s['experiment']['stage']=='blocked' and s['experiment']['category']=='experiment_requires_engineering_capability'
            and s.get('capability_review',{}).get('category')!='capability_registration_rejected')
        self.parent.verify_decision(original,s)
        request=cfg['capability_request'];task=self.plans.task(request['task_id'],c['cto'])
        require(self.parent.experiment_decision(original,s,task,'design')==request)
    def measure(self,cfg):
        try:import validation_job
        except ImportError:from broker import validation_job
        payload=dict(Image=cfg['image'],User='10000:10000',Entrypoint=['python','-B','/reference_fixture_capability_probe.py'],Cmd=[],
            NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1'],Labels={'delivery-kit.reference-capability':digest(cfg)},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=268435456,NanoCpus=1000000000,PidsLimit=64,Mounts=[],Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'}))
        return validation_job.run(self.b,cfg['capability_request']['task_id'],'structure',payload)
    def reserve(self):return self.plans.native.remaining_calls()>=32
    def issue(self,cfg,first):
        parent=self.plans.issues.request('/issues/'+cfg['parent_issue_id'])
        return self.plans.issues.ensure(dict(title='SPIKE reference capability '+digest(cfg['source'])[:12],
            description='Independent review of existing executable-reference capability; fixed synthetic evidence only. '
                'Original engineering request preserved. No source retry, product edits or approval.',
            parent_issue_id=cfg['parent_issue_id'],project_id=parent.get('project_id'),status='todo',stage=1),allow_create=first)
    def wake(self,cfg,s,first):
        return self.native.ensure_planning_start(self.plans.settings,s['issue_id'],cfg['source']['reviewer'],
            cfg['source']['author_task'],s['marker'],instruction(cfg,s),allow_create=first)
    def runs(self,cfg,s):return self.native.issue_task_runs(self.plans.settings,s['issue_id'])
    def decision(self,cfg,s,task):
        try:import native_scope_note
        except ImportError:from broker import native_scope_note
        c=cfg['source'];actual=self.plans.task(task['id'],c['reviewer'])
        expected='DELIVERY_PLANNING_START '+s['marker']+'\nSource: '+c['author_task']+'\n'+instruction(cfg,s).strip()
        require(native_scope_note.canonical(actual.get('handoff_note',''),s['wakeup_id'])==expected)
        return self.parent.read_decision(cfg,s,task,c['reviewer'],contract,context(cfg,s))


def verify_diagnostic(b,diagnostic):
    c=diagnostic['source']
    with b.db() as con:
        initialize(con);row=con.execute('SELECT config,state FROM calibration_capability_reviews WHERE issue_id=? AND author_task=?',
            (c['issue_id'],c['author_task'])).fetchone();require(row);cfg,s=map(json.loads,row)
        qualified(con,cfg,s);require(diagnostic_configuration(cfg,s)==diagnostic)
    fx=Effects(b);fx.verify(cfg);require(fx.measure(cfg)==s['measurement_job'])
    require(fx.decision(cfg,s,{'id':s['decision']['task_id']})==s['decision'])


def handle(b,con,original,parent):
    if parent.get('capability_review',{}).get('category')=='capability_registration_rejected':return parent
    try:
        cfg=configuration(original,parent,os.environ.get('BROKER_REFERENCE_CAPABILITY_PROBE_IMAGE',''))
        s=advance(con,cfg,Effects(b));c=cfg['source']
        parent.update(owner=s['owner'],required_action=(s.get('identifier') or 'Capability')+': '+s['required_action'],
            capability_review={k:s.get(k) for k in ('stage','category','issue_id','identifier')})
        con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(parent,sort_keys=True),c['issue_id'],c['author_task']));con.commit()
        if s['stage']=='permitted':
            with b.db() as lookup:qualified(lookup,cfg,s)
            try:import calibration_controls_diagnostic as diagnostic
            except ImportError:from broker import calibration_controls_diagnostic as diagnostic
            diagnostic.handle_config(b,con,original,parent,diagnostic_configuration(cfg,s))
        if s.get('issue_id'):
            try:
                try:import handoff_runtime
                except ImportError:from broker import handoff_runtime
                handoff_runtime.publish(b,dict(issue_id=s['issue_id'],enabled=True,techlead=c['reviewer']),
                    dict(stage=s['stage'],owner=s['owner'],source_task=c['author_task'],data=json.dumps(dict(required_action=s['required_action']))))
            except Exception as error:
                con.execute('CREATE TABLE IF NOT EXISTS calibration_capability_publication_errors('
                    'issue_id TEXT,author_task TEXT,category TEXT,PRIMARY KEY(issue_id,author_task))')
                con.execute('INSERT OR REPLACE INTO calibration_capability_publication_errors VALUES(?,?,?)',
                    (c['issue_id'],c['author_task'],type(error).__name__));con.commit()
        return parent
    except (ValueError,KeyError,TypeError,ValidationError):
        # Enrollment/registration drift cannot create another diagnostic budget.
        c=original['source'];parent.update(owner=c['cto'],required_action='CTO diagnose capability registration/evidence drift; no identical retry',
            capability_review=dict(stage='blocked',category='capability_registration_rejected'))
        con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(parent,sort_keys=True),c['issue_id'],c['author_task']));con.commit();return parent
