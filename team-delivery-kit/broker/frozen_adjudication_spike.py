"""Controller-owned read-only SPIKE after an unresolved independent CTO verdict.

Fixed recipe only: run frozen suite with assertion observation, repeat with JS
event observation, require equivalence, then hand evidence back to the CTO once.
No implementation, test mutation, review approval or retry budget is granted.
"""
import copy
import hashlib
import json
import re
import time
import uuid

OPERATION='frozen_suite_adjudication_spike_v1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def qualify(e):
    row,route,data=e['row'],e['route'],json.loads(e['row']['data'])
    failure=data.get('validation_failure',{});decision=data.get('decision',{})
    task=e['task'];binding=e['binding'];red=e['red'];job=e['job'];result=job.get('result',{})
    paths=['/evidence/candidate/'+p for p in failure.get('diagnostic_read_files',[])]
    previous=['/evidence/previous/'+p for p in failure.get('diagnostic_read_files',[]) if p.startswith('tests/')]
    reads=e['reads']
    structure=e['structure'];struct_result=structure.get('result',{})
    try:verified=json.loads(struct_result.get('output',''))
    except ValueError:raise ValueError('actual immutable structure receipt required') from None
    if (row['stage']!='technical_decision_required' or row['owner']!=route['cto']
            or route.get('enabled') is not True or row['issue_id']!=route['issue_id']
            or route['author']==route['cto'] or data.get('target')!=route['cto']
            or data.get('artifact_diagnosis') is not True or decision.get('action')!='escalate_cto'
            or decision.get('optional_files')!=[] or e['native_decision']!=decision
            or task.get('id')!=data.get('recipient_task') or task.get('agent_id')!=route['cto']
            or task.get('status')!='completed' or task.get('wakeup_id')!=data.get('wakeup_id')
            or binding.get('status')!='closed' or binding.get('agent_id')!=route['cto']
            or binding.get('issue_id')!=row['issue_id']
            or binding.get('scope','').split(':')[-2:]!=['planning',task['id']]
            or e['source'].get('status')!='completed' or e['source'].get('agent_id')!=route['author']
            or e['source'].get('id')!=row['source_task'] or e['latest_author']!=row['source_task']
            or e['active'] or e['pending'] or e['consumed']
            or failure.get('source_task')!=row['source_task'] or failure.get('phase')!='frozen_green'
            or failure.get('category')!='executed_test_failure' or failure.get('exit_code')!=1
            or type(failure.get('tests_executed')) is not int or failure['tests_executed']<=0
            or e['snapshot'].get('status')!='complete' or e['snapshot'].get('volume')!=failure.get('volume')
            or e['snapshot'].get('task_id')!=row['source_task']
            or job.get('stage')!='complete' or result.get('approval') is not False
            or result.get('exit_code')!=1 or result.get('output_sha256')!=failure.get('output_sha256')
            or hashlib.sha256(result.get('output','').encode()).hexdigest()!=failure.get('output_sha256')
            or structure.get('stage')!='complete' or struct_result.get('exit_code')!=0
            or struct_result.get('approval') is not False
            or hashlib.sha256(struct_result.get('output','').encode()).hexdigest()!=struct_result.get('output_sha256')
            or verified.get('baseline_tests_intact') is not True
            or not re.fullmatch(r'[a-f0-9]{64}',verified.get('manifest_sha256',''))
            or verified.get('new_test_sha256')!=red.get('red',{}).get('test_sha256')
            or not red.get('red',{}).get('test_sha256') or not paths or not previous
            or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in paths+previous)):
        raise ValueError('source-bound completed CTO impasse with genuine frozen failure required')
    return dict(operation=OPERATION,source_task=row['source_task'],issue_id=row['issue_id'],cto=route['cto'],
        diagnostic_task=task['id'],volume=failure['volume'],failure=failure,
        hashes=red['red']['test_sha256'],saved_output=result['output'],image=e['image'],previous_handoff=copy.deepcopy(row),
        manifest_sha256=verified['manifest_sha256'],
        hypotheses=['frozen expectation and executed product interaction disagree',
                    'diagnostic tracing itself changes the measured interaction'],
        decision_rule='Only equivalent untraced/traced observations may inform CTO; no automatic defect classification',
        author_retry_authorized=False,test_change_authorized=False,delivery_approval=False)


