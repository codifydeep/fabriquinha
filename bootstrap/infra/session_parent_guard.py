"""Repair only a provably owned gateway session before transcript append."""


def ensure_session_parent(store, session_id, db):
    if db.get_session(session_id) is not None:
        return
    with store._lock:
        matches = [entry for entry in store._entries.values() if entry.session_id == session_id]
        if len(matches) != 1 or not matches[0].origin:
            raise RuntimeError('missing session parent without unique routing owner; defer append')
        entry = matches[0]
        if store._db_for_key(entry.session_key) is not db:
            raise RuntimeError('session owner differs from transcript store; defer append')
        store._record_gateway_session_peer(session_id, entry.session_key, entry.origin,
                                           display_name=entry.display_name)
    if db.get_session(session_id) is None:
        raise RuntimeError('session parent repair failed; defer append')
