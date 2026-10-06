"""Real SQLite transcript repair and restart test, isolated from live profiles."""
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from hermes_state import SessionDB
from session_parent_guard import ensure_session_parent

with tempfile.TemporaryDirectory(prefix='session-parent-test-') as tmp:
    path = Path(tmp) / 'state.db'
    db = SessionDB(db_path=path)
    entry = SimpleNamespace(session_id='test-owned-session',session_key='agent:produto:telegram:group:test',
                            origin=object(),display_name='isolated fixture')
    def record(sid, key, origin, **kwargs):
        db.record_gateway_session_peer(sid,source='telegram',session_key=key,
            chat_id='test-only',chat_type='group',origin_json=json.dumps({'chat_id':'test-only'}))
    store = SimpleNamespace(_lock=threading.RLock(),_entries={entry.session_key:entry},
                            _db_for_key=lambda _:db,_record_gateway_session_peer=record)
    assert db.get_session(entry.session_id) is None
    ensure_session_parent(store,entry.session_id,db)
    db.append_message(entry.session_id,role='user',content='observed fixture',observed=True,platform_message_id='fixture-1')
    db.close()
    db = SessionDB(db_path=path)
    ensure_session_parent(store,entry.session_id,db)
    messages = db.get_messages(entry.session_id)
    assert len(messages) == 1 and messages[0]['content'] == 'observed fixture', messages
    db.close()
    print('PASS: missing parent repaired from own routing metadata; observed message survives reopen')