def validate_pair(config,plain,traced):
    if (plain.get('operation')!='frozen_python_suite_assertion_observations_v2'
            or traced.get('operation')!='frozen_js_event_order_experiment_v1'
            or plain.get('approval') is not False or traced.get('approval') is not False
            or any(p.get('status')!='experiment_only_not_green_or_approval'
                   or p.get('output_sha256')!=config['failure']['output_sha256'] for p in (plain,traced))
            or not plain.get('runtime_observations') or plain.get('runtime_observations')!=traced.get('runtime_observations')
            or plain.get('manifest_sha256')!=traced.get('manifest_sha256')
            or plain.get('manifest_sha256')!=config['manifest_sha256']
            or plain.get('suite')!=traced.get('suite')
            or plain.get('suite',{}).get('tests')!=config['failure']['tests_executed']
            or plain['suite'].get('failures',0)<1 or plain['suite'].get('errors')!=0 or plain['suite'].get('skipped')!=0
            or not traced.get('event_reports') or any(p.get('truncated') is not False for p in traced['event_reports'])):
        raise ValueError('equivalent actual immutable failing runs required; trace is not Green')
    return dict(operation=OPERATION,manifest_sha256=plain['manifest_sha256'],
        observations=plain['runtime_observations'],suite=plain['suite'],events=traced['event_reports'],
        tracing_observations_equal=True,author_retry_authorized=False,test_change_authorized=False,delivery_approval=False)


def payload(config,traced):
    return dict(Image=config['image'],User='10000:10000',Entrypoint=['python'],Cmd=['/runtime_assertion_probe.py'],
        WorkingDir='/delivery',NetworkDisabled=True,
        Env=['PYTHONDONTWRITEBYTECODE=1','EVENT_ORDER_TRACE='+('1' if traced else '0'),
             'SAVED_OUTPUT='+json.dumps(config['saved_output']),'FROZEN_TEST_HASHES='+json.dumps(config['hashes'],sort_keys=True)],
        Labels={'delivery-kit.purpose':'adjudication-spike','delivery-kit.source-task':config['source_task']},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=536870912,NanoCpus=1000000000,PidsLimit=128,
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=512m,mode=1777'},
            Mounts=[dict(Type='volume',Source=config['volume'],Target='/delivery',ReadOnly=True)]))


