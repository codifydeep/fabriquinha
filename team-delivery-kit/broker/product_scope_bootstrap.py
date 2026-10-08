"""Open a scope plan from fixed-job and controller evidence, never CTO prose.

This prepares a plan only. The execution engine still needs explicit routing;
reading a contract never starts agents or grants an implementation workspace.
"""
import hashlib
import json
from portable_contract import is_test_path
try:
    from . import product_scope_execution as execution, product_scope_ledger as ledger, validation_job
except ImportError:
    import product_scope_execution as execution
    import product_scope_ledger as ledger
    import validation_job

IMAGE='sha256:d3f28550cc03a4cfc0feef8ab43062ef59790e4fd585fe6a5d57eefe623da616'


def prepare(b,issue,effects=None):
    fx=effects or execution.NativeEffects(b)
    with b.db() as con:
        row=con.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? '
                        'AND stage<>? ORDER BY updated DESC LIMIT 1',(issue,'superseded')).fetchone()
        route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        if not row or not route_row or row[1]!='technical_decision_required':raise ValueError('current technical hold required')
        source=row[0];data=json.loads(row[2]);route=json.loads(route_row[0]);failure=data.get('validation_failure') or {}
        if (route.get('enabled') is not True or route.get('test_first') is not True
                or failure.get('category')!='executed_test_failure' or failure.get('source_task')!=source):
            raise ValueError('enabled test-first route with executed functional failure required')
        snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)).fetchone()
        if not snapshot or snapshot[1]!='complete' or snapshot[0]!=failure.get('volume'):
            raise ValueError('complete exact failed delivery required')
        jobs=con.execute('SELECT identity,state FROM validation_jobs').fetchall()
    base=b.issue_base(issue)
    payload=dict(Image=IMAGE,User='10000:10000',Entrypoint=['python'],Cmd=['/product_scope_base_read.py'],
        NetworkDisabled=True,Env=['BASE_SHA='+base['base_sha'],'BASE_MANIFEST_SHA256='+base['manifest_sha256'],
                                  'CONTRACT_SHA256='+route['contract_sha256']],Labels={'delivery-kit.issue-id':issue},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=134217728,PidsLimit=16,Mounts=[dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True)]))
    result=validation_job.run(b,source,'scope_base_read',payload)
    if (result.get('exit_code')!=0 or result.get('approval') is not False
            or not isinstance(result.get('output'),str)
            or hashlib.sha256(result['output'].encode()).hexdigest()!=result.get('output_sha256')):
        raise ValueError('successful exact fixed base-read result required')
    proof=json.loads(result['output'])
    keys={'operation','base_sha','manifest_sha256','contract_sha256','contract','write_grant_issued','delivery_approval'}
    if (not isinstance(proof,dict) or set(proof)!=keys or proof['operation']!='inspected_product_scope_base_v1'
            or any(proof[k]!=base[k] for k in ('base_sha','manifest_sha256'))
            or proof['contract_sha256']!=route['contract_sha256'] or ledger.policy.digest(proof['contract'])!=route['contract_sha256']
            or any(proof[k] is not False for k in ('write_grant_issued','delivery_approval'))):
        raise ValueError('read-only original contract identity required')
    original=proof['contract'];inventory=failure.get('diagnostic_source_hashes') or {}
    eligible={p:sha for p,sha in inventory.items() if p in original['protected_files'] and p not in original['test_files']
              and p.endswith('.py') and not p.startswith(('.github/','.delivery-kit/','tests/','broker/'))
              and p.rsplit('/',1)[-1] not in ('conftest.py','setup.py')
              and not any(is_test_path(p,root,original['test_command'][0]) for root in original['test_roots'])}
    if not 1<=len(eligible)<=8:raise ValueError('bounded observed protected dependencies required')
    candidates=[]
    for raw_identity,raw_state in jobs:
        identity=json.loads(raw_identity);job=json.loads(raw_state)
        if identity.get('task')!=source or identity.get('kind')!='structure' or job.get('stage')!='complete':continue
        spec=identity.get('payload') or {}
        mounts=spec.get('HostConfig',{}).get('Mounts') or []
        if (spec.get('Image')!=b.OFFLINE_IMAGE
                or not any(m.get('Source')==snapshot[0] and m.get('ReadOnly') is True for m in mounts)):
            continue
        receipt=job.get('result') or {};output=receipt.get('output')
        if (receipt.get('exit_code')!=0 or not isinstance(output,str)
                or hashlib.sha256(output.encode()).hexdigest()!=receipt.get('output_sha256')):continue
        facts=json.loads(output)
        if (facts.get('baseline_tests_intact') is True
                and all(facts.get('diagnostic_file_sha256',{}).get(p)==sha for p,sha in eligible.items())):
            if facts not in candidates:candidates.append(facts)
    if len(candidates)!=1:raise ValueError('one exact structural failure inventory required')
    facts=candidates[0]
    context=dict(issue_id=issue,source_task=source,author=route['author'],cto=route['cto'],reviewer=route['techlead'],
        contract_sha256=route['contract_sha256'],snapshot_sha256=facts['manifest_sha256'],
        failure_output_sha256=failure['output_sha256'],eligible_code_sha256=eligible,frozen_test_sha256=facts['new_test_sha256'])
    with b.db() as con:
        red_row=con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
        review_row=con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
    if not red_row or not review_row:raise ValueError('existing reviewed historical Red required')
    red=json.loads(red_row[0]);review=json.loads(review_row[0]);decision=review.get('decision') or {}
    if (red['red']['test_sha256']!=context['frozen_test_sha256']
            or red['red']['base_manifest_sha256']!=base['manifest_sha256']
            or review.get('status')!='approved' or review.get('source_task')!=red['task_id']
            or review.get('manifest_sha256')!=red['red']['manifest_sha256']
            or review.get('read_contract')!='complete-lines-v2' or not review.get('review_task')
            or decision.get('action')!='approve_test_revision' or decision.get('optional_files')!=[]
            or decision.get('manifest_sha256')!=red['red']['manifest_sha256']):
        raise ValueError('scope replanning cannot repair altered or unreviewed tests')
    prospective=dict(context=context,original_contract=original)
    fx.verify_binding(prospective)
    if b.issue_base(issue)!=base:raise ValueError('original base changed during scope bootstrap')
    with b.LOCK,b.db() as con:
        current=con.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? '
                            'AND stage<>? ORDER BY updated DESC LIMIT 1',(issue,'superseded')).fetchone()
        current_route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        if (not current or tuple(current[:2])!=tuple(row[:2])
                or json.loads(current[2]).get('validation_failure')!=failure
                or not current_route or json.loads(current_route[0])!=route):
            raise ValueError('technical hold evidence or route changed during scope bootstrap')
        return ledger.open_plan(con,original,context)
