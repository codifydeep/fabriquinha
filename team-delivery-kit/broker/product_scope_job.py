"""Durable fixed scope materialization after reauthentication of native reviews.

No installation, route mutation, author wakeup or edit grant occurs here.
The qualified image copies only the original base into a separate owned volume.
"""
import hashlib
import json
import re
import time
try:
    from . import product_scope_ledger as ledger, product_scope_execution as execution, validation_job
except ImportError:
    import product_scope_ledger as ledger
    import product_scope_execution as execution
    import validation_job

IMAGE='sha256:64c265cf93432fa87492b0ba4271e113e49e04efa2b52ccc9ff3ea79ea84a62b'


def proposal_wakeup(state,fx):
    """Authenticate a reused proposal against its immutable failed-review parent.

    A review-only recovery must not wake the CTO again. The original dispatch
    remains authoritative, but only for the exact proposal and parent hash
    qualified by the controller. Never inherit a review or an approval.
    """
    wake=state.get('dispatch',{}).get('proposal',{}).get('wakeup_id')
    if wake:return wake
    recovery=state.get('mount_recovery') or {}
    if not recovery:return None
    with fx.b.db() as con:parent=ledger.load(con,recovery['previous_plan'])
    proof=recovery.get('proof') or {}
    if (parent['stage']!='blocked' or parent.get('incident',{}).get('category')!='invalid_scope_review'
            or proof.get('operation')!='qualified_scope_mount_recovery_v1'
            or proof.get('original_plan_sha256')!=ledger.policy.digest(parent)
            or proof.get('proposal_sha256')!=state['proposal_sha256']
            or proof.get('failed_task')!=parent['incident'].get('task_id')
            or proof.get('delivery_approval') is not False or proof.get('write_grant_issued') is not False
            or any(parent.get(k)!=state.get(k) for k in
                   ('context','original_contract','proposal','proposal_sha256','proposal_task'))):
        raise ValueError('exact immutable reused proposal lineage required')
    return parent.get('dispatch',{}).get('proposal',{}).get('wakeup_id')


def reauthenticate(state,fx):
    fx.verify_binding(state)
    for phase,field,actor in (('proposal','proposal_task',state['context']['cto']),
                             ('review','review_task',state['context']['reviewer'])):
        task=fx.task(state[field]['id'],actor)
        wake=proposal_wakeup(state,fx) if phase=='proposal' else state.get('dispatch',{}).get(phase,{}).get('wakeup_id')
        if (ledger.task_identity(task)!=state[field] or not wake or task.get('wakeup_id')!=wake
                or execution.terminal_output(task)!=state['proposal' if phase=='proposal' else 'review']
                or fx.read_hashes(task,state['context']['eligible_code_sha256'])!=state['context']['eligible_code_sha256']):
            raise ValueError('exact authenticated native scope decisions and full reads required')
    proof=ledger.policy.qualify_review(state['context'],state['proposal'],state['review'],
        state['proposal_task'],state['review_task'],state['observed_read_hashes'])
    if proof!=state['qualification'] or proof['status']!='plan_approved':
        raise ValueError('unchanged approved independent scope plan required')


