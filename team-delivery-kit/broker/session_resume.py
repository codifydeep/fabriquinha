"""Preserve conversation only within one native execution, not across handoffs."""


def prior_session(con, scope, task_id):
    row = con.execute(
        'SELECT s.session_id FROM acp_sessions s WHERE s.scope=? AND EXISTS ('
        'SELECT 1 FROM acp_events e JOIN native_bindings n USING(request_id) '
        'WHERE e.session_id=s.session_id AND n.scope=s.scope AND n.task_id=?) '
        'ORDER BY s.rowid DESC LIMIT 1', (scope, task_id)).fetchone()
    return row[0] if row else None
