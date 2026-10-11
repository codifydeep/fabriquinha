"""Durable native CTO bundle dispatch; proposals never authorize delivery.

The current terminal prerequisite is calibration_ready, owned by the technical
controller. It is not success: author Red must subsequently pass its separate
gate using the same immutable delivery, before independent product review.
"""
import hashlib
import json
import time
import urllib.error

from generic_harness_calibration import digest
from calibration_policy_adapter import version_for_engine
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_workflows('
        'issue_id TEXT,author_task TEXT,config TEXT,state TEXT,PRIMARY KEY(issue_id,author_task))')


def instruction(c):
    from calibration_response_contract import context,capsule
    paths=['/evidence/'+root+'/'+path for root in ('candidate','previous') for path in c['test_files']]
    engine=c.get('calibration_engine','unittest_path_fixture_v1');version_for_engine(engine)
    adapter=('Adapter is unittest_path_fixture_v1; fixture_attribute must name the actual uppercase Path variable '
        if engine=='unittest_path_fixture_v1' else
        'Adapter is unittest_path_fixtures_v2; every fixtures.attribute must name an actual uppercase Path variable ')
    modules=('modules=[{path,fixture_attribute,product_path,positive_fixture,classes:{ClassName:[test_method]}}], '
        if engine=='unittest_path_fixture_v1' else
        'modules=[{path,fixtures:[{attribute,product_path,positive_fixture}],classes:{ClassName:[test_method]}}], ')
    negatives=('negatives=[{id,module,class_name,method,fixture,criteria:[A01]}], '
        if engine=='unittest_path_fixture_v1' else
        'negatives=[{id,module,class_name,method,replacements:[{attribute,fixture}],criteria:[A01]}], ')
    note=('CTO CALIBRATION BUNDLE PROPOSAL ONLY. Read the frozen candidate tests and the previous tests '
        'completely, plus each product file referenced by your adapter. Do not edit, run tests, use shell, '
        'approve a delivery, change acceptance or ask the CEO a technical question. '
        'Propose independent positive and negative reference fixture bytes. Preserve all previous test '
        'methods/assertions. The controller will verify actual AST inventories; your declaration is not proof. '
        'Each negative must identify an existing candidate method that should fail by assertion and cover '
        'the unchanged acceptance IDs. Positive references must pass all declared candidate methods. '
        +adapter+
        'used by the immutable test module. Unsupported seams require a technical hold, not fabricated fixtures. '
        'Return one compact JSON object, no prose/fences, with exactly: '
        'action="propose_calibration_bundle", engine="'+engine+'", '+modules+negatives+
        'previous_methods={test_path:{ClassName:[historical_test_method]}}, '
        'controls={relative_fixture_path:literal_UTF8_content}, execution_authorized=false, delivery_approval=false. '
        'No commands, self-authored hashes or approval fields. Controls are at most64KiB each and512KiB total. '
        'If unsupported, return exactly {"action":"calibration_objection","reason":"concrete seam restriction",'
        '"execution_authorized":false,"delivery_approval":false}; this retains an owned hold, not an approval. '
        '\nSource binding: '+digest(c)+'\nAcceptance (unchanged): '+json.dumps(c['criteria'],separators=(',',':'))+
        '\n'+''.join('READ FULL FILE: /evidence/'+root+'/'+path+'\n'
            for root in ('candidate','previous') for path in c['test_files']))
    if engine=='unittest_path_fixtures_v2':
        note+=' All product Path globals used by these tests need positive fixtures; each negative changes only its declared attributes.'
    note=capsule(context('bundle',paths,digest(c),engine=engine if 'calibration_engine' in c else None))+note
    gate.require(len(note)<=4000)
    return note


