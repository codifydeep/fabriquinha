"""Objection -> fixed isolated SPIKE -> independent referral -> one data proposal."""
import hashlib
import json
import time
import urllib.error
import os
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from generic_harness_calibration import digest,require
import calibration_objection_contract as contract
from structured_response_contract import _unique
try:import handoffs,generic_calibration_seam_job as jobs
except ImportError:from broker import handoffs,generic_calibration_seam_job as jobs


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_objections(issue_id TEXT,author_task TEXT,config TEXT,state TEXT,PRIMARY KEY(issue_id,author_task))')


def register(con,c,s):
    initialize(con);require(s['stage']=='blocked' and s['category']=='bundle_technical_objection')
    cfg=dict(source=c,objection=s['objection'],prior_state=s)
    row=con.execute('SELECT config,state FROM calibration_objections WHERE issue_id=? AND author_task=?',(c['issue_id'],c['author_task'])).fetchone()
    if row:
        old,state=map(json.loads,row)
        if old!=cfg:
            state.update(stage='blocked',owner=c['cto'],category='repeated_objection_requires_new_experiment',
                required_action='CTO diagnose a repeated objection; fixed SPIKE and data-submission budgets cannot rearm')
            con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',
                (json.dumps(state,sort_keys=True),c['issue_id'],c['author_task']));con.commit()
        return state
    state=dict(stage='issue_pending',owner=c['reviewer'],execution_authorized=False,delivery_approval=False,
        required_action='Create source-bound Path/Node SPIKE; original delivery remains blocked')
    con.execute('INSERT INTO calibration_objections VALUES(?,?,?,?)',(c['issue_id'],c['author_task'],json.dumps(cfg,sort_keys=True),json.dumps(state,sort_keys=True)));con.commit();return state


def review_context(cfg,s):return contract.context(digest(cfg['source']),digest(cfg['objection']),digest(s['probe']))


def instruction(cfg,s):
    proof=json.loads(s['probe']['output'])
    note=contract.capsule(review_context(cfg,s))+('INDEPENDENT TECH LEAD EVIDENCE REVIEW. No tools, edits, shell or product approval. '
        'A CTO returned an explicit calibration objection. Examine the measured fixed SPIKE, not assumptions. '
        'The experiment recognizes the frozen Python Path -> json.dumps(str(Path)) -> NODE_HARNESS source_path binding '
        'and executes only the recognized Node file-read statement with positive/negative sentinel files. '
        'It DOES NOT execute the whole JS harness or product tests, prove full calibration, or authorize an author retry. '
        'Choose refer_to_cto only if this supports one new data proposal on the SAME snapshot; otherwise retain_technical_hold. '
        'Every full calibration/TDD/review/PR/CI/deploy gate stays unchanged. reason<=200 characters; exact JSON schema.\n'
        'CTO objection: '+cfg['objection']['reason']+'\nMeasured bindings: '+json.dumps(proof['bindings'],separators=(',',':')))
    require(len(note)<=3800);return note