def recover_proposal_lineage(b,config,run,effects=None):
    """Resume only a pre-effect rejection proven to lack a reused CTO wakeup.

    This does not retry an executed job. Both native decisions and all reads
    must reauthenticate before the atomic transition, and any prior job/volume
    or richer materialization intent makes this recovery ineligible.
    """
    with b.db() as con:state=ledger.load(con,run['plan_key'])
    held=state.get('materialization') or {}
    if (config.get('enabled') is not True or run.get('stage')!='blocked'
            or run.get('incident',{}).get('category')!='scope_pipeline_precondition_rejected'
            or run['incident'].get('phase')!='scope_plan'
            or state['stage']!='plan_approved' or state.get('author_blocked') is not True
            or state.get('delivery_approval') is not False or state.get('reauthentication_recovery')
            or not state.get('mount_recovery') or set(held)!={'stage','incident'}
            or held['stage']!='blocked' or held['incident'].get('category')!='scope_materialization_rejected'
            or state.get('dispatch',{}).get('proposal',{}).get('wakeup_id')
            or state['context']['issue_id']!=config['issue_id']
            or state['context']['contract_sha256']!=config['contract_sha256']
            or state['context']['source_task']!=run.get('source_task')):
        return run
    fx=effects or execution.NativeEffects(b)
    reauthenticate(state,fx)
    with b.db() as con:
        if any(json.loads(row[0]).get('task')==state['review_task']['id']
               and json.loads(row[0]).get('kind')=='scope_materialize'
               for row in con.execute('SELECT identity FROM validation_jobs')):
            raise ValueError('existing scope materialization job must be observed, never reset')
    volume=b.PREFIX+'-scope-contract-'+state['key'][:24]
    if b.docker('GET','/volumes/'+volume):
        raise ValueError('existing scope materialization volume cannot be recovered as pre-effect rejection')
    proof=dict(operation='qualified_scope_proposal_lineage_recovery_v1',
        rejected_plan_sha256=ledger.policy.digest(state),proposal_sha256=state['proposal_sha256'],
        review_task=state['review_task']['id'],proposal_wakeup_id=proposal_wakeup(state,fx),
        previous_materialization=held,previous_run_incident=run['incident'],
        delivery_approval=False,write_grant_issued=False)
    after_plan=dict(state,reauthentication_recovery=proof);after_plan.pop('materialization')
    after_run=dict(run,stage='scope_plan',reauthentication_recovery=proof);after_run.pop('incident')
    with b.LOCK,b.db() as con:
        current=con.execute('SELECT config,state FROM product_scope_runs WHERE issue_id=?',(config['issue_id'],)).fetchone()
        if not current or json.loads(current[0])!=config or json.loads(current[1])!=run:
            raise ValueError('scope lineage recovery sponsor changed')
        ledger.save_transition(con,state,after_plan)
        changed=con.execute('UPDATE product_scope_runs SET state=? WHERE issue_id=? AND state=?',
                            (ledger.encoded(after_run),config['issue_id'],current[1]))
        if changed.rowcount!=1:raise ValueError('scope lineage recovery CAS failed')
    return after_run


def recover_unstarted_mount_observation(b,config,run,effects=None):
    """Observe an existing, unstarted fixed job after false-mount normalization.

    The job's identity, deadline and create intent are never replaced. Only a
    proven Docker omission of ReadOnly=false qualifies; no other drift or
    executed job can use this path.
    """
    with b.db() as con:state=ledger.load(con,run['plan_key'])
    held=state.get('materialization') or {}
    if (config.get('enabled') is not True or run.get('stage')!='blocked'
            or run.get('incident',{}).get('category')!='scope_pipeline_precondition_rejected'
            or state['stage']!='plan_approved' or state.get('author_blocked') is not True
            or state.get('delivery_approval') is not False or state.get('mount_observation_recovery')
            or held.get('stage')!='blocked' or held.get('incident',{}).get('category')!='scope_materialization_rejected'
            or set(held)!={'stage','incident','image','base','volume','deadline'}
            or state['context']['issue_id']!=config['issue_id']
            or state['context']['contract_sha256']!=config['contract_sha256']
            or state['context']['source_task']!=run.get('source_task')):return run
    fx=effects or execution.NativeEffects(b);reauthenticate(state,fx)
    if held['image']!=IMAGE or held['deadline']<=time.time():
        raise ValueError('same unexpired fixed materialization intent required')
    registered=b.issue_base(config['issue_id']);base={k:registered[k] for k in ('volume','base_sha','manifest_sha256')}
    volume=b.PREFIX+'-scope-contract-'+state['key'][:24]
    if held['base']!=base or held['volume']!=volume:raise ValueError('unchanged original base required')
    prepared=validation_job.grouped_create('POST','/containers/create?name=validation',payload(state,base,volume,b),b.PREFIX)
    task=state['review_task']['id'];key=validation_job.digest(dict(task=task,kind='scope_materialize',payload=prepared))
    name=b.PREFIX+'-validation-job-'+task+'-'+key[:12]
    expected=dict(prepared,Labels=dict(prepared['Labels'],**{
        'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':task,'delivery-kit.validation-job':key}))
    identity=dict(task=task,kind='scope_materialize',name=name,payload=expected)
    with b.db() as con:row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
    if not row or json.loads(row[0])!=identity:raise ValueError('same registered fixed validation job required')
    job=json.loads(row[1])
    if (job.get('stage')!='create_intent' or job.get('approval') is not False
            or job.get('deadline',0)<=time.time() or set(job)!={'stage','deadline','approval'}):
        raise ValueError('unexpired unstarted create intent required')
    info=b.docker('GET','/containers/'+name+'/json')
    if not info or info.get('State',{}).get('Status')!='created':raise ValueError('same unstarted container required')
    expected_mounts=expected['HostConfig']['Mounts'];actual_mounts=info.get('HostConfig',{}).get('Mounts')
    if expected_mounts==actual_mounts:raise ValueError('verified false mount omission required')
    validation_job.verify(b,info,expected)
    owned_volume=b.docker('GET','/volumes/'+volume)
    if not owned_volume or owned_volume.get('Labels')!={'delivery-kit.owner':b.OWNER,'delivery-kit.scope-plan':state['key']}:
        raise ValueError('same owned materialization volume required')
    proof=dict(operation='qualified_unstarted_scope_mount_observation_v1',job_key=key,container_id=info['Id'],
        identity_sha256=ledger.policy.digest(identity),previous_materialization=held,
        previous_run_incident=run['incident'],delivery_approval=False,write_grant_issued=False)
    after_plan=dict(state,mount_observation_recovery=proof,materialization=dict(held,stage='observe_existing_job'))
    after_plan['materialization'].pop('incident')
    after_run=dict(run,stage='scope_plan',mount_observation_recovery=proof);after_run.pop('incident')
    with b.LOCK,b.db() as con:
        current=con.execute('SELECT config,state FROM product_scope_runs WHERE issue_id=?',(config['issue_id'],)).fetchone()
        job_now=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
        if (not current or json.loads(current[0])!=config or json.loads(current[1])!=run
                or not job_now or tuple(job_now)!=tuple(row)):
            raise ValueError('fixed job recovery sponsor changed')
        ledger.save_transition(con,state,after_plan)
        con.execute('UPDATE product_scope_runs SET state=? WHERE issue_id=? AND state=?',
                    (ledger.encoded(after_run),config['issue_id'],current[1]))
    return after_run


