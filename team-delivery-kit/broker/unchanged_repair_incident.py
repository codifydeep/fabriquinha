"""Bounded diagnosis of a completed repair that resubmitted its exact seed.

No author wakeup or permission is created here. Native uncertainty is observed
against the original marker, never resolved by repeating a remote POST.
"""
import hashlib
import json
import re
import time
import urllib.error
try:
    import handoffs, native
except ImportError:
    from broker import handoffs, native


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def instruction(identity):
    return ('DELIVERY_PRE_RED_UNCHANGED_INCIDENT_V2\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_EXECUTION_DIAGNOSIS_V1\nDELIVERY_TYPED_DECISION_V1\n'
        'DIAGNOSIS ONLY. The completed tests-only correction has the SAME NEW-test hash as its seed. '
        'This is not qualified fresh Red. Controller evidence: '+json.dumps(identity,sort_keys=True)+
        '. Historical cause UNKNOWN; legacy patch summaries do not prove lasting edits. '
        'Recommend ONE bounded experiment to distinguish no-op, persistence and later overwrite, '
        'or identify missing evidence. Do not assert an unobserved cause. No file/shell/admin tools, '
        'author retry, test weakening, budget/depth reset or CEO technical question. '
        'Submit escalate_cto, optional_files=[], reason target <=700 characters, HARD LIMIT 1200. '
        'Use the required typed submission, not prose. This recommendation grants NO execution or approval.')


def qualify_transport_recovery(identity,state,task,event):
    """Exactly one changed-contract CTO diagnosis; never an author retry."""
    diagnostic=event.get('structured_rejection_diagnostic',{})
    if (state.get('stage')!='technical_hold' or state.get('category')!='diagnosis_execution_failed'
            or task.get('id')!=state.get('task_id') or task.get('wakeup_id')!=state.get('wakeup_id')
            or task.get('agent_id')!=identity['owner'] or task.get('issue_id')!=identity['issue_id']
            or task.get('status')!='failed' or task.get('failure_reason')!='agent_error.provider_server_error'
            or event.get('status')!=502 or event.get('category')!='structured_decision_response_invalid'
            or event.get('structured_rejection_category')!='schema_violation'
            or diagnostic.get('version')!='structured-constraint-v1'
            or diagnostic.get('constraints')!=['maxLength']
            or not re.fullmatch(r'[a-f0-9]{64}',str(diagnostic.get('upstream_sha256')))
            or event.get('decision_schema')!='delivery_decision_v1'):
        raise ValueError('exact failed length-constrained CTO diagnosis required')
    return dict(operation='unchanged_diagnosis_typed_transport_v2',failed_task=task['id'],
        failed_wakeup=state['wakeup_id'],rejection=diagnostic,attempt_limit=1,
        instruction_sha256=hashlib.sha256(instruction(identity).encode()).hexdigest(),
        author_retry_authorized=False,delivery_approval=False)