def advance(con,issue,author,fx,*,now=None):
    now=time.time() if now is None else now
    cfg,s=map(json.loads,con.execute('SELECT config,state FROM calibration_objections WHERE issue_id=? AND author_task=?',(issue,author)).fetchone())
    c=cfg['source']
    if s['stage']=='blocked' and s.get('category')=='experiment_plan_rejected' and getattr(fx,'controls_enabled',lambda:False)():
        fx.controls_step(con,cfg,s);return s
    if s['stage']=='blocked' and s.get('category') in ('objection_hold_retained','experiment_evidence_rejected','experiment_native_failed'):
        try:import calibration_experiment_runtime as experiment
        except ImportError:from broker import calibration_experiment_runtime as experiment
        return experiment.advance(con,cfg,s,fx,now=now)
    if s['stage'] in ('blocked','referred'):return s
    def save(**changes):
        s.update(changes);con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),issue,author));con.commit();return s
    def hold(category):return save(stage='blocked',owner=c['cto'],category=category,
        required_action='CTO diagnose '+category+' with preserved SPIKE/objection; no identical retry or author restart')
    try:fx.verify(cfg)
    except (ValueError,KeyError,TypeError):return hold('objection_source_changed')
    if s['stage'] in ('issue_pending','observe_issue'):
        first=s['stage']=='issue_pending'
        if first:save(stage='observe_issue',started=now)
        try:child=fx.issue(cfg,first)
        except (TimeoutError,urllib.error.URLError):child=None
        if child is None:return hold('objection_issue_unobserved') if now-s['started']>=600 else s
        return save(stage='probe_pending',issue_id=child['id'],identifier=child.get('identifier'),required_action='Controller execute one fixed readonly Path/Node SPIKE')
    if s['stage']=='probe_pending':
        try:
            result=fx.probe(cfg)
            from calibration_node_path_probe import validate
            require(result['approval'] is False and result['exit_code']==0 and hashlib.sha256(result['output'].encode()).hexdigest()==result['output_sha256'])
            validate(json.loads(result['output']),c)
        except TimeoutError:return s
        except (ValueError,KeyError,TypeError):return hold('node_path_spike_rejected')
        return save(stage='review_dispatch',probe=result,required_action='Tech Lead review exact fixed experiment and preserved CTO objection')
    if s['stage'] in ('review_dispatch','observe_review'):
        try:note=instruction(cfg,s)
        except ValueError:return hold('objection_context_bound')
        first=s['stage']=='review_dispatch'
        if first and not fx.reserve():return save(required_action='Await model reserve; no wakeup attempted')
        if first:save(stage='observe_review',marker=digest(dict(config=cfg,probe=s['probe'])),started=now)
        try:wake=fx.wake(cfg,s,first)
        except (TimeoutError,urllib.error.URLError):wake=None
        if wake is None:return hold('objection_review_unobserved') if now-s['started']>=600 else s
        return save(stage='review_wait',wakeup_id=wake['id'],started=s['started'],required_action='Observe exact independent review; never duplicate wakeup')
    if s['stage']=='review_wait':
        matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']]
        if len(matches)>1:return hold('objection_duplicate_reviews')
        if not matches or matches[0].get('status') in ('queued','dispatched','running'):
            return hold('objection_review_deadline') if now-s['started']>=1800 else s
        task=matches[0]
        if task.get('status')!='completed':return hold('objection_review_failed')
        try:
            require(task.get('agent_id')==c['reviewer'] and task.get('issue_id')==s['issue_id'])
            decision=fx.decision(cfg,s,task)
            require(decision['agent_id']==c['reviewer'] and decision['task_id']==task['id'])
            Draft202012Validator(contract.schema(review_context(cfg,s))).validate(decision['value'])
        except TimeoutError:return s
        except (ValueError,KeyError,TypeError,ValidationError):return hold('objection_review_invalid')
        if decision['value']['action']=='retain_technical_hold':return save(stage='blocked',owner=c['cto'],decision=decision,
            category='objection_hold_retained',required_action='CTO propose a genuinely different measured experiment; no repeat of this SPIKE')
        return save(stage='resume_pending',decision=decision,resume_started=now,required_action='Verify independent referral and exact source; one new data proposal only')
    require(s['stage']=='resume_pending')
    try:
        fx.verify_decision(cfg,s)
        if s.get('diagnostic_referral'):fx.verify_control_referral(cfg,s)
        elif s.get('experiment'):
            fx.verify_experiment(cfg,s)
        row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',(issue,author)).fetchone()
        require(list(map(json.loads,row))==[c,cfg['prior_state']])
        parent=handoffs.load(con,author);data=json.loads(parent['data']) if parent else {}
        if not parent or data.get('calibration_prerequisite')!=cfg['prior_state']:raise TimeoutError('observe source projection')
        require(parent['stage']=='test_first_blocked' and parent['issue_id']==issue)
        receipt=dict(operation='independent_objection_referral_v1',source_sha256=digest(c),prior_state=cfg['prior_state'],
            objection=cfg['objection'],probe=s['probe'],decision=s['decision'],submission_limit=1,
            author_restarted=False,tests_executed=False,execution_authorized=False,delivery_approval=False)
        if s.get('experiment'):receipt['experiment']=s['experiment']
        if s.get('diagnostic_referral'):
            receipt.update(diagnostic_referral=s['diagnostic_referral'],tests_executed=True,source_author_red_executed=False)
        updated={k:v for k,v in cfg['prior_state'].items() if k.endswith('_recovery_sha256') or k in ('incident_resume_id','incident_resume_sha256')}
        updated.update(stage='bundle_dispatch',owner=c['cto'],objection_resume_sha256=digest(receipt),
            execution_authorized=False,delivery_approval=False,required_action='CTO produce one new data proposal using measured SPIKE; all gates unchanged')
        data.update(calibration_prerequisite=updated,required_action=updated['required_action']);data.pop('error',None)
        data.pop('calibration_incident',None)
        s.update(stage='referred',referral=receipt,submission_consumed=True)
        with con:
            con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',(json.dumps(updated,sort_keys=True),issue,author))
            con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',(json.dumps(s,sort_keys=True),issue,author))
            handoffs.save(con,author,issue,'test_first_validation_pending',c['cto'],data,now,commit=False)
        return s
    except TimeoutError:return hold('objection_projection_deadline') if now-s['resume_started']>=600 else s
    except (ValueError,KeyError,TypeError,ValidationError):return hold('objection_referral_rejected')


