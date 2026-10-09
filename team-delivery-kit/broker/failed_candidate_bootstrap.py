"""One evidence-bound infrastructure repair before the first agent prompt.

No worker API, counter reset, new business allowance or delivery approval.
The original failed dispatch/terminal receipt remains in the issue ledger.
"""
import hashlib
import json
import time

# Audited legacy worker with the 32 KiB product-lockdown incompatibility. A
# merely different image or generic transport failure is not repair authority.
LEGACY_WORKER_IMAGE='sha256:edbe469d49cf8febc9ccc6505e907afdd1e722e6c1d82b161d8b4b4acef2d143'
try:
    from . import failed_candidate_execution as execution, bound_failure_context, native, validation_job, handoffs
except ImportError:
    import failed_candidate_execution as execution, bound_failure_context, native, validation_job, handoffs


def prepare(state,failed,request,proof):
    if state.get('bootstrap_recovery'):
        if (state['bootstrap_recovery']['failed_task']!=failed
                or state['bootstrap_recovery']['request_id']!=request
                or state['bootstrap_recovery']['proof']!=proof):raise ValueError('bootstrap repair already consumed')
        return state
    if (state.get('status')!='blocked_technical_recovery'
            or state.get('terminal',{}).get('task_id')!=failed
            or state.get('terminal',{}).get('status')!='failed'
            or state.get('dispatch',{}).get('task_id')!=failed
            or proof.get('operation')!='preprompt_product_fence_probe_v1'
            or any(proof.get(k) is not True for k in ('actual_workspace_unchanged','frozen_tests_intact'))
            or any(proof.get(k) is not False for k in ('delivery_approval','tests_executed'))
            or not proof.get('legacy_size_conflicts') or proof.get('product_limit')!=2097152
            or any(proof.get(k)!=state['seed']['selection'].get(k)
                   for k in ('manifest_sha256','product_sha256','test_sha256'))
            or proof.get('scope')!=sorted(state['seed']['selection']['product_sha256'])
            or not proof.get('validation_job_key') or not proof.get('output_sha256')):
        raise ValueError('exact pre-prompt bootstrap and executed fixed fence proof required')
    result=json.loads(json.dumps(state))
    result['bootstrap_recovery']=dict(operation='preprompt_product_fence_recovery_v1',failed_task=failed,
        request_id=request,previous_dispatch=state['dispatch'],previous_terminal=state['terminal'],
        previous_wakeup=state.get('wakeup_id'),previous_marker=state['dispatch_marker'],proof=proof,
        infrastructure_attempt_limit=1,retry_budget_reset=False,delivery_approval=False)
    for field in ('dispatch','dispatch_marker','wakeup_id','terminal'):result.pop(field,None)
    result.update(status='admitted_not_dispatched',owner='author')
    return result


