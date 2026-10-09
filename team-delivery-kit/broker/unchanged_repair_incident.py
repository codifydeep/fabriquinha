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
                or not 1<=len(decision['reason'])<=3000):
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
        note=('DELIVERY_PRE_RED_UNCHANGED_INCIDENT_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
            'DIAGNOSIS ONLY. A completed tests-only correction submitted the same NEW-test hash as its seed. '
            'The full suite ran, but this is not a fresh qualified Red. Evidence: '+json.dumps(identity,sort_keys=True)+
            '. Legacy formatted patch completions do NOT prove lasting edits; the historical cause is UNKNOWN. '
            'Do not infer reversion, failed persistence or test correctness. Propose one bounded local experiment '
            'to distinguish those hypotheses, or identify missing evidence. No file/shell/admin tools, no author '
            'retry, test weakening, budget/depth reset or CEO technical question. Original acceptance and independent '
            'review remain binding. Return JSON only with action=request_correction or escalate_cto, reason<=3000 '
            'and optional_files=[]. Either action is only a recommendation; the controller grants no execution.')
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
        advance(identity,state,Effects(b,route,fx),save)
    return True