def validate_receipt(state,base,receipt):
    expected=ledger.policy.candidate_contract(state['original_contract'],state['context'],state['proposal'])
    keys={'operation','issue_id','source_task','proposal_sha256','review_task','base_sha',
          'original_base_manifest_sha256','manifest_sha256','original_contract_sha256',
          'contract_sha256','contract','frozen_test_sha256','delivery_approval','write_grant_issued','historical_red_recreated'}
    fixed=dict(operation='materialized_product_scope_plan_v1',issue_id=state['context']['issue_id'],
        source_task=state['context']['source_task'],proposal_sha256=state['proposal_sha256'],
        review_task=state['review_task']['id'],base_sha=base['base_sha'],
        original_base_manifest_sha256=base['manifest_sha256'],
        original_contract_sha256=state['context']['contract_sha256'],contract_sha256=ledger.policy.digest(expected),
        contract=expected,frozen_test_sha256=state['context']['frozen_test_sha256'])
    if (not isinstance(receipt,dict) or set(receipt)!=keys or any(receipt[k]!=v for k,v in fixed.items())
            or any(receipt[k] is not False for k in ('delivery_approval','write_grant_issued','historical_red_recreated'))
            or not isinstance(receipt['manifest_sha256'],str) or not re.fullmatch(r'[a-f0-9]{64}',receipt['manifest_sha256'])):
        raise ValueError('materialization cannot alter tests, baseline identity or authorization')
    return receipt


def payload(state,base,volume,b):
    fields=('stage','author_blocked','delivery_approval','context','original_contract','proposal','proposal_sha256',
            'proposal_task','review','review_task','qualification','observed_read_hashes')
    return dict(Image=IMAGE,User='10000:10000',Entrypoint=['python'],Cmd=['/product_scope_materialize.py'],
        Env=['PRODUCT_SCOPE_PLAN_JSON='+ledger.encoded({k:state[k] for k in fields}),
             'BASE_MANIFEST_SHA256='+base['manifest_sha256']],NetworkDisabled=True,
        Labels={'delivery-kit.scope-plan':state['key']},HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',
            CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=1073741824,PidsLimit=16,
            Mounts=[dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True),
                    dict(Type='volume',Source=volume,Target='/revision',ReadOnly=False)]))