def register_transport_recovery(b,source):
    """Controller registration binds actual failure and installed proxy projection."""
    from pathlib import Path
    with b.LOCK:
        with b.db() as c:
            row=c.execute('SELECT identity,state FROM unchanged_repair_incidents WHERE source_task=?',(source,)).fetchone()
            identity,state=map(json.loads,row)
            if state.get('transport_recovery'):return state
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('settled leases required')
            bindings=c.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(state['task_id'],)).fetchall()
            if len(bindings)!=1 or bindings[0][1]!='closed':raise ValueError('one closed diagnosis binding required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,state['task_id'],identity['owner'])
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        labels=proxy['Config'].get('Labels',{})
        if (not proxy['State']['Running'] or labels.get('com.docker.compose.project')!=b.PREFIX
                or labels.get('com.docker.compose.service')!='model-proxy'):raise ValueError('owned live proxy required')
        events=[]
        for line in b.docker_stdout(proxy['Id'],limit=2*1024*1024).splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            if e.get('execution_id')==bindings[0][0] and e.get('status')==502:events.append(e)
        if len(events)!=1:raise ValueError('one correlated rejection required')
        proof=qualify_transport_recovery(identity,state,task,events[0])
        script='''import json,sys,hashlib,decision_schema,typed_decision_contract
body={'messages':[{'role':'user','content':sys.argv[1]}],'tools':[{'type':'function','function':{'name':'terminal'}}]}
wire=typed_decision_contract.apply(decision_schema.apply(body))
schema=wire['tools'][0]['function']['parameters']
assert len(wire['tools'])==1 and wire['tool_choice']=={'type':'function','function':{'name':'submit_delivery_decision'}}
assert schema['properties']['action']['enum']==['escalate_cto']
assert schema['properties']['reason']['maxLength']==1200 and schema['properties']['optional_files']['maxItems']==0
print(json.dumps({'schema_sha256':hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),'no_worker_tools':True,'reason_maximum':1200}))
'''
        entry=b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,AttachStderr=False,Tty=True,
            Env=['PYTHONPATH=/'],Cmd=['python','-c',script,instruction(identity)]))
        conn=b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('POST','/v1.45/exec/'+entry['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),{'Content-Type':'application/json'})
            response=conn.getresponse();raw=response.read(4097)
            if response.status!=200 or len(raw)>4096:raise ValueError('bounded installed qualification required')
        finally:conn.close()
        result=b.docker('GET','/exec/'+entry['Id']+'/json')
        if result.get('Running') or result.get('ExitCode')!=0:raise ValueError('installed transport qualification failed')
        proof.update(installed_projection=json.loads(raw),proxy_image=proxy['Image'],
                     module_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        updated={**state,'transport_recovery':dict(proof=proof,state={})}
        with b.db() as c:
            if json.loads(c.execute('SELECT state FROM unchanged_repair_incidents WHERE source_task=?',(source,)).fetchone()[0])!=state:
                raise ValueError('diagnosis state drift')
            c.execute('UPDATE unchanged_repair_incidents SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return updated


def describe(task,route,incident,policy):
    hashes=incident.get('test_sha256',{})
    if (task.get('status')!='completed' or task.get('agent_id')!=route.get('author')
            or task.get('issue_id')!=route.get('issue_id')
            or route.get('cto') in (None,route.get('author'))
            or route.get('test_first') is not True or route.get('enabled') is not True
            or policy.get('seed_previous_tests') is not True
            or incident.get('kind')!='rejected_red'
            or incident.get('reason')!='sponsored repair requires changed NEW-test snapshot'
            or incident.get('issue_id')!=route['issue_id'] or incident.get('task_id')!=task['id']
            or incident.get('exit_code')!=1 or not hashes
            or set(hashes)!=set(route.get('test_first_files',[]))
            or hashes!=policy.get('old_red',{}).get('red',{}).get('test_sha256')
            or any(not re.fullmatch(r'[a-f0-9]{64}',str(v)) for v in
                   [*hashes.values(),incident.get('manifest_sha256'),incident.get('output_sha256')])):
        raise ValueError('exact completed unchanged seeded repair required')
    return dict(operation='unchanged_completed_repair_incident_v1',source_task=task['id'],
        issue_id=route['issue_id'],owner=route['cto'],test_sha256=hashes,
        manifest_sha256=incident['manifest_sha256'],output_sha256=incident['output_sha256'],
        minimum_calls=route.get('minimum_calls',8),cause='unknown',
        author_retry_authorized=False,red_verified=False,delivery_approval=False)


def advance(identity,state,fx,save,*,now=None):
    now=time.time() if now is None else now
    state=dict(state)
    if state.get('stage') in ('diagnosed_hold','technical_hold'):return state
    if not state:
        if not fx.available() or fx.remaining()<identity['minimum_calls']:return state
        state=dict(stage='post_intent',started_at=now,author_retry_authorized=False,delivery_approval=False)
        save(state)  # Intent must precede the only permitted create attempt.
        create=True
    else:create=False
    if state['stage']=='post_intent':
        try:wake=fx.wake(identity,allow_create=create)
        except (TimeoutError,ConnectionError,urllib.error.URLError):return state
        except ValueError:
            state.update(stage='technical_hold',category='diagnosis_wakeup_identity_rejected',
                         required_action='diagnose exact persisted marker; no repeated POST');save(state)
            return state
        if wake is None:
            if now-state['started_at']>=600:
                state.update(stage='technical_hold',category='wakeup_unobserved',
                             required_action='observe exact native marker; no repeated POST')
                save(state)
            return state
        state.update(stage='awaiting_diagnosis',wakeup_id=wake['id']);save(state)
        return state
    runs=[r for r in fx.runs() if r.get('wakeup_id')==state['wakeup_id']
          and r.get('agent_id')==identity['owner']]
    if len(runs)>1:raise ValueError('ambiguous unchanged-repair diagnosis')
    if not runs:
        if now-state['started_at']>=1800:
            state.update(stage='technical_hold',category='diagnosis_not_started',
                         required_action='diagnose exact wakeup; no author restart');save(state)
        return state
    task=runs[0]
    if task['status'] in ('queued','dispatched','running'):return state
    if task['status']!='completed':
        state.update(stage='technical_hold',category='diagnosis_execution_failed',task_id=task['id'])
    else:
        try:decision=fx.decision(task)
        except (ValueError,TypeError,KeyError):
            state.update(stage='technical_hold',category='diagnosis_decision_invalid',task_id=task['id'],
                         required_action='inspect preserved diagnosis; no author restart');save(state)
            return state
        if (set(decision)!={'action','reason','optional_files'}
                or decision['action'] not in ('request_correction','escalate_cto')
                or decision['optional_files']!=[] or not isinstance(decision['reason'],str)
                or not 1<=len(decision['reason'])<=1200):
            state.update(stage='technical_hold',category='diagnosis_recommendation_rejected',task_id=task['id'],
                         required_action='inspect preserved diagnosis; no author restart');save(state)
            return state
        state.update(stage='diagnosed_hold',task_id=task['id'],recommendation=decision)
    state.update(required_action='qualify a changed-condition experiment against original plan before any author dispatch',
                 author_retry_authorized=False,delivery_approval=False);save(state)
    return state


class Effects:
    def __init__(self,b,route,fx):self.b,self.route,self.fx=b,route,fx
    def available(self):
        with self.b.db() as c:
            return not c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    def remaining(self):return self.fx.remaining_calls()
    def wake(self,identity,*,allow_create):
        note=instruction(identity)
        return self.fx.ensure_wakeup(identity['issue_id'],identity['owner'],identity['source_task'],
            digest(identity),note,allow_create=allow_create)
    def runs(self):return native.issue_task_runs(self.fx.settings,self.route['issue_id'])
    def decision(self,task):return self.fx.decision(task)


def handle(b,route,runs,source,prior,fx):
    if (not prior or prior['stage']!='test_first_blocked' or source.get('status')!='completed'
            or route.get('test_first') is not True or route.get('enabled') is not True):return False
    data=json.loads(prior['data']);task=source['id'];issue=route['issue_id']
    if (data.get('error')!='test_first_correction_failed_after_cto_diagnosis'
            or data.get('blocked_cause')!='ValueError:sponsored repair requires changed NEW-test snapshot'
            or data.get('diagnostic',{}).get('kind')!='rejected_red'
            or data.get('diagnostic',{}).get('reason')!='sponsored repair requires changed NEW-test snapshot'):
        return False
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS unchanged_repair_incidents(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
            old=c.execute('SELECT identity,state FROM unchanged_repair_incidents WHERE source_task=?',(task,)).fetchone()
            if old:identity,state=map(json.loads,old)
            else:
                path=b.STATE/'test-first-incidents'/(task+'.json')
                if not path.is_file() or path.is_symlink():return False
                incident=json.loads(path.read_text())
                if incident.get('reason')!='sponsored repair requires changed NEW-test snapshot':return False
                authors=[r for r in runs if r.get('agent_id')==route['author']]
                if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=task
                        or any(r.get('status') in ('queued','dispatched','running') for r in runs)):return False
                policy=c.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
                if not policy:return False
                identity=describe(source,route,incident,json.loads(policy[0]))
                binding=c.execute('SELECT n.issue_id,n.agent_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(task,)).fetchall()
                if len(binding)!=1 or tuple(binding[0])!=(issue,route['author'],'closed'):return False
                for phase in ('copy','red'):
                    job=c.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(task+':'+phase,)).fetchone()
                    if not job:return False
                    bound,result=map(json.loads,job);result=result.get('result',{}) if result.get('stage')=='complete' else {}
                    if (not result or bound['name']!=b.PREFIX+'-test-first-'+phase+'-v2-'+task
                            or bound['payload']['Labels'].get('delivery-kit.owner')!=b.OWNER
                            or bound['payload']['Labels'].get('delivery-kit.test-first-task')!=task):return False
                    if phase=='red':
                        if result.get('exit_code')!=1 or result.get('output_sha256')!=incident['output_sha256']:return False
                    else:
                        copied=json.loads(result['output'])
                        if (result['exit_code']!=0 or copied.get('test_sha256')!=identity['test_sha256']
                                or copied.get('manifest_sha256')!=identity['manifest_sha256']):return False
                if c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone():return False
                identity.update(route_sha256=digest(route),previous_handoff_sha256=digest(data))
                state={}
                c.execute('INSERT INTO unchanged_repair_incidents VALUES(?,?,?)',(task,json.dumps(identity,sort_keys=True),'{}'))
        if identity['issue_id']!=issue or identity['route_sha256']!=digest(route):
            raise ValueError('immutable unchanged-repair incident drift')
        def save(state):
            with b.db() as c:
                current=handoffs.load(c,task)
                if not current or current['stage']!='test_first_blocked':raise ValueError('unchanged incident handoff drift')
                data=json.loads(current['data']);data['unchanged_repair_incident']=dict(identity=identity,state=state)
                data['required_action']=state.get('required_action','CTO diagnose unchanged repair; no author retry')
                c.execute('UPDATE unchanged_repair_incidents SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),task))
                handoffs.save(c,task,issue,'test_first_blocked',route['cto'],data,time.time())
        recovery=state.get('transport_recovery')
        if recovery:
            recovered={**identity, 'transport_recovery_sha256':digest(recovery['proof'])}
            def save_recovery(next_state):
                save({**state,'transport_recovery':{**recovery,'state':next_state}})
            advance(recovered,recovery['state'],Effects(b,route,fx),save_recovery)
        else:advance(identity,state,Effects(b,route,fx),save)
    return True
