"""One CTO diagnosis after a measured provider-routing repair; never an author retry."""
import hashlib
import json
import re
import time
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def validate_canary(event,receipt,execution,response_sha,schema_sha):
    if (event.get('event')!='model_proxy_request' or event.get('status')!=200
            or event.get('execution_id')!=execution or event.get('require_parameters') is not True
            or event.get('routing_compatibility')!='haiku_named_tool_v1'
            or event.get('upstream_require_parameters') is not False or event.get('tool_count')!=1
            or event.get('decision_adapter')!='validated_typed_decision_adapter_v1'
            or event.get('decision_output_sha256')!=response_sha
            or receipt.get('operation')!='validated_typed_decision_adapter_v1'
            or receipt.get('output_sha256')!=response_sha or receipt.get('model_values_preserved') is not True
            or receipt.get('schema_sha256')!=schema_sha
            or receipt.get('worker_tool_executed') is not False or receipt.get('delivery_approval') is not False):
        raise ValueError('actual typed technical transport qualification required')


def proxy_info(b):
    info=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
    labels=(info or {}).get('Config',{}).get('Labels',{})
    if (not info or not info.get('State',{}).get('Running')
            or labels.get('com.docker.compose.project')!=b.PREFIX
            or labels.get('com.docker.compose.service')!='model-proxy'):
        raise ValueError('owned live model proxy required')
    return info


def register(b,payload,*,review=False,mediation=False):
    """Operator-only registration, using actual owned proxy logs and its ledger."""
    if not isinstance(payload,dict) or set(payload)!={'execution_id','response_sha256'}:
        raise ValueError('exact synthetic transport receipt required')
    execution=payload['execution_id'];sha=payload['response_sha256']
    if review and mediation:raise ValueError('one transport qualification mode required')
    if str(uuid.UUID(execution))!=execution or not re.fullmatch(r'[a-f0-9]{64}',sha):
        raise ValueError('canonical qualification identity required')
    try:import artifact_rejection_evidence as logs
    except ImportError:from broker import artifact_rejection_evidence as logs
    with b.LOCK:
        with b.db() as c:
            if c.execute('SELECT 1 FROM native_bindings WHERE request_id=?',(execution,)).fetchone():
                raise ValueError('qualification cannot be a product task')
        proxy=proxy_info(b)
        script='''import sys,json,sqlite3,hashlib,model_proxy,model_policy,provider_tool_routing
from pathlib import Path
p=Path(model_proxy.COUNTER_PATH).with_name("deterministic-reads.sqlite")
with sqlite3.connect(p.as_uri()+"?mode=ro",uri=True) as c:
 rows=[json.loads(r[0]) for r in c.execute("SELECT receipt FROM typed_decisions WHERE execution_id=?",(sys.argv[1],))]
print(json.dumps({"model":model_policy.MODEL,"routing_sha256":hashlib.sha256(Path(provider_tool_routing.__file__).read_bytes()).hexdigest(),"receipts":rows}))
'''
        entry=b.docker('POST','/containers/'+proxy['Id']+'/exec',dict(AttachStdout=True,
            AttachStderr=False,Tty=True,Env=['PYTHONPATH=/'],Cmd=['python','-c',script,execution]))
        conn=b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('POST','/v1.45/exec/'+entry['Id']+'/start',json.dumps(dict(Detach=False,Tty=True)),
                         {'Content-Type':'application/json'})
            response=conn.getresponse();raw=response.read(16385)
            if response.status!=200 or len(raw)>16384:raise ValueError('bounded qualification query required')
        finally:conn.close()
        outcome=b.docker('GET','/exec/'+entry['Id']+'/json')
        if outcome.get('Running') or outcome.get('ExitCode')!=0:raise ValueError('qualification query failed')
        value=json.loads(raw)
        if value['model']!='anthropic/claude-haiku-5.5' or len(value['receipts'])!=1:
            raise ValueError('one Haiku technical transport receipt required')
        conn=b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('GET','/v1.45/containers/'+proxy['Id']+'/logs?stdout=1&tail=128')
            response=conn.getresponse();raw=response.read(262145)
            if response.status!=200 or len(raw)>262144:raise ValueError('bounded qualification logs required')
        finally:conn.close()
        events=[]
        for line in logs.decode_logs(raw):
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('event')=='model_proxy_request' and event.get('execution_id')==execution:events.append(event)
        if len(events)!=1:raise ValueError('one correlated actual request required')
        from decision_schema import apply
        if mediation:
            from mediation_transport_fixture import body
            expected=apply(body())
        elif review:
            from review_transport_fixture import body
            expected=apply(body())
        else:
            expected=apply({'messages':[{'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'}]})
        validate_canary(events[0],value['receipts'][0],execution,sha,
                        digest(expected['response_format']['json_schema']['schema']))
        if review and (events[0].get('provider_schema_projection')!='haiku_review_union_v1'
                or events[0].get('canonical_schema_validation_preserved') is not True
                or value['receipts'][0].get('mode')!='test_review'
                or value['receipts'][0].get('manifest_sha256')!='a'*64
                or value['receipts'][0].get('review_acceptance_by_proxy') is not False):
            raise ValueError('synthetic projected review receipt required')
        if mediation:validate_mediation_canary(events[0],value['receipts'][0],value['routing_sha256'])
        if proxy_info(b)['Id']!=proxy['Id']:raise ValueError('proxy changed during qualification')
        proof=dict(operation='provider_diagnosis_transport_qualification_v1',execution_id=execution,
            model=value['model'],proxy_image=proxy['Image'],routing_sha256=value['routing_sha256'],
            response_sha256=sha,event=events[0],adapter_receipt=value['receipts'][0],
            worker_tool_executed=False,delivery_approval=False)
        table=('provider_mediation_qualifications' if mediation else
               'provider_review_qualifications' if review else 'provider_diagnosis_qualifications')
        if review:proof.update(operation='provider_review_transport_qualification_v1',actual_artifact_read=False)
        if mediation:proof.update(operation='provider_mediation_transport_qualification_v1',actual_artifact_read=False)
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS '+table+'('
                      'execution_id TEXT PRIMARY KEY,proof TEXT,at REAL)')
            old=c.execute('SELECT proof FROM '+table+' WHERE execution_id=?',(execution,)).fetchone()
            if old and json.loads(old[0])!=proof:raise ValueError('qualification identity drift')
            if not old:c.execute('INSERT INTO '+table+' VALUES(?,?,?)',
                                 (execution,json.dumps(proof,sort_keys=True),time.time()))
        return proof


