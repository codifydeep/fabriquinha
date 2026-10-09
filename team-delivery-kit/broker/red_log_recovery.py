"""Recover exact stopped Red-job logs, never replay tests or model execution."""
import json
import time


def eligible(source,prior,job):
    if not prior or not job or source.get('status')!='completed': return False
    data=json.loads(prior['data']);identity=json.loads(job['identity']);state=json.loads(job['state'])
    return (prior['stage']=='technical_decision_required'
        and data.get('phase')=='test_first'
        and data.get('error')=='RuntimeError:validator output unavailable'
        and identity['name'].endswith('-red-v2-'+source['id'])
        and identity['payload']['Labels'].get('delivery-kit.test-first-task')==source['id']
        and state['stage']=='start_intent' and bool(state.get('container_id')))


def reconcile(b,route,source,prior,effects):
    data=json.loads(prior['data']) if prior else {}
    if (not prior or prior['stage']!='technical_decision_required'
            or source.get('status')!='completed' or data.get('phase')!='test_first'
            or data.get('error')!='RuntimeError:validator output unavailable'): return False
    with b.db() as c:
        job=c.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',
            (source['id']+':red',)).fetchone()
        if not eligible(source,prior,job): return False
        c.execute('CREATE TABLE IF NOT EXISTS red_log_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
        old=c.execute('SELECT receipt FROM red_log_recoveries WHERE source_task=?',(source['id'],)).fetchone()
        receipt=json.loads(old[0]) if old else dict(operation='same_red_job_log_recovery_v1',
            source_task=source['id'],issue_id=route['issue_id'],stage='intent',
            container_id=json.loads(job['state'])['container_id'],
            author_restarted=False,tests_reexecuted=False,delivery_approval=False)
        if receipt['stage'] in ('blocked','complete'): return True
        c.execute('INSERT OR REPLACE INTO red_log_recoveries VALUES(?,?)',(source['id'],json.dumps(receipt)))
    try:
        result=effects.capture_test_first_red({'task_id':source['id']})
        if result['task_id']!=source['id'] or result['issue_id']!=route['issue_id']:
            raise ValueError('Red capture identity drift')
        receipt.update(stage='complete',output_sha256=result['red']['output_sha256'])
    except TimeoutError:
        return True  # same registered job; do not re-create or re-start it
    except Exception as error:
        receipt.update(stage='blocked',error=type(error).__name__+':'+str(error)[:180])
    with b.db() as c:
        c.execute('UPDATE red_log_recoveries SET receipt=? WHERE source_task=?',(json.dumps(receipt),source['id']))
        if receipt['stage']=='complete':
            try: import handoffs
            except ImportError: from broker import handoffs
            data=json.loads(prior['data']);data['red_log_recovery']=receipt
            handoffs.save(c,source['id'],route['issue_id'],'test_first_red_captured',route['cto'],data,time.time())
    return True
