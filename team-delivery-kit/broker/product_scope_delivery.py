"""Read-only qualification of an independently approved scope-revised delivery.

This supplies an effective contract, never merge/CI/deployment permission. The
portable driver must recheck this exact proof before each external transition.
"""
import json
try:
    from . import product_scope_task_binding as binding, product_scope_worker as worker, product_scope_execution as execution
    from . import product_scope_ledger as ledger
except ImportError:
    import product_scope_task_binding as binding
    import product_scope_worker as worker
    import product_scope_execution as execution
    import product_scope_ledger as ledger


def qualified(b,issue,delivery,effects=None):
    if not isinstance(delivery,dict) or set(delivery)!={'source_task','review_task','author','reviewer','manifest_sha256','volume'}:
        raise ValueError('exact independent delivery reference required')
    selected=binding.lookup(b,issue,delivery['source_task'])
    if selected is None:return None
    configuration=worker.selection(b,issue,delivery['source_task'])
    red=worker.red_reference(b,delivery['source_task'])
    with b.db() as con:
        state=ledger.load(con,selected['plan_key'])
        row=con.execute('SELECT source_task_id,reviewer_agent_id,manifest_sha256,status FROM reviews WHERE review_task_id=?',
                        (delivery['review_task'],)).fetchone()
        snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(delivery['source_task'],)).fetchone()
        tdd_row=con.execute('SELECT receipt FROM delivery_tdd WHERE task_id=?',(delivery['source_task'],)).fetchone()
    if (not row or tuple(row)!=(delivery['source_task'],delivery['reviewer'],delivery['manifest_sha256'],'approved')
            or not snapshot or tuple(snapshot)!=(delivery['volume'],'complete')
            or delivery['author']!=selected['author'] or delivery['reviewer']==delivery['author']
            or not tdd_row):raise ValueError('exact independent approved scope delivery required')
    fx=effects or execution.NativeEffects(b)
    review_task=None
    for role,key in (('author','source_task'),('reviewer','review_task')):
        task=fx.task(delivery[key],delivery[role])
        if (task.get('id')!=delivery[key] or task.get('agent_id')!=delivery[role]
                or task.get('issue_id')!=issue or task.get('status')!='completed'):
            raise ValueError('completed exact native delivery and review required')
        if role=='reviewer':review_task=task
    read_paths={'/delivery/'+p.removeprefix('/workspace/') for p in configuration['editable_paths']}
    read_paths.update('/delivery/'+p for p in selected['frozen_test_sha256'])
    reads=fx.delivery_reads(review_task)
    if (not read_paths or any(type(reads.get(path,{}).get('lines')) is not int
            or reads[path]['lines']<=0 or reads[path]['lines']!=reads[path].get('total_lines')
            for path in read_paths)):
        raise ValueError('complete independent scoped code and frozen test inspection required')
    volume=b.docker('GET','/volumes/'+delivery['volume'])
    if (not volume or volume.get('Name')!=delivery['volume'] or volume.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER
            or volume.get('Labels',{}).get('delivery-kit.source-task')!=delivery['source_task']):
        raise ValueError('owned immutable reviewed delivery volume required')
    tdd=json.loads(tdd_row[0]);green=tdd.get('green') or {};bridge=tdd.get('scope_transition') or {}
    expected=dict(operation='qualified_scope_tdd_transition_v1',plan_key=selected['plan_key'],
        author=selected['author'],implementation_task=delivery['source_task'],
        original_base_manifest_sha256=selected['original_base_manifest_sha256'],
        revised_base_manifest_sha256=selected['manifest_sha256'],revised_contract_sha256=selected['contract_sha256'],
        verification_output_sha256=selected['verification_output_sha256'],delivery_manifest_sha256=delivery['manifest_sha256'],
        **configuration['provenance'],frozen_test_sha256=selected['frozen_test_sha256'],
        baseline_test_sha256=red['red'].get('baseline_test_sha256'),delivery_approval=False)
    original=b.issue_base(issue)
    if (bridge!=expected or bridge.get('delivery_approval') is not False
            or bridge.get('historical_red_recreated') is not False
            or tdd.get('mode')!='controller_test_first' or tdd.get('red')!=red['red']
            or tdd.get('test_task')!=red['task_id'] or tdd.get('implementation_task')!=delivery['source_task']
            or green.get('manifest_sha256')!=delivery['manifest_sha256'] or green.get('executed_by_controller') is not True
            or type(green.get('tests')) is not int or green['tests']<red['red']['test_count']
            or original['base_sha']!=selected['base_sha']
            or original['manifest_sha256']!=selected['original_base_manifest_sha256']):
        raise ValueError('unchanged scope TDD transition and original Git base required')
    return dict(operation='qualified_product_scope_delivery_v1',issue_id=issue,delivery=delivery,
        plan_key=selected['plan_key'],base_sha=selected['base_sha'],original_contract_sha256=state['context']['contract_sha256'],
        effective_contract_sha256=selected['contract_sha256'],contract=selected['contract'],
        scope_tdd_sha256=ledger.policy.digest(tdd),release_homologated=False)