def validate_mediation_canary(event,receipt,routing_sha):
    if (event.get('provider_schema_projection')!='haiku_mediation_union_v1'
            or event.get('canonical_schema_validation_preserved') is not True
            or routing_sha!='e982dafa69291d7efe979081e6594ef4d3bc9fa2bd321d4be2dba1d6b87ec668'
            or receipt.get('mode') not in (None,'technical') or 'manifest_sha256' in receipt
            or receipt.get('worker_tool_executed') is not False
            or receipt.get('delivery_approval') is not False):
        raise ValueError('synthetic nonauthorizing mediation transport receipt required')


def qualify(e):
    q=e.get('qualification') or {};failure=e.get('failure') or {}
    if not (e['enabled'] and e['test_first'] and e['author']!=e['cto'] and e['actor']==e['cto']
            and e['mode']=='planning' and e['source_status']=='failed' and e['status']=='failed'
            and e['failure_reason']=='agent_error.provider_server_error' and e['lease']=='closed'
            and not e['active'] and not e['red'] and not e['pending'] and e['diagnostic']
            and failure.get('version')=='acp-failure-receipt-v1' and failure.get('approval') is False
            and failure.get('method')=='session/prompt' and failure.get('cause')=='classified_hint'
            and failure.get('categories')==['provider_configuration']
            and q.get('operation')=='provider_diagnosis_transport_qualification_v1'
            and q.get('model')=='anthropic/claude-haiku-5.5'
            and q.get('worker_tool_executed') is False and q.get('delivery_approval') is False):
        raise ValueError('qualified idle CTO provider failure required')
    return dict(operation='provider_diagnosis_recovery_v1',issue=e['issue'],source_task=e['source_task'],
        failed_cto=e['failed_cto'],old_wakeup=e['old_wakeup'],diagnostic_sha256=digest(e['diagnostic']),
        failure_receipt=failure,qualification=q,historical_http_status_proven=False,
        author_retry_authorized=False,delivery_approval=False)


