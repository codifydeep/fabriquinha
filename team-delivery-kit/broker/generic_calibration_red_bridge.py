"""Await the durable prerequisite without restarting an author or granting Red.

Native workflow phases own their bounded observation deadlines. The parent must
not replace those deadlines with the generic ten-minute Docker-job timer.
"""
import json
import hashlib
import time

try:
    import generic_calibration_workflow as workflow,generic_calibration_gate as gate
    import generic_calibration_registration as registration,handoffs
except ImportError:
    from broker import generic_calibration_workflow as workflow,generic_calibration_gate as gate
    from broker import generic_calibration_registration as registration,handoffs


class Pending(TimeoutError):
    def __init__(self,issue,task,state):
        self.issue=issue;self.task=task;self.state=state
        super().__init__('Observe original generic calibration prerequisite; no author restart')


def reconcile_existing(b,route,source,prior):
    """A durable prerequisite keeps ownership ahead of legacy test repair.

    Revalidate its native source through request before restoring a projection;
    never infer an engine from Telegram, a worker or stale parent data.
    """
    if source.get('status')!='completed' or source.get('agent_id')!=route.get('author'):return False
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='generic_calibration_workflows'").fetchone():return False
        row=con.execute('SELECT state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
            (route['issue_id'],source['id'])).fetchone()
    if not row or json.loads(row[0])['stage']=='calibration_ready':return False
    if prior and prior['stage'] not in ('test_first_validation_pending','test_first_blocked','technical_decision_required'):return False
    state=workflow.request(b,route['issue_id'],source['id'])
    if state['stage']=='calibration_ready':return False
    data=json.loads(prior['data']) if prior else {}
    expected_stage='test_first_blocked' if state['stage']=='blocked' else 'test_first_validation_pending'
    if (prior and prior['stage']==expected_stage and data.get('calibration_prerequisite')==state
            and prior['owner']==(state.get('owner') or route['cto'])):return True
    if prior and data.get('calibration_prerequisite')!=state:
        data['calibration_projection_repair']=dict(operation='restore_durable_calibration_projection_v1',
            prior_stage=prior['stage'],prior_error=data.get('error'),
            prior_data_sha256=hashlib.sha256(prior['data'].encode()).hexdigest(),
            author_restarted=False,delivery_approval=False)
        prior={**prior,'data':json.dumps(data,sort_keys=True)}
    return observe(b,route,source,prior,Pending(route['issue_id'],source['id'],state))


def capture(b,con,issue,task,volume,prepared):
    state=workflow.request(b,issue,task)
    if state['stage']!='calibration_ready':raise Pending(issue,task,state)
    # Re-fetch actual native approvals and fixed-job evidence, not cached text.
    record=registration.register(b,issue,task)
    gate.require(volume==record['context']['candidate_volume']
        and prepared['manifest_sha256']==record['policy']['candidate_manifest_sha256']
        and prepared['test_sha256']==record['policy']['test_sha256'])
    result=gate.run(b,con,record)
    gate.require(state['calibration_receipt']==result['receipt'])
    return result['receipt'] # Prerequisite only; caller must execute actual Red.


def observe(b,route,source,prior,error):
    if not isinstance(error,Pending):return False
    gate.require(error.issue==route['issue_id'] and error.task==source['id'])
    state=error.state
    gate.require(state.get('delivery_approval') is False and state.get('execution_authorized') is False)
    data=json.loads(prior['data']) if prior else {}
    data.update(source_task=source['id'],phase='test_first',
        calibration_prerequisite=state,author_retry_authorized=False,delivery_approval=False,
        required_action=state.get('required_action') or 'Observe original source-bound calibration workflow')
    # Do not carry an unrelated lease/job timer into native technical work.
    data.pop('validation_wait',None)
    stage='test_first_validation_pending'
    if state['stage']=='blocked':
        stage='test_first_blocked';data['error']='generic_calibration_prerequisite:'+state['category']
    else:data.pop('error',None)
    with b.db() as con:
        handoffs.save(con,source['id'],route['issue_id'],stage,state.get('owner') or route['cto'],data,time.time())
    return True