def qualify(b,con,route,data,state,settings):
    failed=state['terminal']['task_id'];issue=route['issue_id']
    runs=native.issue_task_runs(settings,issue)
    authors=[r for r in runs if r.get('agent_id')==route['author']]
    record=next((r for r in authors if r['id']==failed),{})
    if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=failed
            or record.get('status')!='failed' or record.get('error')!='hermes initialize failed: hermes process exited'
            or record.get('wakeup_id')!=state.get('wakeup_id')
            or any(r.get('status') not in ('failed','completed','cancelled','canceled') for r in runs)):
        raise ValueError('latest closed pre-prompt failed author required')
    rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(failed,)).fetchall()
    if len(rows)!=1 or rows[0]['status'] not in ('closed','failed') or rows[0]['issue_id']!=issue or rows[0]['agent_id']!=route['author']:
        raise ValueError('closed exact bootstrap binding required')
    binding=dict(rows[0]);request=binding['request_id']
    startup=con.execute('SELECT state FROM acp_startups WHERE request_id=?',(request,)).fetchone()
    errors=con.execute('SELECT 1 FROM broker_errors WHERE request_id=? AND operation=? AND category=?',
        (request,'transport_start','bootstrap:broker_internal')).fetchone()
    if (not startup or json.loads(startup[0]).get('stage')!='failed'
            or json.loads(startup[0]).get('category')!='startup_broker_internal' or not errors
            or con.execute('SELECT 1 FROM acp_events WHERE request_id=?',(request,)).fetchone()
            or con.execute('SELECT 1 FROM tool_events WHERE request_id=?',(request,)).fetchone()):
        raise ValueError('no ACP event, prompt or tool may precede infrastructure repair')
    active=con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) WHERE n.issue_id=? AND l.status IN ('creating','starting','running','closing')",(issue,)).fetchone()
    if active:raise ValueError('settled issue leases required')
    origin=con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(state['source_task'],)).fetchone()
    original=json.loads(origin[0]) if origin else {}
    if (not bound_failure_context.verified_failed_diagnostic(con,state['source_task'],original)
            or original.get('failed_candidate_execution',{}).get('grant_sha256')!=state['grant_sha256']
            or execution.digest(original.get('failed_candidate_plan'))!=state['plan_sha256']
            or execution.digest(original.get('failed_candidate_plan_review'))!=state['review_sha256']
            or state['contract_sha256']!=route['contract_sha256'] or state['author']!=route['author']):
        raise ValueError('unchanged reviewed replan required')
    creation=con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone()
    if (not creation or json.loads(creation[0]).get('Image')!=LEGACY_WORKER_IMAGE
            or b.IMAGE==LEGACY_WORKER_IMAGE):
        raise ValueError('changed installed immutable worker required')
    base=b.handoff_runtime.task_base(b,issue,state['source_task'])
    volume=b.PREFIX+'-work-'+hashlib.sha256(binding['scope'].encode()).hexdigest()[:32]
    labels=(b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.scope')!=binding['scope']:
        raise ValueError('owned actual implementation workspace required')
    payload=dict(Image=b.IMAGE,User='0:0',Entrypoint=['python'],Cmd=['/bootstrap_fence_probe.py'],NetworkDisabled=True,
        Env=['BASE_MANIFEST_SHA256='+base['manifest_sha256'],
             'REVISION_SEED_JSON='+json.dumps(state['seed']['selection'],sort_keys=True)],
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':failed},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],CapAdd=['CHOWN','DAC_OVERRIDE'],
            SecurityOpt=['no-new-privileges'],Memory=134217728,NanoCpus=500000000,PidsLimit=16,
            Tmpfs={'/workspace':'rw,nosuid,nodev,size=64m,mode=1777'},Mounts=[
                dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True),
                dict(state['seed']['mount']),dict(Type='volume',Source=volume,Target='/evidence-work',ReadOnly=True)]))
    result=validation_job.run(b,failed,'bootstrap_fence',payload)
    if result.get('exit_code')!=0 or hashlib.sha256(result.get('output','').encode()).hexdigest()!=result.get('output_sha256'):
        raise ValueError('fixed bootstrap probe failed; preserve receipt')
    proof=json.loads(result['output'])
    proof.update(validation_job_key=result['validation_job_key'],output_sha256=result['output_sha256'],image=b.IMAGE)
    if native.issue_task_runs(settings,issue)!=runs:
        raise ValueError('native execution changed during fixed preparation probe')
    return failed,request,proof,original


def tick(b):
    settings=json.loads((b.STATE/'native.json').read_text())
    with b.db() as con:
        rows=list(con.execute("SELECT source_task,issue_id,data FROM delivery_handoffs WHERE stage='technical_decision_required'"))
    for row in rows:
        data=json.loads(row['data'])
        if data.get('error')!='bounded_replan_execution_failed' or data.get('bootstrap_recovery_incident'):continue
        try:
            with b.db() as con:
                state=execution.load(con,row['issue_id'])
                if not state or state.get('bootstrap_recovery') or state.get('status')!='blocked_technical_recovery':continue
                route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
                if not route.get('enabled'):continue
                failed,request,proof,original=qualify(b,con,route,data,state,settings)
                repaired=prepare(state,failed,request,proof)
                # Qualification never overwrites an intervening handoff or execution.
                current=con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(row['source_task'],)).fetchone()
                if (not current or json.loads(current[0])!=data
                        or execution.load(con,row['issue_id'])!=state):raise ValueError('bootstrap handoff changed during probe')
                if row['source_task']!=failed:raise ValueError('exact current bootstrap source required')
                execution.persist(con,row['issue_id'],repaired)
                data.update(bootstrap_recovery=repaired['bootstrap_recovery'],
                    failed_candidate_execution={'grant_sha256':state['grant_sha256']},finding=original['finding'],
                    trigger_task=failed,diagnostic_revision='bootstrap-fence:'+proof['output_sha256'])
                data.pop('required_action',None)
                handoffs.save(con,failed,row['issue_id'],'correct_author',route['author'],data,time.time())
        except validation_job.Pending:
            continue  # Durable job, same handle; no native agent has been dispatched.
        except (ValueError,KeyError,TypeError) as error:
            with b.db() as con:
                current=con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(row['source_task'],)).fetchone()
                if current and json.loads(current[0])==data:
                    data['bootstrap_recovery_incident']=dict(category='bootstrap_recovery_precondition_rejected',
                        reason=str(error)[:240],owner='cto',automatic_retry=False,delivery_approval=False)
                    handoffs.save(con,row['source_task'],row['issue_id'],'technical_decision_required',route['cto'],data,time.time())