def recover(b,route,runs,source,prior,effects):
    if (not prior or prior['stage']!='test_first_blocked' or source.get('status')!='failed'
            or not route.get('enabled') or not route.get('test_first')):return False
    data=json.loads(prior['data'])
    if data.get('phase')!='test_first' or data.get('error') not in (
            'test_first_cto_execution_failed','provider_diagnosis_outcome_unconfirmed'):return False
    try:import handoffs,cto_prompt_bound_recovery as once
    except ImportError:from broker import handoffs,cto_prompt_bound_recovery as once
    with b.db() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='provider_diagnosis_qualifications'").fetchone():return False
        c.execute('CREATE TABLE IF NOT EXISTS provider_diagnosis_recoveries(source_task TEXT PRIMARY KEY,record TEXT)')
        stored=c.execute('SELECT record FROM provider_diagnosis_recoveries WHERE source_task=?',(source['id'],)).fetchone()
        record=json.loads(stored[0]) if stored else None
        if record and record['state']=='accepted':
            if data.get('test_first_cto_wakeup')==record['wakeup_id']:return False
            if (data.get('test_first_cto_wakeup')!=record['proof']['old_wakeup']
                    or digest(data.get('diagnostic'))!=record['proof']['diagnostic_sha256']):
                raise ValueError('accepted provider recovery lineage drift')
            data.update(provider_diagnosis_recovery=record,test_first_cto_wakeup=record['wakeup_id'],dispatched_at=record['at'])
            handoffs.save(c,source['id'],route['issue_id'],'test_first_cto_diagnosis',route['cto'],data,time.time())
            return True
        q=c.execute('SELECT proof FROM provider_diagnosis_qualifications ORDER BY at DESC LIMIT 1').fetchone()
        if not q:return False
        qualification=json.loads(q[0])
        if qualification['proxy_image']!=proxy_info(b)['Image']:return False
        candidates=[r for r in runs if r.get('agent_id')==route['cto'] and r.get('wakeup_id')==data.get('test_first_cto_wakeup')]
        if len(candidates)!=1:return False
        failed=candidates[0]
        bindings=c.execute('SELECT n.request_id,n.scope,l.status FROM native_bindings n JOIN leases l USING(request_id) '
            'WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',(failed['id'],route['cto'],route['issue_id'])).fetchall()
        if len(bindings)!=1:return False
        if bindings[0]['scope'].split(':')[-2:]!=['planning',failed['id']]:return False
        receipts=c.execute('SELECT receipt FROM acp_failure_receipts WHERE request_id=? AND method=?',
                           (bindings[0]['request_id'],'session/prompt')).fetchall()
        if len(receipts)!=1:return False
        try:
            proof=qualify(dict(enabled=route['enabled'],test_first=route['test_first'],author=route['author'],
                cto=route['cto'],actor=failed['agent_id'],mode=effects.settings['agents'].get(route['cto']),
                source_status=source['status'],status=failed['status'],failure_reason=failed.get('failure_reason'),
                lease=bindings[0]['status'],active=bool(c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()),
                red=bool(c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(route['issue_id'],)).fetchone()),
                pending=any(r.get('status') in ('queued','running','dispatched') for r in runs),
                diagnostic=data.get('diagnostic'),failure=json.loads(receipts[0][0]),qualification=qualification,
                issue=route['issue_id'],source_task=source['id'],failed_cto=failed['id'],old_wakeup=data['test_first_cto_wakeup']))
        except ValueError:return False
    def save(value):
        with b.db() as c:
            c.execute('INSERT INTO provider_diagnosis_recoveries VALUES(?,?) ON CONFLICT(source_task) DO UPDATE SET record=excluded.record',
                      (source['id'],json.dumps(value,sort_keys=True)))
            c.commit()
    instruction=('CONTROLLER CHANGED PROVIDER TRANSPORT. The previous independent CTO diagnosis failed with a '
        'provider_configuration hint, not a code verdict. The exact installed proxy has now passed a correlated '
        'technical typed-decision canary. Only provider endpoint selection changed; model, schemas, permissions '
        'and limits are unchanged. ONE CTO diagnosis recovery, not an author retry. No Red exists. '
        'Diagnose the original tests-only failure. Diagnostic: '+json.dumps(data['diagnostic'],sort_keys=True)+
        '. Qualification SHA256: '+digest(qualification)+'. Do not claim the exact historical HTTP cause '
        'is proven by a hint. Decide whether one concrete tests-only correction by the original author '
        'is justified under this changed condition, or escalate with precise missing evidence. '
        'Never edit files, fabricate Red, weaken existing tests, grant merge or declare homologation. '
        'Return only JSON: action (request_correction or escalate_cto), reason (one concrete sentence, <=1200 chars), '
        'optional_files ([]). No technical decision belongs to the CEO.\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n')
    result=once.dispatch(record,proof,save,lambda marker,allow:effects.ensure_wakeup(
        route['issue_id'],route['cto'],source['id'],marker,instruction,allow_create=allow),
        effects.remaining_calls(),route['minimum_calls'])
    if result and result['state']=='accepted':
        data.update(provider_diagnosis_recovery=result,test_first_cto_wakeup=result['wakeup_id'],dispatched_at=time.time())
        with b.db() as c:handoffs.save(c,source['id'],route['issue_id'],'test_first_cto_diagnosis',route['cto'],data,time.time())
    elif result:
        data.update(provider_diagnosis_recovery=result,
                    required_action='CTO observes durable wakeup marker; never repeat an uncertain POST')
        if time.time()-result['at']>=1800:data['error']='provider_diagnosis_outcome_unconfirmed'
        with b.db() as c:handoffs.save(c,source['id'],route['issue_id'],'test_first_blocked',route['cto'],data,time.time())
    return bool(result)
