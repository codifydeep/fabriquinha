"""Operator-only reversible route isolation during a proved sealed maintenance.

Pausing a historical route is not cancellation, delivery or permission to replay
an effect. Original contracts and all task evidence remain in persistent state.
There is no worker-facing endpoint and no automatic restoration.
"""
import json
import uuid
try:import controller_maintenance as maintenance
except ImportError:from broker import controller_maintenance as maintenance


def isolate(b,issue,operation):
    if str(uuid.UUID(issue))!=issue or str(uuid.UUID(operation))!=operation:
        raise ValueError('exact operator isolation identities required')
    if maintenance.native_active(b):raise ValueError('native work must be idle before route isolation')
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        barrier=maintenance.current(con)
        if not barrier or barrier['stage']!='sealed' or barrier['operation_id']!=operation or barrier['namespace']!=b.PREFIX:
            raise ValueError('exact sealed operator maintenance required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing','active')").fetchone():
            raise ValueError('active leases prevent isolation')
        con.execute('CREATE TABLE IF NOT EXISTS controller_route_isolations('
            'operation_id TEXT PRIMARY KEY,issue_id TEXT,original TEXT,receipt TEXT)')
        rows=con.execute('SELECT issue_id,config FROM delivery_routes').fetchall()
        routes={r[0]:json.loads(r[1]) for r in rows}
        prior=con.execute('SELECT issue_id,original,receipt FROM controller_route_isolations WHERE operation_id=?',(operation,)).fetchone()
        if prior:
            if prior[0]!=issue:raise ValueError('isolation target drift')
            original=json.loads(prior[1]);receipt=json.loads(prior[2])
            expected={key:value if key==issue else {**value,'enabled':False} for key,value in original.items()}
            if routes!=expected:raise ValueError('isolated routes drift; no replay')
            return receipt
        if issue not in routes or routes[issue].get('enabled') is not True:
            raise ValueError('registered enabled target required')
        if any(type(value.get('enabled')) is not bool for value in routes.values()):
            raise ValueError('route enablement must be explicit')
        receipt=dict(operation_id=operation,active_issue=issue,paused=sum(
            value['enabled'] for key,value in routes.items() if key!=issue),
            delivery_approval=False,author_restarted=False,history_preserved=True)
        con.execute('INSERT INTO controller_route_isolations VALUES(?,?,?,?)',
            (operation,issue,json.dumps(routes,sort_keys=True),json.dumps(receipt,sort_keys=True)))
        for key,value in routes.items():
            if key!=issue and value['enabled']:
                con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',
                    (json.dumps({**value,'enabled':False},sort_keys=True),key))
        return receipt