def advance(con,c,fx,*,now=None):
    initialize(con);now=time.time() if now is None else now
    row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    gate.require(row and json.loads(row[0])==c);s=json.loads(row[1])
    if s['stage'] in ('blocked','calibration_ready'):return s
    if s['stage'] in ('inputs_ready','observe_inputs','register_policy','observe_calibration'):
        try:import generic_calibration_pipeline as pipeline
        except ImportError:from broker import generic_calibration_pipeline as pipeline
        return pipeline.advance(con,c,fx,now=now)
    if s['stage']=='controls_ready' or s['stage'].startswith('policy_'):
        try:import generic_calibration_approvals as approvals
        except ImportError:from broker import generic_calibration_approvals as approvals
        return approvals.advance(con,c,fx,now=now)
    def save(**changes):
        s.update(changes)
        con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),c['issue_id'],c['author_task']));con.commit()
        return s
    def hold(category,action,**facts):
        return save(stage='blocked',category=category,owner=c['cto'],required_action=action,**facts)
    try:fx.verify(c)
    except (ValueError,KeyError,TypeError):
        return hold('bundle_source_binding_rejected','CTO diagnose changed source binding; no dispatch or retry')
    if s['stage']=='prepare_controls':
        try:result=fx.materialize(c)
        except TimeoutError:return s  # Observe the same durable Docker job.
        except (ValueError,KeyError,TypeError):
            return hold('bundle_materialization_rejected','CTO diagnose controller materialization; never reassign author blindly')
        if result is None:return s
        try:
            receipt=result['receipt']
            gate.require(receipt['bundle_sha256']==s['bundle_sha256'] and receipt['policy_sha256']==s['policy_sha256']
                and all(receipt[k] is False for k in ('tests_executed','execution_authorized','delivery_approval')))
        except (ValueError,KeyError,TypeError):
            return hold('bundle_materialization_receipt_rejected',
                'CTO diagnose exact materialization receipt; preserve job and never replay effects')
        return save(stage='controls_ready',materialization=result,
            required_action='CTO attest exact immutable policy, then Tech Lead independently reviews; no test authority')
    if s['stage'] in ('bundle_dispatch','observe_bundle_dispatch'):
        first=s['stage']=='bundle_dispatch'
        if first and not fx.reserve(c):
            return save(required_action='Await proxy reserve before recording any wakeup effect')
        marker=digest(dict(config_sha256=digest(c),phase='bundle',protocol='generic-calibration-producer-v1'))
        if s.get('protocol_recovery_sha256'):
            try:import generic_calibration_protocol_recovery as repair
            except ImportError:from broker import generic_calibration_protocol_recovery as repair
            receipt=repair.qualified(con,c,s)
            marker=digest(dict(config_sha256=digest(c),phase='bundle',protocol=receipt['protocol'],
                recovery_sha256=digest(receipt)))
        try:note=instruction(c)
        except ValueError:
            return hold('bundle_context_requires_readonly_capsule',
                'Controller materialize full context for CTO; never truncate approved criteria')
        if first:save(stage='observe_bundle_dispatch',marker=marker,observation_started=now,
            required_action='Observe exact CTO bundle wakeup; no duplicate dispatch')
        gate.require(s['marker']==marker)
        try:wake=fx.wake(c,note,marker,first)
        except (TimeoutError,urllib.error.URLError):wake=None
        if wake is None:
            if now-s['observation_started']>=600:
                return hold('bundle_dispatch_unobserved','CTO diagnose exact unobserved wakeup; never repeat POST')
            return s
        gate.require(isinstance(wake.get('id'),str) and bool(wake['id']))
        return save(stage='await_bundle',wakeup_id=wake['id'],dispatched_at=s['observation_started'],
            required_action='CTO produce source-bound fixture data; no execution authority')
    gate.require(s['stage']=='await_bundle')
    matches=[t for t in fx.runs(c) if t.get('wakeup_id')==s['wakeup_id']]
    if len(matches)>1:return hold('ambiguous_bundle_runs','CTO diagnose duplicate runs for exact wakeup')
    if not matches or matches[0]['status'] in ('queued','dispatched','running'):
        age=now-s['dispatched_at']
        if age>=1800 or (not matches and age>=600):
            return hold('bundle_progress_deadline','CTO inspect exact native task; no identical restart',
                observed_task=matches[0]['id'] if matches else None)
        return s
    task=matches[0]
    if task.get('agent_id')!=c['cto'] or task['status']!='completed':
        return hold('bundle_task_failed','CTO diagnose exact failed or foreign producer',observed_task=task['id'])
    try:ready=fx.ready(c,task)
    except (ValueError,KeyError,TypeError):
        return hold('bundle_native_binding_rejected','CTO diagnose exact producer binding; no replacement task')
    if not ready:
        if now-s['dispatched_at']>=1800:
            return hold('bundle_lease_close_deadline','CTO diagnose exact unclosed producer lease',observed_task=task['id'])
        return s
    try:record=fx.collect(c,task,s['wakeup_id'])
    except (ValueError,KeyError,TypeError):
        return hold('bundle_submission_rejected','CTO diagnose invalid source-bound bundle; no identical retry',observed_task=task['id'])
    gate.require(record['execution_authorized'] is False and record['delivery_approval'] is False)
    return save(stage='prepare_controls',producer_task=task['id'],bundle_sha256=digest(record),
        policy_sha256=record['policy_sha256'],owner=c['cto'],
        required_action='Controller materialize exact immutable controls, then independent native policy review')


