"""Once-only observed readonly planning review, never a recovered verdict.

The legacy timeout has unknown cause. A fixed offline initialization experiment
and installed phase diagnostics qualify ONE new observation, not repeated retries.
"""
import copy
import hashlib
import json
from pathlib import Path
import uuid
try:
    import technical_remediation_plan as plans, test_first_job
except ImportError:
    from broker import technical_remediation_plan as plans, test_first_job


def prepare(config,state,task,reads,failure,probe):
    if (state.get('stage')!='blocked' or state.get('category')!='ValueError'
            or state.get('planning_review_observation') or state.get('review_task') or state.get('review')
            or state.get('execution_authorized') is not False
            or state.get('plan_sha256')!=plans.digest(state.get('plan'))
            or task.get('status')!='failed' or task.get('agent_id')!=config['reviewer']
            or task.get('issue_id')!=state.get('issue_id') or task.get('wakeup_id')!=state.get('wakeup_id')
            or reads or failure.get('category')!='prompt_timeout' or failure.get('event_count')!=0
            or failure.get('lease_status') not in ('expired','closed')
            or probe.get('schema')!='real-acp-initialize-probe-v1' or probe.get('status')!='passed'
            or probe.get('actual_hermes_initialize') is not True or probe.get('prompts_sent')!=0
            or probe.get('sessions_created')!=0 or probe.get('network')!='none'
            or probe.get('socket_absent') is not True or probe.get('delivery_approval') is not False):
        raise ValueError('exact unused preread planning timeout and fixed offline probe required')
    proof=dict(operation='planning_review_transport_observation_v1',previous=copy.deepcopy(state),
        failed_task=task['id'],failed_wakeup=task['wakeup_id'],failure=copy.deepcopy(failure),
        probe=copy.deepcopy(probe),cause='unknown',attempt_limit=1,
        execution_authorized=False,delivery_approval=False)
    updated={**state,'stage':'review_dispatch','owner':config['reviewer'],
        'planning_review_observation':proof,
        'review_protocol':'phase-observed-review-'+plans.digest(proof),
        'required_action':'One fresh readonly independent review; complete reads and exact plan verdict required'}
    for field in ('wakeup_id','dispatched_at','category'):updated.pop(field,None)
    return updated


