"""Controller-only CLI; one fixed isolated experiment, no agent commands."""
import hashlib
import json
import time
import broker as b

source='01a10776-f6c9-705d-97c9-e0b23ffbb40b'
image=b.docker('GET','/images/delivery-kit-execution-broker:20261004.92/json')['Id']
name=b.PREFIX+'-event-order-v1-'+source
table='runtime_event_order_experiments'
with b.LOCK,b.db() as con:
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    row=con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',(source,)).fetchone()
    data=json.loads(row['data']);failure=data['validation_failure']
    assert row['stage']=='technical_decision_required' and data['decision']['action']=='escalate_cto' and data.get('independent_failure_finding')
    red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
    output=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',(source,failure['output_sha256'])).fetchone()[0]
    assert hashlib.sha256(output.encode()).hexdigest()==failure['output_sha256']
    assert con.execute("SELECT 1 FROM snapshots WHERE task_id=? AND status='complete' AND volume=?",(source,failure['volume'])).fetchone()
    con.execute('CREATE TABLE IF NOT EXISTS '+table+'(source_task TEXT PRIMARY KEY,status TEXT,receipt TEXT)')
    assert not con.execute('SELECT 1 FROM '+table+' WHERE source_task=?',(source,)).fetchone()
    con.execute('INSERT INTO '+table+' VALUES(?,?,?)',(source,'intent',json.dumps(dict(image=image,output_sha256=failure['output_sha256'],volume=failure['volume'],approval=False))))
    con.commit()
labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':source,'com.docker.compose.project':b.PREFIX}
assert not b.docker('GET','/containers/'+name+'/json')
created=b.docker('POST','/containers/create?name='+name,dict(Image=image,User='10000:10000',Entrypoint=['python'],
    Cmd=['/runtime_assertion_probe.py'],WorkingDir='/delivery',NetworkDisabled=True,
    Env=['PYTHONDONTWRITEBYTECODE=1','EVENT_ORDER_TRACE=1','SAVED_OUTPUT='+json.dumps(output),'FROZEN_TEST_HASHES='+json.dumps(red['red']['test_sha256'])],Labels=labels,
    HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=536870912,PidsLimit=128,
        Tmpfs={'/tmp':'rw,nosuid,nodev,size=512m,mode=1777'},Mounts=[dict(Type='volume',Source=failure['volume'],Target='/delivery',ReadOnly=True)])))
assert created and created.get('Id')
try:
    b.docker('POST','/containers/'+name+'/start');deadline=time.time()+60
    while time.time()<deadline:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and not info['State']['Running']:
            if info['State']['ExitCode']:raise ValueError('fixed runtime probe failed')
            proof=json.loads(b.docker_stdout(name,limit=65536))
            assert proof['operation']=='frozen_js_event_order_experiment_v1' and proof['approval'] is False and proof['output_sha256']==failure['output_sha256']
            with b.db() as con:
                prior=json.loads(con.execute("SELECT receipt FROM runtime_assertion_experiments_v3 WHERE source_task=? AND status='complete'",(source,)).fetchone()[0])['proof']
            equivalent=proof['suite']==prior['suite'] and proof['runtime_observations']==prior['runtime_observations']
            proof['untraced_observations_equal']=equivalent
            if not equivalent:raise ValueError('instrumented observations differ; diagnostic contaminated')
            receipt=dict(source_task=source,image=image,volume=failure['volume'],proof=proof,approval=False)
            with b.db() as con:con.execute('UPDATE '+table+' SET status=?,receipt=? WHERE source_task=?',('complete',json.dumps(receipt,sort_keys=True),source))
            print(json.dumps(dict(status='complete',suite=proof['suite'],observations=len(proof['runtime_observations']),events=sum(len(r['events']) for r in proof['event_reports']),untraced_observations_equal=equivalent,
                observed_report_keys=sorted({k for o in proof['runtime_observations'] for report in o['reports'].values() if isinstance(report,dict) for k in report}),approval=False)))
            break
        time.sleep(.2)
    else:raise TimeoutError('fixed runtime probe deadline')
except Exception as error:
    with b.db() as con:con.execute('UPDATE '+table+' SET status=?,receipt=? WHERE source_task=?',('blocked',json.dumps(dict(category=type(error).__name__,approval=False)),source))
    print(json.dumps(dict(status='blocked',category=type(error).__name__,approval=False)))
finally:
    info=b.docker('GET','/containers/'+name+'/json')
    if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items()):b.docker('DELETE','/containers/'+info['Id']+'?force=true')