def request(b,issue,author_task,*,engine='unittest_path_fixture_v1'):
    """Freeze the dispatch source after a real completed candidate copy."""
    version_for_engine(engine)
    try:import remediation_runtime_guard as guard,remediation_admission,technical_remediation_plan as plans
    except ImportError:from broker import remediation_runtime_guard as guard,remediation_admission,technical_remediation_plan as plans
    with b.LOCK:
        value=guard.qualified(b,issue)
        gate.require(value and value.get('amendment',{}).get('kind')=='inherited_frozen_suite')
        approved_config,approved=remediation_admission.Effects(b).plan(value['source_task'])
        gate.require(approved['plan_sha256']==value['plan_sha256'])
        with b.db() as con:
            initialize(con)
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            gate.require(route['cto']==approved_config['cto'] and route['techlead']==approved_config['reviewer']
                and route['author']==approved_config['original_author']
                and len({route['cto'],route['techlead'],route['author']})==3)
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (author_task,)).fetchall()
            gate.require(len(rows)==1 and rows[0]['agent_id']==route['author'] and rows[0]['issue_id']==issue
                and rows[0]['status']=='closed' and rows[0]['scope'].split(':')[-2]=='implementation')
            author_binding=dict(rows[0])
            copied=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(author_task+':copy',)).fetchone()
            gate.require(copied is not None);identity,state=map(json.loads,copied)
            gate.require(state.get('stage')=='complete')
            result=state['result'];raw=result['output']
            gate.require(result['approval'] is False and type(result['exit_code']) is int and result['exit_code']==0
                and hashlib.sha256(raw.encode()).hexdigest()==result['output_sha256'])
            prepared=json.loads(raw)
            gate.require(set(prepared['test_sha256'])==set(value['steps'][0]['editable_files']))
            mounts=[m for m in identity['payload']['HostConfig']['Mounts'] if m.get('Target')=='/snapshot']
            gate.require(len(mounts)==1 and identity['payload']['Labels'].get('delivery-kit.test-first-task')==author_task)
            c=dict(issue_id=issue,author_task=author_task,cto=route['cto'],reviewer=route['techlead'],
                candidate_volume=mounts[0]['Source'],previous_volume=value['previous_new_test_delivery']['volume'],
                previous_task=value['previous_new_test_delivery']['task_id'],test_files=sorted(prepared['test_sha256']),
                prepared=prepared,execution_sha256=digest(value),plan_sha256=value['plan_sha256'],
                criteria=value['criteria'],source_task=value['source_task'])
            if engine!='unittest_path_fixture_v1':c['calibration_engine']=engine
        fx=Effects(b);fx.verify(c)
        authored=fx.plans.task(author_task,route['author'])
        gate.require_author_scope(author_binding,authored)
        gate.require(authored.get('status')=='completed' and authored.get('issue_id')==issue)
        with b.db() as con:
            prior=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
                (issue,author_task)).fetchone()
            if prior:gate.require(json.loads(prior[0])==c);return json.loads(prior[1])
            gate.require(guard.qualified(b,issue)==value)
            s=dict(stage='bundle_dispatch',owner=c['cto'],execution_authorized=False,delivery_approval=False)
            con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
                (issue,author_task,json.dumps(c,sort_keys=True),json.dumps(s,sort_keys=True)))
            return s