def reconcile(b,source):
    with b.LOCK:
        with b.db() as con:
            config,state=map(json.loads,con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone())
            if state.get('planning_review_observation'):return state
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return None
        fx=plans.Effects(b);runs=plans.native.issue_task_runs(fx.settings,state['issue_id'])
        matches=[r for r in runs if r.get('wakeup_id')==state['wakeup_id']]
        if len(matches)!=1 or any(r['status'] in ('queued','dispatched','running') for r in runs):
            raise ValueError('one exact terminal review wakeup required')
        task=fx.task(matches[0]['id'],config['reviewer']);reads=fx.reads(task)
        original=fx.task(state['plan_task'],config['cto'])
        pending={**state,'stage':'awaiting_plan','wakeup_id':state['plan_wakeup']}
        if (fx.result(original)!=state['plan'] or not plans.validate_result(config,pending,original,state['plan'],fx.reads(original))):
            raise ValueError('exact qualified original CTO proposal required')
        with b.db() as con:
            bindings=con.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                (task['id'],config['reviewer'],state['issue_id'])).fetchall()
            if len(bindings)!=1:raise ValueError('one failed review execution required')
            request=bindings[0]['request_id']
            errors=con.execute('SELECT category FROM broker_errors WHERE request_id=? AND operation=?',(request,'/v1/acp-message')).fetchall()
            if len(errors)!=1:raise ValueError('one durable transport failure required')
            failure=dict(request_id=request,category=errors[0][0],lease_status=bindings[0]['status'],
                event_count=con.execute('SELECT count(*) FROM acp_events WHERE request_id=?',(request,)).fetchone()[0])
        program=Path('/acp_initialize_probe.py')
        # No agent command, credentials, socket, product volume or network.
        payload=dict(Image=b.IMAGE,User='10000:10000',Entrypoint=['python'],Cmd=['-c',program.read_text()],WorkingDir='/tmp',
            Env=['PYTHONDONTWRITEBYTECODE=1'],Labels={'delivery-kit.purpose':'planning-review-initialize-observation'},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
                Tmpfs={'/tmp':'rw,size=64m,mode=1777','/opt/data':'rw,size=16m,mode=0700,uid=10000,gid=10000'}))
        # Qualification before a Docker effect; fixture cannot legitimize an
        # unrelated, partially read or already approved failure.
        expected=dict(schema='real-acp-initialize-probe-v1',status='passed',actual_hermes_initialize=True,
            prompts_sent=0,sessions_created=0,network='none',socket_absent=True,delivery_approval=False)
        prepare(config,state,task,reads,failure,expected)
        corrected=copy.deepcopy(payload)
        corrected['Cmd']=['-c',"import sys,importlib.util;assert importlib.util.find_spec('acp_transport') is None;sys.path.insert(0,'/');assert importlib.util.find_spec('acp_transport') is not None;\n"+program.read_text()]
        with b.db() as con:
            test_first_job.initialize(con)
            prior=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(task['id']+':copy',)).fetchone()
        repair=state.get('planning_review_probe_import_repair')
        if prior and json.loads(prior['identity'])['payload']['Cmd']==payload['Cmd'] and not repair:
            # Consume the exact old job before registering a changed experiment.
            with b.db() as con:old=test_first_job.run(b,con,task['id'],'copy',payload)
            if old['exit_code']!=1:raise ValueError('one failed legacy inline probe required')
            info=b.docker('GET','/containers/'+old['container_id']+'/json')
            stderr=b.docker_stdout(old['container_id'],include_stderr=True,limit=8192) if info else ''
            if info and "ModuleNotFoundError: No module named 'acp_transport'" not in stderr:
                raise ValueError('exact inline probe import failure required')
            repair=dict(operation='fixed_probe_root_import_repair_v1',attempt_limit=1,
                old_job_identity=json.loads(prior['identity']),old_result=old,
                diagnostic='missing_acp_transport' if info else 'retired_probe_stderr_unavailable',
                historical_probe_cause='observed_import_failure' if info else 'unknown',
                required_control='module_absent_before_root_path_and_present_after',
                stderr_sha256=hashlib.sha256(stderr.encode()).hexdigest() if info else None,
                previous_hold=state.get('planning_review_observation_hold'),delivery_approval=False)
            updated={**state,'planning_review_probe_import_repair':repair}
            updated.pop('planning_review_observation_hold',None)
            with b.db() as con:
                current=json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])
                if current!=state:raise ValueError('probe failure hold changed')
                con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
            state=updated
        job_task=str(uuid.uuid5(uuid.NAMESPACE_URL,'planning-review-probe-import-v1:'+task['id'])) if repair else task['id']
        with b.db() as con:result=test_first_job.run(b,con,job_task,'copy',corrected)
        if result['exit_code']!=0:raise ValueError('actual installed initialization observation failed')
        observed=json.loads(result['output'])
        new=prepare(config,state,task,reads,failure,observed)
        new['planning_review_observation'].update(worker_image=b.IMAGE,
            probe_source_sha256=hashlib.sha256(program.read_bytes()).hexdigest(),
            probe_output_sha256=result['output_sha256'],probe_container_id=result['container_id'])
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()[0])!=state:
                raise ValueError('planning review hold changed during observation')
            con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new


def tick(b):
    with b.db() as con:
        plans.initialize(con)
        rows=con.execute('SELECT source_task,state FROM technical_remediation_plans').fetchall()
    for row in rows:
        state=json.loads(row['state'])
        hold=state.get('planning_review_observation_hold') or {}
        import_repair_candidate=(hold.get('category')=='ValueError'
            and hold.get('error_sha256')==hashlib.sha256(b'actual installed initialization observation failed').hexdigest()
            and not state.get('planning_review_probe_import_repair'))
        if (state.get('stage')!='blocked' or state.get('category')!='ValueError' or not state.get('plan_task')
                or state.get('planning_review_observation') or (hold and not import_repair_candidate)):continue
        try:reconcile(b,row['source_task'])
        except (TimeoutError,ConnectionError):continue  # Observe exact durable job.
        except Exception as error:
            with b.db() as con:
                current=json.loads(con.execute('SELECT state FROM technical_remediation_plans WHERE source_task=?',(row['source_task'],)).fetchone()[0])
                if current!=state:continue
                current['planning_review_observation_hold']=dict(category=type(error).__name__,
                    error_sha256=hashlib.sha256(str(error).encode()).hexdigest(),cause='unknown',retry_authorized=False)
                con.execute('UPDATE technical_remediation_plans SET state=? WHERE source_task=?',(json.dumps(current,sort_keys=True),row['source_task']))
