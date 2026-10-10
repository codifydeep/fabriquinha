"""Durable native CTO bundle dispatch; proposals never authorize delivery.

The current terminal prerequisite is prepare_controls, owned by the technical
controller. It is not success: materialization, attestation, independent review,
input probe and calibration must subsequently consume the exact same bundle.
"""
import hashlib
import json
import time
import urllib.error

from generic_harness_calibration import digest
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_workflows('
        'issue_id TEXT,author_task TEXT,config TEXT,state TEXT,PRIMARY KEY(issue_id,author_task))')


def instruction(c):
    note=('CTO CALIBRATION BUNDLE PROPOSAL ONLY. Read the frozen candidate tests and the previous tests '
        'completely, plus each product file referenced by your adapter. Do not edit, run tests, use shell, '
        'approve a delivery, change acceptance or ask the CEO a technical question. '
        'Propose independent positive and negative reference fixture bytes. Preserve all previous test '
        'methods/assertions. The controller will verify actual AST inventories; your declaration is not proof. '
        'Each negative must identify an existing candidate method that should fail by assertion and cover '
        'the unchanged acceptance IDs. Positive references must pass all declared candidate methods. '
        'Adapter is unittest_path_fixture_v1; fixture_attribute must name the actual uppercase Path variable '
        'used by the immutable test module. Unsupported seams require a technical hold, not fabricated fixtures. '
        'Return one compact JSON object, no prose/fences, with exactly: '
        'action="propose_calibration_bundle", engine="unittest_path_fixture_v1", '
        'modules=[{path,fixture_attribute,product_path,positive_fixture,classes:{ClassName:[test_method]}}], '
        'negatives=[{id,module,class_name,method,fixture,criteria:[A01]}], '
        'previous_methods={test_path:{ClassName:[historical_test_method]}}, '
        'controls={relative_fixture_path:literal_UTF8_content}, execution_authorized=false, delivery_approval=false. '
        'No commands, self-authored hashes or approval fields. Controls are at most64KiB each and512KiB total. '
        'If unsupported, explain the concrete seam restriction; the controller will retain an owned hold, '
        'not interpret that prose as a submitted bundle. '
        '\nSource binding: '+digest(c)+'\nAcceptance (unchanged): '+json.dumps(c['criteria'],separators=(',',':'))+
        '\n'+''.join('READ FULL FILE: /evidence/'+root+'/'+path+'\n'
            for root in ('candidate','previous') for path in c['test_files']))
    gate.require(len(note)<=4000)
    return note


def advance(con,c,fx,*,now=None):
    initialize(con);now=time.time() if now is None else now
    row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    gate.require(row and json.loads(row[0])==c);s=json.loads(row[1])
    if s['stage'] in ('blocked','prepare_controls'):return s
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
    if s['stage'] in ('bundle_dispatch','observe_bundle_dispatch'):
        first=s['stage']=='bundle_dispatch'
        if first and not fx.reserve(c):
            return save(required_action='Await proxy reserve before recording any wakeup effect')
        marker=digest(dict(config_sha256=digest(c),phase='bundle',protocol='generic-calibration-producer-v1'))
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


def request(b,issue,author_task):
    """Freeze the dispatch source after a real completed candidate copy."""
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
                and rows[0]['status']=='closed' and rows[0]['scope'].split(':')[-2:]==['implementation',author_task])
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
        fx=Effects(b);fx.verify(c)
        authored=fx.plans.task(author_task,route['author'])
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
        return producer.collect(self.b,c['issue_id'],c['author_task'],task['id'],wakeup)


def tick(b):
    with b.LOCK,b.db() as con:
        initialize(con)
        rows=con.execute('SELECT config,state FROM generic_calibration_workflows').fetchall()
        active=[json.loads(r[0]) for r in rows if json.loads(r[1])['stage'] not in ('blocked','prepare_controls')]
        if not active:return
        fx=Effects(b)
        for c in active:advance(con,c,fx)


def mounts(b,binding):
    with b.db() as con:
        initialize(con)
        rows=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=?',(binding['issue_id'],)).fetchall()
        matches=[(json.loads(r[0]),json.loads(r[1])) for r in rows if json.loads(r[1])['stage']=='await_bundle'
            and json.loads(r[0])['cto']==binding['agent_id']]
        if not matches:return []
        gate.require(len(matches)==1);c,s=matches[0]
        current=con.execute("SELECT n.* FROM native_bindings n JOIN leases l USING(request_id) "
            "WHERE n.issue_id=? AND n.agent_id=? AND l.status IN ('creating','starting','running')",
            (binding['issue_id'],binding['agent_id'])).fetchall()
        gate.require(len(current)==1)
        gate.require(current[0]['scope'].split(':')[-2:]==['planning',current[0]['task_id']])
    fx=Effects(b);fx.verify(c)
    task=fx.plans.task(current[0]['task_id'],c['cto'])
    gate.require(task.get('wakeup_id')==s['wakeup_id'] and task.get('issue_id')==c['issue_id'])
    return [dict(Type='volume',Source=c[key],Target=target,ReadOnly=True) for key,target in (
        ('candidate_volume','/evidence/candidate'),('previous_volume','/evidence/previous'))]