def qualified(con,c,s):
    row=con.execute('SELECT config,state FROM calibration_objections WHERE issue_id=? AND author_task=?',(c['issue_id'],c['author_task'])).fetchone()
    require(row is not None);cfg,state=map(json.loads,row);r=state['referral']
    require(state['stage']=='referred' and state['submission_consumed'] is True and cfg['source']==c
        and r['source_sha256']==digest(c) and r['submission_limit']==1 and digest(r)==s['objection_resume_sha256']
        and all(r[k] is False for k in ('author_restarted','execution_authorized','delivery_approval')))
    if r.get('diagnostic_referral'):
        try:import calibration_controls_diagnostic as diagnostic
        except ImportError:from broker import calibration_controls_diagnostic as diagnostic
        require(r['tests_executed'] is True and r['source_author_red_executed'] is False)
        diagnostic.cached_referral(con,c,r['diagnostic_referral'])
    else:require(r['tests_executed'] is False)
    return r


def addendum(r):
    if r.get('diagnostic_referral'):
        from diagnostic_control_transport import MARKER
        return ('\nIndependent measured full-harness diagnostic referral: positive references passed; each negative failed its test body. '
            'Not product approval or author Red. Propose new verified data; preserve all gates. Evidence '+digest(r['diagnostic_referral'])+'.\n'
            +MARKER+':'+r['source_sha256']+'\n')
    if r.get('experiment'):
        e=r['experiment'];require(e['stage']=='permitted')
        return ('\nIndependent experiment PLAN permit, not results/approval. Full harness + positive/negative controls remain required. '
            'Method: '+e['proposal']['value']['method']+' Plan SHA '+digest(e['proposal'])+'.')
    proof=json.loads(r['probe']['output'])
    facts={p:dict(attribute=b['attribute'],product_path=b['product_path'],line=b['line']) for p,b in proof['bindings'].items()}
    return '\nIndependent SPIKE referral (not approval): '+json.dumps(facts,separators=(',',':'))+(
        '. Recognized Path is formatted into Node source_path; actual isolated Node read switched sentinel bytes. '
        'Whole harness/product tests NOT run. Snapshot/template unchanged. Probe SHA '+r['probe']['output_sha256']+'.')