class Effects:
    def __init__(self,b):
        try:import technical_remediation_plan as plans
        except ImportError:from broker import technical_remediation_plan as plans
        self.b=b;self.plans=plans.Effects(b)
    def verify(self,c):
        try:import remediation_runtime_guard as guard,remediation_admission
        except ImportError:from broker import remediation_runtime_guard as guard,remediation_admission
        engine=c.get('calibration_engine','unittest_path_fixture_v1');version_for_engine(engine)
        if engine=='unittest_path_fixtures_v2':
            import re
            image=getattr(self.b,'GENERIC_CALIBRATION_V2_IMAGE',None)
            gate.require(isinstance(image,str) and bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
        value=guard.qualified(self.b,c['issue_id'])
        gate.require(value and digest(value)==c['execution_sha256'] and value['plan_sha256']==c['plan_sha256'])
        config,approved=remediation_admission.Effects(self.b).plan(value['source_task'])
        gate.require(config['cto']==c['cto'] and config['reviewer']==c['reviewer']
            and approved['plan_sha256']==c['plan_sha256']
            and self.plans.settings['agents'].get(c['cto'])=='planning'
            and self.plans.settings['agents'].get(c['reviewer'])=='planning')
        with self.b.db() as con:
            route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()
        gate.require(route is not None)
        route=json.loads(route[0])
        gate.require(route['cto']==c['cto'] and route['techlead']==c['reviewer'])
        for volume,task in ((c['candidate_volume'],c['author_task']),(c['previous_volume'],c['previous_task'])):
            gate.require(volume.startswith(self.b.PREFIX+'-'))
            tags=(self.b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
            gate.require(tags.get('delivery-kit.owner')==self.b.OWNER and tags.get('delivery-kit.test-first-task')==task)
    def runs(self,c):
        try:import native
        except ImportError:from broker import native
        return native.issue_task_runs(self.plans.settings,c['issue_id'])
    def reserve(self,c):return self.plans.native.remaining_calls()>=32
    def ready(self,c,task):
        with self.b.db() as con:
            rows=con.execute('SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (task['id'],)).fetchall()
        gate.require(len(rows)==1)
        return rows[0][0]=='closed'
    def wake(self,c,note,marker,allow_create):
        try:import native
        except ImportError:from broker import native
        return native.ensure_planning_start(self.plans.settings,c['issue_id'],c['cto'],c['author_task'],marker,note,
            allow_create=allow_create)
    def collect(self,c,task,wakeup):
        try:import generic_calibration_proposal as producer
        except ImportError:from broker import generic_calibration_proposal as producer
        return producer.collect(self.b,c['issue_id'],c['author_task'],task['id'],wakeup,
            expected_engine=c.get('calibration_engine','unittest_path_fixture_v1'))
    def materialize(self,c):
        try:import generic_calibration_materialization as jobs
        except ImportError:from broker import generic_calibration_materialization as jobs
        with self.b.db() as con:return jobs.run(self.b,con,c['issue_id'],c['author_task'])
    def approval_source(self,c,s):
        try:import generic_calibration_materialization as jobs,remediation_runtime_guard as guard
        except ImportError:from broker import generic_calibration_materialization as jobs,remediation_runtime_guard as guard
        self.verify(c)
        with self.b.db() as con:
            producer=con.execute('SELECT record FROM generic_calibration_proposals WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone()
            row=con.execute('SELECT identity,state FROM generic_calibration_materializations WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone()
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()[0])
        gate.require(producer and row)
        record=json.loads(producer[0]);identity,state=map(json.loads,row);p=record['policy']
        gate.require(digest(record)==s['bundle_sha256'] and record['policy_sha256']==s['policy_sha256']
            and record['producer']['task_id']==s['producer_task']
            and state.get('stage')=='complete' and state['result']==s['materialization']
            and identity==jobs.identity(self.b,record))
        jobs.validate_receipt(state['result']['receipt'],record)
        value=guard.qualified(self.b,c['issue_id'])
        gate.require(value and digest(value)==c['execution_sha256']
            and p['source_task']==c['source_task'] and p['execution_sha256']==c['execution_sha256']
            and p['plan_sha256']==c['plan_sha256'] and p['criteria']==sorted(c['criteria'])
            and p['engine']==c.get('calibration_engine','unittest_path_fixture_v1')
            and p['candidate_manifest_sha256']==c['prepared']['manifest_sha256']
            and p['test_sha256']==c['prepared']['test_sha256']
            and route['cto']==c['cto'] and route['techlead']==c['reviewer']
            and len({route['author'],c['cto'],c['reviewer']})==3)
        for role,expected in identity['volumes'].items():
            actual=self.b.docker('GET','/volumes/'+expected['Name']) or {}
            gate.require(actual.get('Name')==expected['Name'] and actual.get('Labels')==expected['Labels']
                and state['result'][role+'_volume']==expected['Name'])
        context=dict(issue_id=c['issue_id'],author_task=c['author_task'],author=route['author'],cto=c['cto'],
            reviewer=c['reviewer'],previous_methods=p['previous_methods'],execution_sha256=c['execution_sha256'],
            plan_sha256=c['plan_sha256'],source_task=c['source_task'],criteria=p['criteria'],
            control_files=sorted(record['controls']),candidate_volume=c['candidate_volume'],
            controls_volume=state['result']['controls_volume'],policy_volume=state['result']['policy_volume'])
        gate.validate_volumes(self.b,dict(policy_sha256=digest(p),context=context))
        return dict(policy=p,context=context,previous=value['previous_new_test_delivery'])
    def wake_policy(self,c,actor,note,marker,allow_create):
        try:import native
        except ImportError:from broker import native
        gate.require(actor in (c['cto'],c['reviewer']))
        return native.ensure_planning_start(self.plans.settings,c['issue_id'],actor,c['author_task'],marker,note,
            allow_create=allow_create)
    def policy_task(self,c,tid,actor):
        gate.require(actor in (c['cto'],c['reviewer']) and tid!=c['author_task'])
        with self.b.db() as con:
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (tid,)).fetchall()
        gate.require(len(rows)==1 and rows[0]['status']=='closed' and rows[0]['issue_id']==c['issue_id']
            and rows[0]['agent_id']==actor and rows[0]['scope'].split(':')[-2:]==['planning',tid])
        return self.plans.task(tid,actor)
    def policy_reads(self,task):return self.plans.reads(task)
    def persist_intake(self,c,s,intake):
        try:import generic_calibration_registration as registration
        except ImportError:from broker import generic_calibration_registration as registration
        source=self.approval_source(c,s)
        gate.require(intake['policy']==source['policy'] and intake['previous']==source['previous']
            and intake['context']=={**source['context'],'proposal_wakeup':s['attestation_wakeup'],
                'review_wakeup':s['policy_wakeup']}
            and intake['proposal_task']==s['attestation_task']
            and intake['review_task'] not in (c['author_task'],s['producer_task'],s['attestation_task'])
            and intake['probe_job_key']==c['author_task']+':calibration-inputs:'+digest(source['policy']))
        proposal=self.policy_task(c,intake['proposal_task'],c['cto'])
        review=self.policy_task(c,intake['review_task'],c['reviewer'])
        gate.qualify(intake['policy'],intake['context'],proposal,review,self.policy_reads(proposal),self.policy_reads(review))
        with self.b.db() as con:
            registration.initialize(con)
            current=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone()
            gate.require(current and json.loads(current[0])==c and json.loads(current[1])==s)
            old=con.execute('SELECT config FROM generic_calibration_intakes WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone()
            if old:gate.require(json.loads(old[0])==intake)
            else:con.execute('INSERT INTO generic_calibration_intakes VALUES(?,?,?)',
                (c['issue_id'],c['author_task'],json.dumps(intake,sort_keys=True)))
        return intake
    def pipeline_intake(self,c,s):
        source=self.approval_source(c,s)
        with self.b.db() as con:
            row=con.execute('SELECT config FROM generic_calibration_intakes WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone()
        gate.require(row is not None);intake=json.loads(row[0])
        gate.require(digest(intake)==s['intake_sha256'] and intake['policy']==source['policy']
            and intake['previous']==source['previous']
            and intake['context']=={**source['context'],'proposal_wakeup':s['attestation_wakeup'],
                'review_wakeup':s['policy_wakeup']}
            and intake['proposal_task']==s['attestation_task'] and intake['review_task']==s['review_task'])
        return intake
    def input_probe(self,c,s,intake):
        try:import generic_calibration_registration as registration,remediation_runtime_guard as guard
        except ImportError:from broker import generic_calibration_registration as registration,remediation_runtime_guard as guard
        value=guard.qualified(self.b,c['issue_id'])
        gate.require(value and digest(value)==c['execution_sha256'])
        with self.b.db() as con:
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()[0])
            return registration.run_inputs(self.b,con,intake,value,route)
    def register_policy(self,c,s,intake):
        try:import generic_calibration_registration as registration
        except ImportError:from broker import generic_calibration_registration as registration
        # register independently re-fetches native tasks, exact closed leases,
        # original copy, input job and immutable intake; never model declarations.
        with self.b.db() as con:
            row=con.execute('SELECT state FROM generic_calibration_input_jobs WHERE job_key=?',
                (intake['probe_job_key'],)).fetchone()
        gate.require(row is not None);state=json.loads(row[0])
        gate.require(state.get('stage')=='complete' and digest(state['result'])==s['input_result_sha256'])
        return registration.register(self.b,c['issue_id'],c['author_task'])
    def calibrate(self,c,s,record):
        with self.b.db() as con:return gate.run(self.b,con,record)
    def registered_policy(self,c,s,intake):
        with self.b.db() as con:
            row=con.execute('SELECT record FROM generic_calibration_policies WHERE issue_id=? AND author_task=?',
                (c['issue_id'],c['author_task'])).fetchone()
        gate.require(row is not None);record=json.loads(row[0])
        gate.require(digest(record)==s['registration_sha256'])
        # Re-fetch actual approval/lease facts. register's immutable store reads
        # the existing identical row; it cannot create a new revision here.
        gate.require(self.register_policy(c,s,intake)==record)
        return record


def tick(b):
    with b.LOCK,b.db() as con:
        initialize(con)
        rows=con.execute('SELECT config,state FROM generic_calibration_workflows').fetchall()
        active=[json.loads(r[0]) for r in rows if json.loads(r[1])['stage'] not in ('blocked','calibration_ready')]
        if not active:return
        fx=Effects(b)
        for c in active:advance(con,c,fx)


def bound_prompt(c,s,task,note,expected_note):
    """A capsule is format context, never permission to impersonate a phase."""
    from calibration_response_contract import request
    phases={'await_bundle':('bundle',c['cto'],'wakeup_id'),
        'policy_attestation_wait':('attestation',c['cto'],'attestation_wakeup'),
        'policy_review_wait':('review',c['reviewer'],'policy_wakeup')}
    gate.require(s['stage'] in phases)
    phase,actor,wake=phases[s['stage']]
    gate.require(task.get('agent_id')==actor and task.get('issue_id')==c['issue_id']
        and bool(s.get(wake)) and task.get('wakeup_id')==s[wake])
    value=request(dict(messages=[dict(role='user',content=note)]))
    expected=request(dict(messages=[dict(role='user',content=expected_note)]))
    gate.require(value is not None and value==expected and value['phase']==phase)
    return value


def prompt_contract(b,issue,task,note):
    from calibration_response_contract import request
    value=request(dict(messages=[dict(role='user',content=note)]))
    if value is None:return None
    with b.db() as con:
        initialize(con)
        rows=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=?',(issue,)).fetchall()
    phases={'await_bundle','policy_attestation_wait','policy_review_wait'}
    matches=[(json.loads(r[0]),json.loads(r[1])) for r in rows if json.loads(r[1])['stage'] in phases]
    gate.require(len(matches)==1);c,s=matches[0]
    fx=Effects(b);fx.verify(c)
    if s['stage']=='await_bundle':expected=instruction(c)
    else:
        try:import generic_calibration_approvals as approvals
        except ImportError:from broker import generic_calibration_approvals as approvals
        expected=approvals.instruction(fx.approval_source(c,s),'attestation' if s['stage']=='policy_attestation_wait' else 'review')
    return bound_prompt(c,s,task,note,expected)


def mounts(b,binding):
    with b.db() as con:
        initialize(con)
        rows=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=?',(binding['issue_id'],)).fetchall()
        def expected_actor(c,s):
            if s['stage']=='await_bundle' or s['stage']=='policy_attestation_wait':return c['cto']
            if s['stage']=='policy_review_wait':return c['reviewer']
            return None
        matches=[(json.loads(r[0]),json.loads(r[1])) for r in rows
            if expected_actor(json.loads(r[0]),json.loads(r[1]))==binding['agent_id']]
        if not matches:return []
        gate.require(len(matches)==1);c,s=matches[0]
        current=con.execute("SELECT n.* FROM native_bindings n JOIN leases l USING(request_id) "
            "WHERE n.issue_id=? AND n.agent_id=? AND l.status IN ('creating','starting','running')",
            (binding['issue_id'],binding['agent_id'])).fetchall()
        gate.require(len(current)==1)
        gate.require(current[0]['scope'].split(':')[-2:]==['planning',current[0]['task_id']])
    fx=Effects(b);fx.verify(c)
    task=fx.plans.task(current[0]['task_id'],expected_actor(c,s))
    wakeup=s['wakeup_id'] if s['stage']=='await_bundle' else s['policy_wakeup']
    gate.require(task.get('wakeup_id')==wakeup and task.get('issue_id')==c['issue_id'])
    volumes=[(c['candidate_volume'],'/evidence/candidate'),(c['previous_volume'],'/evidence/previous')]
    if s['stage']!='await_bundle':
        source=fx.approval_source(c,s)
        volumes.extend((source['context'][role+'_volume'],'/evidence/'+role) for role in ('controls','policy'))
    gate.require(len({v for v,t in volumes})==len(volumes))
    return [dict(Type='volume',Source=volume,Target=target,ReadOnly=True) for volume,target in volumes]