def advance(config,state,effects,persist):
    """Persist each intent before effects; an uncertain effect is only observed."""
    state=copy.deepcopy(state)
    def save(**values):
        state.update(values);persist(copy.deepcopy(state))
    if state['stage'] in ('blocked','dispatched'):return state
    if state['stage']=='registered':save(stage='issue_intent')
    if state['stage']=='issue_intent':
        first=not state.get('issue_attempted')
        if first:save(issue_attempted=True,issue_attempted_at=time.time())
        try:issue=effects.issue(config,allow_create=first)
        except Exception as error:
            save(issue_observation_error=type(error).__name__)
            issue=None
        if not issue and time.time()-state['issue_attempted_at']>=1800:
            save(stage='blocked',category='issue_outcome_unconfirmed',required_action='observe original native issue intent; no repeated POST')
            return state
        if not issue:return state
        save(stage='plain',spike_issue=issue['id'],identifier=issue.get('identifier'))
    if state['stage'] in ('plain','traced'):
        traced=state['stage']=='traced';variant='traced' if traced else 'plain'
        task=str(uuid.uuid5(uuid.NAMESPACE_URL,OPERATION+':'+digest(config)+':'+variant))
        try:result=effects.job(task,payload(config,traced))
        except TimeoutError:return state
        if result['exit_code']!=0:
            save(stage='blocked',category='fixed_probe_failed',job_task=task,output_sha256=result['output_sha256'],
                 required_action='CTO diagnose fixed experiment; no identical retry');return state
        try:
            if hashlib.sha256(result['output'].encode()).hexdigest()!=result['output_sha256']:
                raise ValueError('captured probe output hash mismatch')
            proof=json.loads(result['output'])
        except ValueError:
            save(stage='blocked',category='invalid_probe_receipt');return state
        save(**{variant:proof},stage='decision_pending' if traced else 'traced')
    if state['stage']=='decision_pending':
        try:proof=validate_pair(config,state['plain'],state['traced'])
        except ValueError:
            save(stage='blocked',category='trace_contamination_or_incomplete_evidence',
                 required_action='CTO diagnose non-equivalent experiment; no mutation or replay');return state
        effects.handoff(config,proof,state['spike_issue'])
        save(stage='dispatched',proof_sha256=digest(proof),delivery_approval=False)
    return state


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS frozen_adjudication_spikes(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


class Effects:
    def __init__(self,b):
        self.b=b;self.settings=json.loads((b.STATE/'native.json').read_text())
    def issue(self,config,*,allow_create):
        try:from incremental_provisioning import NativeIssues
        except ImportError:from broker.incremental_provisioning import NativeIssues
        return NativeIssues(self.settings).ensure(config['desired'],allow_create=allow_create)
    def job(self,task,body):
        try:import test_first_job
        except ImportError:from broker import test_first_job
        with self.b.db() as c:return test_first_job.run(self.b,c,task,'copy',body)
    def handoff(self,config,proof,spike_issue):
        try:import handoffs,controller_maintenance
        except ImportError:from broker import handoffs,controller_maintenance
        marker=digest(dict(operation=OPERATION,config=digest(config),proof=digest(proof)))
        with self.b.db() as c:
            if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
            if controller_maintenance.current(c):raise TimeoutError('maintenance; observe same completed experiment')
            current=handoffs.load(c,config['source_task']);data=json.loads(current['data'])
            if data.get('adjudication_spike',{}).get('marker')==marker:return
            if current!=config['previous_handoff']:raise ValueError('source changed before SPIKE handoff')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
                raise TimeoutError('wait for diagnostic capacity')
            instruction=(data['instruction']+'\nYOU ARE THE CTO AND FINAL TECHNICAL OWNER, not a third party to consult. '
                'The controller completed a read-only SPIKE; the plain and traced suites failed identically. '
                'Use the actual observations and bound source to adjudicate the product-versus-test question. '
                'These observations prove neither a test defect nor acceptance. No assertion may be weakened. '
                'request_correction is a product proposal within the existing edit scope. '
                'request_test_revision requires evidence of a defective NEW test and fresh independent gates. '
                'If genuinely unresolved, escalate_cto naming ONE missing experiment or constraint; do not ask '
                'the CTO in the third person or the CEO for a technical decision. No edits, Green or approval. '
                'SPIKE card: '+spike_issue+'\nController experiment receipt: '+json.dumps(proof,sort_keys=True)+'\n')
            if len(instruction)>28000:raise ValueError('bounded complete SPIKE evidence required; no truncation')
            updated=copy.deepcopy(data)
            for field in ('recipient_task','wakeup_id','dispatched_at','alerted','decision','recipient_error',
                          'failed_dispatch_stage','control_error','control_error_count'):
                updated.pop(field,None)
            updated.update(adjudication_spike=dict(marker=marker,spike_issue=spike_issue,proof_sha256=digest(proof),
                config_sha256=digest(config),author_retry_authorized=False,test_change_authorized=False,delivery_approval=False),
                diagnostic_revision=data['diagnostic_revision']+':'+OPERATION,trigger_task=config['diagnostic_task'],
                error='technical_adjudication_unresolved',required_action='CTO adjudicate completed read-only SPIKE',
                dispatch_marker=marker,dispatch_stage='diagnose_cto',target=config['cto'],instruction=instruction)
            handoffs.save(c,config['source_task'],config['issue_id'],'dispatch_intent',config['cto'],updated,time.time(),commit=False)


def register(b,source_id):
    try:import handoffs,native,handoff_runtime,controller_maintenance,remediation_red_reference
    except ImportError:from broker import handoffs,native,handoff_runtime,controller_maintenance,remediation_red_reference
    with b.LOCK:
        with b.db() as c:
            initialize(c)
            if controller_maintenance.current(c):return None
            old=c.execute('SELECT config,state FROM frozen_adjudication_spikes WHERE source_task=?',(source_id,)).fetchone()
            if old:return tuple(map(json.loads,old))
            row=handoffs.load(c,source_id)
            if not row or row['stage']!='technical_decision_required':return None
            data=json.loads(row['data']);failure=data.get('validation_failure',{})
            if ((data.get('decision') or {}).get('action')!='escalate_cto'
                    or not data.get('artifact_diagnosis') or failure.get('phase')!='frozen_green'):return None
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            if row['owner']!=route['cto'] or not route.get('enabled'):return None
            latest=c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(row['issue_id'],)).fetchone()
            if latest[0]!=source_id:return None
            active=bool(c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone())
            if active:return None
            bindings=c.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(data.get('recipient_task'),)).fetchall()
            snapshots=c.execute('SELECT * FROM snapshots WHERE task_id=?',(source_id,)).fetchall()
            if len(bindings)!=1 or len(snapshots)!=1:return None
            jobs=[];structures=[]
            for item in c.execute('SELECT identity,state FROM validation_jobs'):
                identity,state=map(json.loads,item)
                if identity.get('task')==source_id and identity.get('kind')=='suite':jobs.append(state)
                if identity.get('task')==source_id and identity.get('kind')=='structure':structures.append(state)
            if len(jobs)!=1 or len(structures)!=1:return None
            redrow=c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(row['issue_id'],)).fetchone()
        red=json.loads(redrow[0]) if redrow else None
        if not red:
            reference=remediation_red_reference.qualified(b,row['issue_id'])
            if not reference:return None
            red=reference['red']
        fx=handoff_runtime.Effects(b,json.loads((b.STATE/'native.json').read_text()))
        runs=native.issue_task_runs(fx.settings,row['issue_id'])
        source=next((t for t in runs if t['id']==source_id),None)
        task=next((t for t in runs if t['id']==data.get('recipient_task')),None)
        authors=[t for t in runs if t.get('agent_id')==route['author']]
        if not source or not task or not authors:return None
        info=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')
        labels=info.get('Config',{}).get('Labels',{}) if info else {}
        if (not info or info.get('HostConfig',{}).get('ReadonlyRootfs') is not True
                or labels.get('com.docker.compose.project')!=b.PREFIX
                or labels.get('com.docker.compose.service')!='execution-broker'):raise ValueError('owned readonly SPIKE runner required')
        volume=b.docker('GET','/volumes/'+failure['volume'])
        labels=volume.get('Labels',{}) if volume else {}
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source_id:
            raise ValueError('owned immutable SPIKE input required')
        try:config=qualify(dict(row=row,route=route,source=source,task=task,binding=dict(bindings[0]),snapshot=dict(snapshots[0]),
            job=jobs[0],structure=structures[0],red=red,image=info['Image'],reads=fx.read_evidence(task),native_decision=fx.decision(task),
            latest_author=max(authors,key=lambda t:(t.get('created_at') or '',t['id']))['id'],
            active=active,pending=any(t.get('status') in ('queued','running','dispatched') for t in runs),consumed=False))
        except ValueError:return None
        try:from incremental_provisioning import NativeIssues
        except ImportError:from broker.incremental_provisioning import NativeIssues
        parent=NativeIssues(fx.settings).request('/issues/'+row['issue_id'])
        config['desired']=dict(title='SPIKE frozen-suite adjudication '+digest(config)[:12],
            description='CONTROLLER READ-ONLY SPIKE '+digest(config)+'\nOwner: CTO '+config['cto']+
                '\nSource task: '+source_id+'\nHypotheses: '+json.dumps(config['hypotheses'])+
                '\nRecipe: immutable full-suite assertion observation; repeat with JS event tracing. '+
                'Expected evidence: equivalent suite and assertion observations plus non-truncated event ordering. '+
                'Decision rule: '+config['decision_rule']+
                '\nExecution is controller-owned; CTO diagnosis stays bound to the parent issue. '+
                'No author/test change, Green, CI waiver or release approval. No agent assignment before bound permissions.',
            parent_issue_id=row['issue_id'],project_id=parent.get('project_id'),stage=0,status='todo')
        state=dict(stage='registered',owner=config['cto'],delivery_approval=False)
        with b.db() as c:
            if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
            if controller_maintenance.current(c) or handoffs.load(c,source_id)!=row:return None
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():return None
            c.execute('INSERT INTO frozen_adjudication_spikes VALUES(?,?,?)',(source_id,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))
        return config,state


