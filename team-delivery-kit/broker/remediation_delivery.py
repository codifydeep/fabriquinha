"""Read-only R2 delivery qualification. Not merge or homologation authority."""
import json
import re
try:
    import remediation_red_reference as references
    from technical_remediation_plan import digest
except ImportError:
    from broker import remediation_red_reference as references
    from broker.technical_remediation_plan import digest


def qualified(b, issue, delivery):
    """Revalidate an approved_submission against real R1 and closed R2 records.

    This proof is a point-in-time prerequisite for the existing portable driver,
    not a substitute for its native run, GitHub, CI or deployment checks. Call
    again before consequential transitions; a cached proof grants no authority.
    No Red receipts, board states, routes or leases are written here.
    """
    with b.LOCK:
        return _qualified(b,issue,delivery)


def _qualified(b,issue,delivery):
    reference=references.qualified(b,issue)
    keys={'source_task','review_task','author','reviewer','manifest_sha256','volume'}
    if (not reference or not isinstance(delivery,dict) or set(delivery)!=keys
            or any(not isinstance(v,str) or not v for v in delivery.values())
            or not re.fullmatch('[0-9a-f]{64}',delivery['manifest_sha256'])):
        raise ValueError('exact approved R2 submission and real R1 reference required')
    source=delivery['source_task']; reviewer=delivery['review_task']
    with b.db() as con:
        route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        route=json.loads(route_row[0]) if route_row else {}
        handoff=con.execute('SELECT source_task,stage FROM delivery_handoffs WHERE issue_id=? '
            'ORDER BY updated DESC,rowid DESC LIMIT 1',(issue,)).fetchone()
        snapshots=list(con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)))
        reviews=list(con.execute('SELECT source_task_id,manifest_sha256,status,reviewer_agent_id FROM reviews '
            'WHERE review_task_id=?',(reviewer,)))
        bindings=list(con.execute('SELECT n.issue_id,n.agent_id,g.mode,l.status FROM native_bindings n '
            'JOIN grants g USING(request_id) JOIN leases l USING(request_id) WHERE n.task_id=?',(reviewer,)))
        receipts=list(con.execute('SELECT receipt FROM delivery_tdd WHERE task_id=?',(source,)))
    if (route.get('enabled') is not True or route.get('author')!=delivery['author']
            or route.get('reviewer')!=delivery['reviewer'] or delivery['author']!=reference['author']
            or delivery['author']==delivery['reviewer'] or reviewer==source
            or not handoff or tuple(handoff)!=(source,'approved')
            or len(snapshots)!=1 or tuple(snapshots[0])!=(delivery['volume'],'complete')
            or len(reviews)!=1 or tuple(reviews[0])!=(source,delivery['manifest_sha256'],'approved',delivery['reviewer'])
            or len(bindings)!=1 or tuple(bindings[0])!=(issue,delivery['reviewer'],'review','closed')
            or len(receipts)!=1):
        raise ValueError('latest exact independent approved immutable R2 delivery required')
    origin=references.task_red(b,source)
    receipt=json.loads(receipts[0][0]); green=receipt.get('green',{})
    count=green.get('tests'); red=reference['red']
    if (origin!=red or receipt.get('mode')!='controller_test_first'
            or receipt.get('red')!=red['red'] or receipt.get('test_task')!=red['task_id']
            or receipt.get('implementation_task')!=source
            or receipt.get('red_origin_issue')!=red['issue_id']
            or receipt.get('red_origin_scope')!=red['scope']
            or source==red['task_id'] or issue==red['issue_id']
            or green.get('manifest_sha256')!=delivery['manifest_sha256']
            or green.get('executed_by_controller') is not True
            or type(count) is not int or count < red['red']['test_count']):
        raise ValueError('full controller Green and unchanged original R1 Red required')
    return dict(operation='qualified_remediation_r2_delivery_v1',issue_id=issue,
        source_task=reference['source_task'],run_id=reference['run_id'],
        execution_contract_sha256=reference['execution_contract_sha256'],
        r1_gate_sha256=reference['r1_gate_sha256'],reference_sha256=digest(reference),
        delivery=dict(delivery),tdd_sha256=digest(receipt),
        red_origin_issue=red['issue_id'],red_origin_task=red['task_id'],
        original_depth=reference['original_depth'],release_homologated=False)
