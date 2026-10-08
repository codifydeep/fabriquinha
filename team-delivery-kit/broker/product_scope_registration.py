"""Register a reverified scope base without changing any task or edit grant.

This isolated registry is deliberately NOT the issue's global base nor a latest
contract-revisions row. Future dispatch must bind one explicit authorized task.
"""
import hashlib
import json
try:
    from . import product_scope_ledger as ledger,product_scope_execution as execution,product_scope_job as materialization,validation_job
except ImportError:
    import product_scope_ledger as ledger
    import product_scope_execution as execution
    import product_scope_job as materialization
    import validation_job

IMAGE='sha256:c1563214982fac21a2aa22ab2a9130446632e6d4b5ca37f2a06fec36e2b394e0'


def _tick(b,key,effects):
    with b.LOCK,b.db() as con:state=ledger.load(con,key)
    if (state['stage']!='plan_approved' or state['author_blocked'] is not True
            or state.get('materialization',{}).get('stage')!='complete'):
        raise ValueError('completed materialization with author still blocked required')
    fx=effects or execution.NativeEffects(b)
    materialization.reauthenticate(state,fx)
    mat=state['materialization'];base=mat['base'];receipt=mat['receipt']
    actual_base=b.issue_base(state['context']['issue_id'])
    if any(actual_base[k]!=base[k] for k in ('base_sha','volume','manifest_sha256')):
        raise ValueError('registered original base changed')
    materialization.validate_receipt(state,base,receipt)
    volume=b.docker('GET','/volumes/'+mat['volume'])
    if (not volume or volume.get('Name')!=mat['volume'] or volume.get('Labels')!=
            {'delivery-kit.owner':b.OWNER,'delivery-kit.scope-plan':key}):
        raise ValueError('owned materialized scope volume required')
    registration=state.get('registration')
    if registration and registration['stage']=='complete':
        with b.db() as con:
            row=con.execute('SELECT receipt FROM product_scope_bases WHERE plan_key=?',(key,)).fetchone()
        if not row or json.loads(row[0])!=registration['receipt']:raise ValueError('scope registry receipt changed')
        return state
    if not registration:
        registration=dict(stage='verification_intent',image=IMAGE)
        state=execution.save(b,state,dict(state,registration=registration))
    if registration.get('image')!=IMAGE:raise ValueError('qualified scope verifier changed')
    payload=materialization.payload(state,base,mat['volume'],b)
    payload['Image']=IMAGE;payload['Cmd']=['/product_scope_base_verify.py']
    payload['Env'].append('MATERIALIZATION_RECEIPT_JSON='+ledger.encoded(receipt))
    for mount in payload['HostConfig']['Mounts']:mount['ReadOnly']=True
    result=validation_job.run(b,state['review_task']['id'],'scope_base_verify',payload)
    expected=dict(operation='verified_product_scope_base_v1',base_sha=receipt['base_sha'],
        original_base_manifest_sha256=base['manifest_sha256'],manifest_sha256=receipt['manifest_sha256'],
        contract_sha256=receipt['contract_sha256'],frozen_test_sha256=receipt['frozen_test_sha256'],
        delivery_approval=False,write_grant_issued=False)
    proof=json.loads(result['output']) if isinstance(result.get('output'),str) else None
    if (result.get('exit_code')!=0 or result.get('approval') is not False
            or not isinstance(result.get('output'),str)
            or hashlib.sha256(result['output'].encode()).hexdigest()!=result.get('output_sha256')
            or proof!=expected or any(proof[k] is not False for k in ('delivery_approval','write_grant_issued'))):
        raise ValueError('exact read-only base verification required')
    materialization.reauthenticate(state,fx)
    registered=dict(operation='registered_product_scope_base_v1',plan_key=key,issue_id=state['context']['issue_id'],
        source_task=state['context']['source_task'],volume=mat['volume'],base_sha=receipt['base_sha'],
        original_base_manifest_sha256=base['manifest_sha256'],manifest_sha256=receipt['manifest_sha256'],
        contract_sha256=receipt['contract_sha256'],contract=receipt['contract'],
        frozen_test_sha256=receipt['frozen_test_sha256'],proposal_sha256=state['proposal_sha256'],
        review_task=state['review_task']['id'],verifier_image=IMAGE,verification_job_key=result['validation_job_key'],
        verification_output_sha256=result['output_sha256'],write_grant_issued=False,delivery_approval=False)
    with b.LOCK,b.db() as con:
        if ledger.load(con,key)!=state:raise ValueError('scope state changed during base verification')
        con.execute('CREATE TABLE IF NOT EXISTS product_scope_bases(plan_key TEXT PRIMARY KEY,receipt TEXT NOT NULL)')
        con.execute('INSERT OR IGNORE INTO product_scope_bases VALUES (?,?)',(key,ledger.encoded(registered)))
        row=json.loads(con.execute('SELECT receipt FROM product_scope_bases WHERE plan_key=?',(key,)).fetchone()[0])
        if row!=registered:raise ValueError('immutable registered scope base changed')
        return ledger.save_transition(con,state,dict(state,registration=dict(registration,stage='complete',receipt=registered)))


def tick(b,key,effects=None):
    with b.LOCK,b.db() as con:state=ledger.load(con,key)
    if state.get('registration',{}).get('stage')=='blocked':return state
    try:return _tick(b,key,effects)
    except validation_job.Pending:raise
    except TimeoutError as error:
        raise validation_job.Pending('scope base verification pending; observe the same job') from error
    except (ValueError,KeyError,TypeError):
        with b.LOCK,b.db() as con:current=ledger.load(con,key)
        if current.get('author_blocked') is True and current.get('stage')=='plan_approved':
            execution.save(b,current,dict(current,registration=dict(current.get('registration') or {},stage='blocked',
                incident=dict(category='scope_base_registration_rejected',owner=current['context']['cto'],
                              next_action='diagnose_exact_base_verification',automatic_retry=False))))
        raise
