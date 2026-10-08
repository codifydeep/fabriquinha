"""Maintenance-only recovery of a never-started, canonically identical Red job."""
import hashlib
import json
import time


def resume(b,task):
    try:import controller_maintenance as maintenance,failed_test_checkpoint as checkpoint,native,test_first_job as jobs
    except ImportError:from broker import controller_maintenance as maintenance,failed_test_checkpoint as checkpoint,native,test_first_job as jobs
    with b.LOCK,b.db() as con:
        barrier=maintenance.current(con)
        if not barrier or barrier.get('stage')!='sealed' or barrier.get('drained') is not True:
            raise ValueError('sealed drained maintenance required')
        row=con.execute('SELECT issue_id,receipt FROM failed_test_checkpoint_executions WHERE source_task=?',(task,)).fetchone()
        if not row:raise ValueError('exact failed checkpoint required')
        issue,saved=row[0],json.loads(row[1])
        if saved.get('canonical_image_recovery'):return saved
        expected_failure=hashlib.sha256(b'fixed test-first job isolation drift').hexdigest()
        if (saved.get('status')!='rejected' or saved.get('failure_type')!='ValueError'
                or saved.get('failure_sha256')!=expected_failure
                or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
            raise ValueError('idle exact image comparison rejection required')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        if checkpoint.digest(route)!=saved['route_sha256']:raise ValueError('checkpoint route drift')
        job=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(task+':red',)).fetchone()
        if not job:raise ValueError('durable exact Red intent required')
        identity,state=map(json.loads,job)
        if state.get('stage')!='create_intent':raise ValueError('unstarted create intent required')
        frozen=con.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(task,)).fetchone()
        binding=con.execute('SELECT n.request_id,l.status,g.mode FROM native_bindings n JOIN leases l USING(request_id) '
            'JOIN grants g USING(request_id) WHERE n.task_id=?',(task,)).fetchall()
        calibration=con.execute('SELECT state FROM harness_qualifications WHERE task_id=?',(task,)).fetchone()
        if (not frozen or frozen['status']!='complete' or frozen['volume']!=saved['snapshot_volume']
                or len(binding)!=1 or binding[0]['request_id']!=saved['request_id']
                or binding[0]['status']!='closed' or binding[0]['mode']!='implementation'
                or not calibration or json.loads(calibration[0]).get('stage')!='passed'):
            raise ValueError('preserved source, closed author and passed calibration required')
        settings=json.loads((b.STATE/'native.json').read_text())
        source=native.task_record(settings,task,route['author'])
        if not checkpoint.eligible(route,source,native.issue_task_runs(settings,issue)):
            raise ValueError('latest terminal source required')
        labels=(b.docker('GET','/volumes/'+frozen['volume']) or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task:
            raise ValueError('owned failed snapshot required')
        info=b.docker('GET','/containers/'+identity['name']+'/json')
        if (not info or info['State']['Status']!='created' or info['State']['Running'] is not False
                or not info['State'].get('StartedAt','').startswith('0001-') or info.get('ExecIDs')):
            raise ValueError('exact never-started Red container required')
        pin=identity['payload']['Image']
        if '@sha256:' not in pin or pin==info['Image']:raise ValueError('repository digest versus canonical ID required')
        jobs.verify(b,info,identity['payload'])
        recovery=dict(operation='canonical_red_image_observation_v1',previous_checkpoint=saved,
            previous_job_state=state,container_id=info['Id'],requested_pin=pin,canonical_id=info['Image'],
            maintenance_operation=barrier['operation_id'],author_restarted=False,
            create_replayed=False,start_replayed=False,delivery_approval=False)
        new={**saved,'status':'capturing','canonical_image_recovery':recovery}
        # A bounded observation window, not a renewed author iteration budget.
        observed={**state,'deadline':time.time()+600,'canonical_image_recovery':recovery['operation']}
        con.execute('UPDATE test_first_jobs SET state=? WHERE job_key=?',(json.dumps(observed,sort_keys=True),task+':red'))
        con.execute('UPDATE failed_test_checkpoint_executions SET receipt=? WHERE source_task=?',(json.dumps(new,sort_keys=True),task))
        return new