def _tick(b,key,effects=None,*,now=None):
    fx=effects or execution.NativeEffects(b)
    with b.LOCK,b.db() as con:state=ledger.load(con,key)
    if state['stage']!='plan_approved' or state['author_blocked'] is not True:
        raise ValueError('independent approved plan with author blocked required')
    reauthenticate(state,fx)
    registered_base=b.issue_base(state['context']['issue_id'])
    base={k:registered_base[k] for k in ('volume','base_sha','manifest_sha256')}
    if (not isinstance(base['volume'],str) or not base['volume']
            or not re.fullmatch(r'[a-f0-9]{40}',base['base_sha'])
            or not re.fullmatch(r'[a-f0-9]{64}',base['manifest_sha256'])):
        raise ValueError('original registered Git base identity required')
    now=time.time() if now is None else now
    materialization=state.get('materialization')
    volume=b.PREFIX+'-scope-contract-'+key[:24]
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.scope-plan':key}
    if not materialization:
        materialization=dict(stage='prepared',image=IMAGE,base=base,volume=volume,deadline=now+600)
        state=execution.save(b,state,dict(state,materialization=materialization))
    if any(materialization[k]!=v for k,v in dict(image=IMAGE,base=base,volume=volume).items()):
        raise ValueError('immutable materialization inputs changed')
    if materialization['stage']=='complete':return state
    if materialization['stage']=='blocked':raise ValueError('materialization blocked; preserve exact job')
    if now>=materialization['deadline']:
        execution.save(b,state,dict(state,materialization=dict(materialization,stage='blocked',
            incident={'category':'scope_materialization_observation_deadline','owner':'devops',
                      'next_action':'diagnose_exact_job','automatic_retry':False})))
        raise ValueError('materialization observation deadline; no new execution')
    existing=b.docker('GET','/volumes/'+volume)
    if existing and (existing.get('Name')!=volume or existing.get('Labels')!=labels):
        raise ValueError('foreign scope contract volume')
    if materialization['stage']=='prepared':
        state=execution.save(b,state,dict(state,materialization=dict(materialization,stage='volume_create_intent')))
        materialization=state['materialization']
        if not existing:b.docker('POST','/volumes/create',dict(Name=volume,Labels=labels))
        existing=b.docker('GET','/volumes/'+volume)
    if not existing:raise validation_job.Pending('observe the same scope volume create intent')
    if existing.get('Name')!=volume or existing.get('Labels')!=labels:raise ValueError('scope volume identity drift')
    result=validation_job.run(b,state['review_task']['id'],'scope_materialize',payload(state,base,volume,b))
    if (result.get('exit_code')!=0 or result.get('approval') is not False
            or not isinstance(result.get('output'),str)
            or hashlib.sha256(result['output'].encode()).hexdigest()!=result.get('output_sha256')):
        raise ValueError('successful exact fixed materialization job required')
    receipt=validate_receipt(state,base,json.loads(result['output']))
    reauthenticate(state,fx)  # Decisions and sponsorship can change while the job runs.
    return execution.save(b,state,dict(state,materialization=dict(materialization,stage='complete',
        receipt=receipt,job_key=result['validation_job_key'],output_sha256=result['output_sha256'])))


def tick(b,key,effects=None,*,now=None):
    with b.LOCK,b.db() as con:state=ledger.load(con,key)
    if state.get('materialization',{}).get('stage')=='blocked':return state
    try:return _tick(b,key,effects,now=now)
    except validation_job.Pending:raise
    except TimeoutError as error:
        raise validation_job.Pending('scope materialization pending; observe the same intent or job') from error
    except (ValueError,KeyError,TypeError):
        with b.LOCK,b.db() as con:current=ledger.load(con,key)
        if current.get('author_blocked') is True and current.get('stage')=='plan_approved':
            materialization=current.get('materialization') or {}
            if materialization.get('stage')!='blocked':
                execution.save(b,current,dict(current,materialization=dict(materialization,stage='blocked',
                    incident=dict(category='scope_materialization_rejected',owner=current['context']['cto'],
                        next_action='diagnose_bound_decisions_and_exact_job',automatic_retry=False))))
        raise