def projection(con,issue,author,source):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_objections'").fetchone():return None
    row=con.execute('SELECT config,state FROM calibration_objections WHERE issue_id=? AND author_task=?',(issue,author)).fetchone()
    if not row:return None
    cfg,s=map(json.loads,row)
    if s['stage']=='referred' or cfg['prior_state']!=source:return None
    return dict(kind='calibration_objection',stage=s['stage'],identifier=s.get('identifier'),issue_id=s.get('issue_id'),
        owner=s['owner'],required_action=s['required_action'],author_retry_authorized=False,delivery_approval=False)


class Effects:
    def __init__(self,b):
        try:import generic_calibration_workflow as workflow,native
        except ImportError:from broker import generic_calibration_workflow as workflow,native
        self.b=b;self.workflow=workflow;self.native=native;self.source=workflow.Effects(b);self.plans=self.source.plans
    def controls_enabled(self):return bool(os.environ.get('BROKER_GENERIC_CALIBRATION_CONTROLS_IMAGE'))
    def controls_step(self,con,cfg,s):
        try:import calibration_controls_diagnostic as diagnostic
        except ImportError:from broker import calibration_controls_diagnostic as diagnostic
        return diagnostic.handle(self.b,con,cfg,s)
    def verify_control_referral(self,cfg,s):
        try:import calibration_controls_diagnostic as diagnostic
        except ImportError:from broker import calibration_controls_diagnostic as diagnostic
        diagnostic.verify_referral(self.b,cfg['source'],s['diagnostic_referral'])
    def verify(self,cfg):
        c=cfg['source'];self.source.verify(c);require(self.workflow.request(self.b,c['issue_id'],c['author_task'])==cfg['prior_state'])
        task=self.plans.task(cfg['objection']['producer_task'],c['cto'])
        require(self.source.objection(c,task,cfg['objection']['wakeup_id'])==cfg['objection'])
    def probe(self,cfg):
        with self.b.db() as con:return jobs.run(self.b,con,cfg['source'],kind='node')
    def reserve(self):return self.plans.native.remaining_calls()>=32
    def issue(self,cfg,first):
        c=cfg['source'];parent=self.plans.issues.request('/issues/'+c['issue_id'])
        return self.plans.issues.ensure(dict(title='SPIKE Path/Node calibration '+digest(c)[:12],
            description='Verify source-bound CTO objection '+digest(cfg['objection'])+'. Fixed read-only Node experiment; no author retry or approval.',
            parent_issue_id=c['issue_id'],project_id=parent.get('project_id'),stage=1,status='todo'),allow_create=first)
    def wake(self,cfg,s,first):
        c=cfg['source'];require(self.plans.settings['agents'].get(c['reviewer'])=='planning')
        return self.native.ensure_planning_start(self.plans.settings,s['issue_id'],c['reviewer'],c['author_task'],s['marker'],instruction(cfg,s),allow_create=first)
    def runs(self,cfg,s):return self.native.issue_task_runs(self.plans.settings,s['issue_id'])
    def decision(self,cfg,s,task):
        return self.read_decision(cfg,s,task,cfg['source']['reviewer'],contract,review_context(cfg,s))
    def read_decision(self,cfg,s,task,actor,module,context):
        c=cfg['source'];actual=self.plans.task(task['id'],actor)
        require(actual.get('status')=='completed' and actual.get('issue_id')==s['issue_id'] and actual.get('wakeup_id')==s['wakeup_id']
            and module.request(dict(messages=[dict(role='user',content=actual.get('handoff_note',''))]))==context)
        with self.b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(task['id'],)).fetchall();require(len(rows)==1);r=dict(rows[0])
            if r['status'] in ('creating','starting','running','closing'):raise TimeoutError('observe review lease')
            require(r['status']=='closed' and r['agent_id']==actor and r['issue_id']==s['issue_id']
                and r['scope'].split(':')[-2:]==['planning',task['id']]
                and con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(r['request_id'],)).fetchone()[0]==0)
        raw=(actual.get('result') or {}).get('output');require(isinstance(raw,str) and 1<=len(raw)<=4096)
        value=json.loads(raw,object_pairs_hook=_unique);Draft202012Validator(module.schema(context)).validate(value)
        return dict(task_id=task['id'],agent_id=actor,execution_id=r['request_id'],value=value)
    def verify_decision(self,cfg,s):
        task=self.plans.task(s['decision']['task_id'],cfg['source']['reviewer'])
        require(self.decision(cfg,s,task)==s['decision'] and self.probe(cfg)==s['probe'])
    def experiment_wake(self,cfg,s,actor,note,first):
        require(self.plans.settings['agents'].get(actor)=='planning')
        return self.native.ensure_planning_start(self.plans.settings,s['issue_id'],actor,cfg['source']['author_task'],s['experiment']['marker'],note,allow_create=first)
    def experiment_decision(self,cfg,s,task,phase):
        try:import calibration_experiment_runtime as experiment
        except ImportError:from broker import calibration_experiment_runtime as experiment
        shadow={**s,'wakeup_id':s['experiment']['wakeup_id']}
        # Persisted receipts retain their original wakeup as the next phase advances.
        key='proposal' if phase=='design' else 'review'
        if key in s['experiment']:shadow['wakeup_id']=s['experiment'][key]['wakeup_id']
        result=self.read_decision(cfg,shadow,task,cfg['source']['cto' if phase=='design' else 'reviewer'],experiment.contract,experiment.context(cfg,s,phase))
        return {**result,'wakeup_id':shadow['wakeup_id']}
    def verify_experiment(self,cfg,s):
        try:import calibration_experiment_runtime as experiment
        except ImportError:from broker import calibration_experiment_runtime as experiment
        experiment.verify(cfg,s,self)
    def experiment_format_rejection(self,cfg,s,task,phase):
        try:import calibration_experiment_runtime as experiment,calibration_incidents as incidents
        except ImportError:from broker import calibration_experiment_runtime as experiment,calibration_incidents as incidents
        actor=cfg['source']['cto' if phase=='design' else 'reviewer'];actual=self.plans.task(task['id'],actor)
        require(actual.get('status')=='failed' and actual.get('failure_reason')=='agent_error.provider_server_error'
            and actual.get('wakeup_id')==s['experiment']['wakeup_id'] and actual.get('issue_id')==s['issue_id']
            and actual.get('agent_id')==actor and experiment.contract.request(dict(messages=[dict(role='user',
                content=actual.get('handoff_note',''))]))==experiment.context(cfg,s,phase))
        with self.b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(task['id'],)).fetchall()
            require(len(rows)==1);r=dict(rows[0])
            if r['status'] in ('creating','starting','running','closing'):raise TimeoutError('observe exact failed experiment lease')
            require(r['status']=='closed' and r['agent_id']==actor and r['issue_id']==s['issue_id']
                and r['scope'].split(':')[-2:]==['planning',task['id']]
                and con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(r['request_id'],)).fetchone()[0]==0)
        receipt,_=incidents.Effects(self.b).evidence(r['request_id'])
        if receipt.get('category')!='schema_violation' or receipt.get('diagnostic',{}).get('constraints')!=['maxLength']:return None
        return dict(receipt=receipt,context_sha256=digest(experiment.context(cfg,s,phase)))


def handle(b,con,c,s):
    register(con,c,s);fx=Effects(b);state=advance(con,c['issue_id'],c['author_task'],fx)
    if state.get('issue_id'):
        try:import handoff_runtime
        except ImportError:from broker import handoff_runtime
        handoff_runtime.publish(b,dict(issue_id=state['issue_id'],enabled=True,techlead=c['reviewer']),
            dict(stage=state['stage'],owner=state['owner'],source_task=c['author_task'],data=json.dumps(dict(required_action=state['required_action']))))
    return state
