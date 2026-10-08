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


def reauthenticate(state,fx):
    fx.verify_binding(state)
    for phase,field,actor in (('proposal','proposal_task',state['context']['cto']),
                             ('review','review_task',state['context']['reviewer'])):
        task=fx.task(state[field]['id'],actor)
        wake=state.get('dispatch',{}).get(phase,{}).get('wakeup_id')
        if (ledger.task_identity(task)!=state[field] or not wake or task.get('wakeup_id')!=wake
                or execution.terminal_output(task)!=state['proposal' if phase=='proposal' else 'review']
                or fx.read_hashes(task,state['context']['eligible_code_sha256'])!=state['context']['eligible_code_sha256']):
            raise ValueError('exact authenticated native scope decisions and full reads required')
    proof=ledger.policy.qualify_review(state['context'],state['proposal'],state['review'],
        state['proposal_task'],state['review_task'],state['observed_read_hashes'])
    if proof!=state['qualification'] or proof['status']!='plan_approved':
        raise ValueError('unchanged approved independent scope plan required')


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