def tick(b):
    try:import controller_maintenance
    except ImportError:from broker import controller_maintenance
    with b.LOCK:
        with b.db() as c:
            initialize(c)
            if controller_maintenance.current(c):return
            pending=c.execute("SELECT source_task FROM frozen_adjudication_spikes WHERE json_extract(state,'$.stage') NOT IN ('blocked','dispatched')").fetchall()
            candidates=c.execute("SELECT source_task FROM delivery_handoffs WHERE stage='technical_decision_required'").fetchall()
        for source_id in dict.fromkeys([r[0] for r in pending]+[r[0] for r in candidates]):
            try:registered=register(b,source_id)
            except ValueError:continue  # An ineligible older incident cannot starve unrelated handoffs.
            if not registered:continue
            config,state=registered
            def persist(value):
                with b.db() as c:c.execute('UPDATE frozen_adjudication_spikes SET state=? WHERE source_task=?',(json.dumps(value,sort_keys=True),source_id))
            try:
                outcome=advance(config,state,Effects(b),persist)
                if outcome['stage']=='blocked':
                    try:import handoffs
                    except ImportError:from broker import handoffs
                    with b.db() as c:
                        current=handoffs.load(c,source_id)
                        if current==config['previous_handoff']:
                            visible=json.loads(current['data'])
                            visible.update(error='technical_spike_blocked',required_action=outcome.get('required_action','CTO diagnose SPIKE receipt; no identical retry'),
                                adjudication_spike_failure=dict(category=outcome['category'],config_sha256=digest(config),delivery_approval=False))
                            handoffs.save(c,source_id,current['issue_id'],current['stage'],config['cto'],visible,time.time())
            except TimeoutError:continue
            except Exception as error:
                with b.db() as c:latest=json.loads(c.execute('SELECT state FROM frozen_adjudication_spikes WHERE source_task=?',(source_id,)).fetchone()[0])
                persist(dict(latest,stage='blocked',category=type(error).__name__,owner=config['cto'],
                    required_action='CTO diagnose SPIKE state; preserve handles, no identical retry',delivery_approval=False))
