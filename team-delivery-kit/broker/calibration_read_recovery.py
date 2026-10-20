"""One evidence-backed read-context repair, never a retry of the author.

An invalid-JSON producer incident with an inapplicable terminal-framing probe
may qualify a DIFFERENT experiment: static dependency discovery and mandatory
pagination. Two new native technical decisions must sponsor the changed input
contract. The old failure, decision, incident and every delivery gate survive.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error

import calibration_dependency_probe as probe
import calibration_response_contract as wire
from generic_harness_calibration import digest,require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_read_recoveries(recovery_id TEXT PRIMARY KEY,config TEXT,state TEXT)')


def key(c):return digest(dict(source=digest(c),protocol='full_dependency_reads_v1'))


def inapplicable_json_request(cfg,state):
    diagnostic=cfg.get('rejection',{}).get('diagnostic',{})
    decision=state.get('cto_decision',{}).get('value',{})
    return (diagnostic.get('version')=='calibration-constraint-v2' and diagnostic.get('failure_code')=='invalid_json'
        and state.get('stage')=='blocked' and state.get('category') in
            ('incident_experiment_not_applicable','incident_hold_binding_rejected')
        and state.get('observed_phase')=='diagnosis' and decision.get('action')=='request_transport_probe'
        and decision.get('experiment')=='fixed_transport_probe_v1'
        and not any(state.get(k) for k in ('probe','decision','json_format_addendum_consumed','prior_hold')))


def instruction(cfg,s,phase):
    actor='CTO technical assessment' if phase=='cto' else 'Independent Tech Lead assessment'
    facts=dict(source_sha256=digest(cfg['source']),manifest_sha256=cfg['source']['prepared']['manifest_sha256'],
        experiment_sha256=digest(s['measurement']),required_paths=s['measurement']['required_paths'],
        previously_incomplete=s['missing_reads'],checks=s['measurement']['checks'])
    note=(actor+'. NEW READ-CONTEXT EXPERIMENT, NOT A TERMINAL-TRANSPORT RETRY. '
        'The earlier producer failed invalid_json. Its response bytes were not preserved, so this experiment '
        'does NOT prove the historical cause or that JSON mode was absent. The prior CTO request for a '
        'terminal-framing probe remains preserved and was not applicable to this diagnostic class. '
        'A fixed offline AST-only probe now found literal Path globals in the frozen test. It verified '
        'that the existing wire contract can require all those product files completely before proposal. '
        'The earlier producer did not fully observe at least one of these files. No test/product bytes '
        'were changed and no delivered code was executed. Evaluate whether this genuinely changed input '
        'contract justifies ONE new calibration DATA proposal on the SAME snapshot. '
        'Choose request_correction only if justified, or escalate_cto with the measurable remaining concern. '
        'This is not permission for tools, author retry, test weakening, source reset, Red, Green, merge '
        'or release approval. Normal calibration still needs independent policy review and actual sandbox controls. '
        'No tools. Return exactly {action,reason,optional_files}; optional_files=[], reason target250/max1200 characters.\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\nFacts: '+json.dumps(facts,sort_keys=True))
    if phase=='review':note+='\nCTO decision: '+json.dumps(s['cto_decision']['value'],sort_keys=True)
    require(phase in ('cto','review') and len(note)<=3800);return note


def validate_measurement(cfg,result):
    c=cfg['source']
    require(result['operation']=='static_calibration_dependency_probe_v1'
        and result['manifest_sha256']==c['prepared']['manifest_sha256'] and result['test_sha256']==c['prepared']['test_sha256']
        and result['script_sha256']==hashlib.sha256(Path(probe.__file__).read_bytes()).hexdigest()
        and result['contract_sha256']==hashlib.sha256(Path(wire.__file__).read_bytes()).hexdigest()
        and result['checks']==probe.read_contract_experiment() and type(result['model_calls']) is int and result['model_calls']==0
        and all(result[k] is False for k in ('product_tests_executed','historical_cause_proven','author_retry_authorized',
            'execution_authorized','delivery_approval')))
    baseline={'/evidence/'+r+'/'+p for r in ('candidate','previous') for p in c['test_files']}
    deps=result['dependencies'];require(isinstance(deps,list) and 1<=len(deps)<=512)
    paths=baseline|{'/evidence/candidate/'+d['path'] for d in deps}
    require(result['required_paths']==sorted(paths) and paths>baseline
        and all(d['module'] in c['test_files'] and re.fullmatch('[A-Z][A-Z0-9_]{0,119}',d['attribute'])
            and wire.safe_path('/evidence/candidate/'+d['path'],'bundle')
            and re.fullmatch('[a-f0-9]{64}',d['sha256']) for d in deps))
    return paths-baseline


def advance(con,cfg,fx,*,now=None):
    initialize(con);now=time.time() if now is None else now;k=key(cfg['source'])
    row=con.execute('SELECT config,state FROM calibration_read_recoveries WHERE recovery_id=?',(k,)).fetchone()
    if row:require(json.loads(row[0])==cfg);s=json.loads(row[1])
    else:
        s=dict(stage='measure',owner=cfg['source']['cto'],source_reset=False,author_retry_authorized=False,
            execution_authorized=False,delivery_approval=False)
        con.execute('INSERT INTO calibration_read_recoveries VALUES(?,?,?)',
            (k,json.dumps(cfg,sort_keys=True),json.dumps(s,sort_keys=True)));con.commit()
    if s['stage'] in ('blocked','armed'):return s
    def save(**changes):
        s.update(changes);con.execute('UPDATE calibration_read_recoveries SET state=? WHERE recovery_id=?',
            (json.dumps(s,sort_keys=True),k));con.commit();return s
    def hold(category):return save(stage='blocked',category=category,owner=cfg['source']['cto'],
        required_action='CTO diagnose '+category+' from preserved evidence; no identical data submission or author retry')
    try:
        fx.verify(cfg)
        if s['stage']=='measure':
            job=fx.measure(cfg);raw=job['output']
            require(job['approval'] is False and type(job['exit_code']) is int and job['exit_code']==0
                and job['output_sha256']==hashlib.sha256(raw.encode()).hexdigest())
            result=json.loads(raw);extra=validate_measurement(cfg,result);observed=fx.failed_reads(cfg)
            missing=sorted(p for p in extra if not (type(observed.get(p,{}).get('total_lines')) is int
                and observed[p].get('total_lines',0)>0 and observed[p].get('lines')==observed[p]['total_lines']))
            require(missing)
            producer_instruction(cfg['source'],dict(measurement=result)) # Bounds before spending native decisions.
            preview={**s,'measurement':result,'missing_reads':missing,'cto_decision':{'value':
                dict(action='request_correction',reason='x'*1200,optional_files=[])}}
            # Prospective size check only: this fixture is not persisted or
            # presented as a native decision/approval.
            instruction(cfg,preview,'cto');instruction(cfg,preview,'review')
            return save(stage='issue_pending',measurement=result,measurement_job=job,missing_reads=missing,
                required_action='Create technical SPIKE for changed mandatory dependency reads; no data proposal yet')
        if s['stage'] in ('issue_pending','issue_observe'):
            first=s['stage']=='issue_pending'
            if first:save(stage='issue_observe',phase_started=now)
            issue=fx.issue(cfg,s,first)
            if issue is None:return hold('dependency_issue_unobserved') if now-s['phase_started']>=600 else s
            return save(stage='cto_dispatch',issue_id=issue['id'],identifier=issue.get('identifier'),phase_started=now,
                required_action='CTO assess measured read-context change; historical JSON cause remains unknown')
        if s['stage']=='arm':
            fx.validate_decisions(cfg,s)
            receipt=dict(operation='independent_dependency_read_sponsorship_v1',source_config_sha256=digest(cfg['source']),
                previous_state=cfg['previous_state'],previous_incident_id=cfg['incident_id'],
                previous_incident_decision=cfg['incident_decision'],measurement=s['measurement'],measurement_job=s['measurement_job'],
                missing_reads=s['missing_reads'],cto_decision=s['cto_decision'],review_decision=s['review_decision'],
                submission_limit=1,author_retry_authorized=False,source_reset=False,execution_authorized=False,delivery_approval=False)
            con.execute('SAVEPOINT dependency_read_arm')
            try:
                fx.arm(con,cfg,s,k,receipt)
                s.update(stage='armed',receipt=receipt,submission_consumed=True,
                    required_action='Observe one new data proposal with stronger read capsule; all normal delivery gates remain required')
                con.execute('UPDATE calibration_read_recoveries SET state=? WHERE recovery_id=?',
                    (json.dumps(s,sort_keys=True),k))
                con.execute('RELEASE SAVEPOINT dependency_read_arm');con.commit()
                return s
            except Exception:
                con.execute('ROLLBACK TO SAVEPOINT dependency_read_arm');con.execute('RELEASE SAVEPOINT dependency_read_arm')
                raise
        phase='cto' if s['stage'].startswith('cto_') else 'review';actor=cfg['source']['cto' if phase=='cto' else 'reviewer']
        if s['stage'] in (phase+'_dispatch',phase+'_observe'):
            first=s['stage']==phase+'_dispatch'
            if first:
                if not fx.reserve():return s
                save(stage=phase+'_observe',marker=digest(dict(config=digest(cfg),phase=phase,note=instruction(cfg,s,phase))),phase_started=now)
            wake=fx.wake(cfg,s,phase,first)
            if wake is None:return hold('dependency_wakeup_unobserved') if now-s['phase_started']>=600 else s
            return save(stage=phase+'_wait',wakeup_id=wake['id'],owner=actor,
                required_action='Observe exact native '+phase+' assessment; no duplicate wakeup or author restart')
        require(s['stage']==phase+'_wait')
        matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']];require(len(matches)<=1)
        if not matches or matches[0]['status'] in ('queued','dispatched','running'):
            return hold('dependency_native_deadline') if now-s['phase_started']>=1800 else s
        task=matches[0];require(task['status']=='completed' and task['agent_id']==actor)
        decision=fx.decision(cfg,s,phase,task)
        require(decision['agent_id']==actor and decision['task_id']==task['id']
            and decision['value']['action'] in ('request_correction','escalate_cto')
            and set(decision['value'])=={'action','reason','optional_files'} and decision['value']['optional_files']==[]
            and isinstance(decision['value']['reason'],str) and 0<len(decision['value']['reason'])<=1200)
        save(**{phase+'_decision':decision,phase+'_wakeup':s['wakeup_id'],phase+'_marker':s['marker']})
        if decision['value']['action']=='escalate_cto':return hold('dependency_technical_hold_retained')
        return save(stage='review_dispatch' if phase=='cto' else 'arm',phase_started=now,
            owner=cfg['source']['reviewer' if phase=='cto' else 'cto'],
            required_action='Tech Lead independently assess changed read contract' if phase=='cto' else
                'Controller reauthenticate both native decisions before one new DATA proposal; not delivery approval')
    except (TimeoutError,urllib.error.URLError):return s
    except (ValueError,KeyError,TypeError):return hold('dependency_evidence_rejected')


def qualified(con,c,s):
    initialize(con);row=con.execute('SELECT config,state FROM calibration_read_recoveries WHERE recovery_id=?',
        (s['dependency_read_recovery_id'],)).fetchone();require(row)
    cfg,state=map(json.loads,row);receipt=state['receipt']
    require(cfg['source']==c and state['stage']=='armed' and state['submission_consumed'] is True
        and receipt['source_config_sha256']==digest(c) and digest(receipt)==s['dependency_read_recovery_sha256']
        and receipt['submission_limit']==1 and receipt['previous_state']==cfg['previous_state']
        and all(receipt[k] is False for k in ('author_retry_authorized','source_reset','execution_authorized','delivery_approval')))
    validate_measurement(cfg,receipt['measurement']);return receipt


def producer_instruction(c,receipt):
    try:import generic_calibration_workflow as flow
    except ImportError:from broker import generic_calibration_workflow as flow
    original=flow.instruction(c);old=wire.request(dict(messages=[dict(role='user',content=original)]))
    current={**old,'required_paths':receipt['measurement']['required_paths']}
    require(set(current['required_paths'])>set(old['required_paths']))
    new=wire.capsule(current)+original.removeprefix(wire.capsule(old))
    new+='\nQualified changed input: read ALL declared fixture dependencies completely before any DATA proposal. No release authority.\n'
    require(len(new)<=3800);return new


def projection(con,issue,author,state):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_read_recoveries'").fetchone():return None
    matches=[]
    for row in con.execute('SELECT recovery_id,config,state FROM calibration_read_recoveries'):
        cfg,s=map(json.loads,(row[1],row[2]));c=cfg['source']
        if c['issue_id']==issue and c['author_task']==author and cfg['previous_state']==state and s['stage']!='armed':
            matches.append(dict(incident_id=row[0],stage=s['stage'],issue_id=s.get('issue_id'),identifier=s.get('identifier'),
                owner=s['owner'],required_action=s.get('required_action') or 'Observe exact dependency-read SPIKE',
                author_retry_authorized=False,delivery_approval=False))
    require(len(matches)<=1);return matches[0] if matches else None


class Effects:
    def __init__(self,b):
        try:import generic_calibration_workflow as flow,calibration_incidents as incidents
        except ImportError:from broker import generic_calibration_workflow as flow,calibration_incidents as incidents
        self.b=b;self.flow=flow;self.incidents=incidents;self.source=flow.Effects(b);self.old=incidents.Effects(b)
    def verify(self,cfg):
        c=cfg['source'];self.source.verify(c)
        require(self.flow.request(self.b,c['issue_id'],c['author_task'])==cfg['previous_state'])
        with self.b.db() as con:
            row=con.execute('SELECT config,state FROM calibration_incidents WHERE incident_id=?',(cfg['incident_id'],)).fetchone();require(row)
        old,s=map(json.loads,row)
        require(digest(old)==cfg['incident_config_sha256'] and inapplicable_json_request(old,s)
            and s['cto_decision']==cfg['incident_decision'] and old['rejection']['diagnostic']['failure_code']=='invalid_json'
            and old['rejection']['diagnostic']['version']=='calibration-constraint-v2'
            and s['cto_decision']['value']['action']=='request_transport_probe'
            and old['failed_task']==cfg['previous_state']['observed_task'])
        self.old.verify(old)
        task=self.old.plans.task(s['cto_decision']['task_id'],c['cto'])
        require(self.old.decision(old,{**s,'wakeup_id':task['wakeup_id']},'diagnosis',task)==s['cto_decision'])
        require(os.environ['BROKER_CALIBRATION_DEPENDENCY_PROBE_IMAGE']==cfg['image'])
    def measure(self,cfg):
        try:import validation_job
        except ImportError:from broker import validation_job
        c=cfg['source']
        payload=dict(Image=cfg['image'],User='10000:10000',Entrypoint=['python'],
            Cmd=['/calibration_dependency_probe.py','/candidate',c['prepared']['manifest_sha256'],json.dumps(c['test_files'])],
            Env=['PYTHONDONTWRITEBYTECODE=1'],HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
                SecurityOpt=['no-new-privileges'],Memory=268435456,NanoCpus=1000000000,PidsLimit=32,
                Mounts=[dict(Type='volume',Source=c['candidate_volume'],Target='/candidate',ReadOnly=True)],
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'}),Labels={'delivery-kit.dependency-recovery':key(c)})
        return validation_job.run(self.b,cfg['previous_state']['observed_task'],'structure',payload)
    def failed_reads(self,cfg):
        t=self.source.plans.task(cfg['previous_state']['observed_task'],cfg['source']['cto'])
        require(t['status']=='failed' and t['issue_id']==cfg['source']['issue_id']);return self.source.plans.reads(t)
    def reserve(self):return self.source.plans.native.remaining_calls()>=64
    def issue(self,cfg,s,first):
        c=cfg['source'];parent=self.source.plans.issues.request('/issues/'+c['issue_id'])
        return self.source.plans.issues.ensure(dict(title='SPIKE full dependency reads '+key(c)[:12],
            description='Static immutable inputs -> CTO -> independent Lead -> at most one changed DATA proposal. '
                'Prior incident '+cfg['incident_id']+' preserved; no author retry, product change or delivery approval.',
            parent_issue_id=c['issue_id'],project_id=parent.get('project_id'),status='todo',stage=1),allow_create=first)
    def wake(self,cfg,s,phase,first):
        try:import native
        except ImportError:from broker import native
        from decision_schema import apply
        from typed_decision_contract import apply as typed,NAME
        note=instruction(cfg,s,phase)
        body=typed(apply(dict(messages=[dict(role='user',content=note)],tools=[])))
        require(body.get('tool_choice')==dict(type='function',function=dict(name=NAME)) and len(body['tools'])==1
            and set(body['tools'][0]['function']['parameters']['properties'])=={'action','reason','optional_files'})
        return native.ensure_planning_start(self.source.plans.settings,s['issue_id'],
            cfg['source']['cto' if phase=='cto' else 'reviewer'],cfg['source']['author_task'],s['marker'],note,allow_create=first)
    def runs(self,cfg,s):
        try:import native
        except ImportError:from broker import native
        return native.issue_task_runs(self.source.plans.settings,s['issue_id'])
    def decision(self,cfg,s,phase,task):
        try:import native_scope_note
        except ImportError:from broker import native_scope_note
        actor=cfg['source']['cto' if phase=='cto' else 'reviewer'];actual=self.source.plans.task(task['id'],actor)
        require(actual['status']=='completed' and actual['issue_id']==s['issue_id'] and actual['wakeup_id']==s['wakeup_id'])
        note='DELIVERY_PLANNING_START '+s['marker']+'\nSource: '+cfg['source']['author_task']+'\n'+instruction(cfg,s,phase).strip()
        require(native_scope_note.canonical(actual.get('handoff_note',''),s['wakeup_id'])==note)
        with self.b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(actual['id'],)).fetchall()
            require(len(rows)==1);r=rows[0]
            if r['status']!='closed':raise TimeoutError('observe exact native decision lease')
            require(r['agent_id']==actor and r['issue_id']==s['issue_id'] and r['scope'].split(':')[-2:]==['planning',actual['id']]
                and con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(r['request_id'],)).fetchone()[0]==0)
        raw=(actual.get('result') or {}).get('output');require(isinstance(raw,str) and 0<len(raw.encode())<=4096)
        from structured_response_contract import _unique
        return dict(task_id=actual['id'],agent_id=actor,execution_id=r['request_id'],value=json.loads(raw,object_pairs_hook=_unique),
            output_sha256=hashlib.sha256(raw.encode()).hexdigest())
    def validate_decisions(self,cfg,s):
        for phase in ('cto','review'):
            d=s[phase+'_decision'];shadow={**s,'wakeup_id':s[phase+'_wakeup'],'marker':s[phase+'_marker']}
            require(self.decision(cfg,shadow,phase,{'id':d['task_id']})==d and d['value']['action']=='request_correction')
        require(s['cto_decision']['task_id']!=s['review_decision']['task_id']
            and s['cto_decision']['agent_id']!=s['review_decision']['agent_id'])
        job=self.measure(cfg);require(job==s['measurement_job'] and json.loads(job['output'])==s['measurement'])
    def arm(self,con,cfg,s,k,receipt):
        try:import handoffs
        except ImportError:from broker import handoffs
        c=cfg['source']
        current=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
            (c['issue_id'],c['author_task'])).fetchone();require(current and list(map(json.loads,current))==[c,cfg['previous_state']])
        parent=handoffs.load(con,c['author_task']);require(parent and parent['stage']=='test_first_blocked'
            and json.loads(parent['data']).get('calibration_prerequisite')==cfg['previous_state'])
        updated=dict(stage='bundle_dispatch',owner=c['cto'],dependency_read_recovery_id=k,
            dependency_read_recovery_sha256=digest(receipt),execution_authorized=False,delivery_approval=False,
            required_action='One independently sponsored proposal with full frozen dependency reads; no author restart')
        # The caller commits this parent transition together with stage=armed.
        con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(updated,sort_keys=True),c['issue_id'],c['author_task']))


def handle(b,con,c,s):
    initialize(con);k=key(c)
    row=con.execute('SELECT config FROM calibration_read_recoveries WHERE recovery_id=?',(k,)).fetchone()
    if row:cfg=json.loads(row[0])
    else:
        if s.get('stage')!='blocked' or s.get('category')!='bundle_task_failed':return None
        incident=None
        for row in con.execute('SELECT incident_id,config,state FROM calibration_incidents'):
            old,held=map(json.loads,(row[1],row[2]))
            if old.get('source_config_sha256')==digest(c) and inapplicable_json_request(old,held):
                require(incident is None);incident=(row[0],old,held)
        if not incident:return None
        identifier,old,held=incident
        diagnostic=old['rejection']['diagnostic']
        if diagnostic.get('version')!='calibration-constraint-v2' or diagnostic.get('failure_code')!='invalid_json':return None
        image=os.environ.get('BROKER_CALIBRATION_DEPENDENCY_PROBE_IMAGE','');require(re.fullmatch('sha256:[a-f0-9]{64}',image))
        cfg=dict(source=c,previous_state=s,incident_id=identifier,incident_config_sha256=digest(old),
            incident_decision=held['cto_decision'],image=image)
    result=advance(con,cfg,Effects(b))
    if result.get('issue_id'):
        try:
            try:import handoff_runtime
            except ImportError:from broker import handoff_runtime
            handoff_runtime.publish(b,dict(issue_id=result['issue_id'],enabled=True,techlead=c['reviewer']),
                dict(stage='dependency_read_'+result['stage'],owner=result['owner'],source_task=c['author_task'],
                    data=json.dumps(dict(required_action=result.get('required_action'),delivery_approval=False))))
        except (ValueError,RuntimeError,TimeoutError,urllib.error.URLError) as error:
            con.execute('CREATE TABLE IF NOT EXISTS calibration_read_publication_errors(recovery_id TEXT PRIMARY KEY,category TEXT)')
            con.execute('INSERT OR REPLACE INTO calibration_read_publication_errors VALUES(?,?)',(k,type(error).__name__));con.commit()
    return result
