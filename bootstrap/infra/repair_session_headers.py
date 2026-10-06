"""Restore missing session parents from each profile's own routing metadata.

No cross-profile copies, transcript deletion, or synthetic chat messages.
"""
import json
import sqlite3
import time
from pathlib import Path
from hermes_state import SessionDB

PROFILES = ('produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security')

def main():
    backup = Path('/opt/data/observability') / ('session-header-repair-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700, parents=True)
    for profile in PROFILES:
        root = Path('/opt/data/profiles') / profile
        index = root / 'sessions/sessions.json'
        db_path = root / 'state.db'
        if not index.exists() or not db_path.exists():
            continue
        entries = json.loads(index.read_text())
        db = SessionDB(db_path=db_path)
        try:
            missing = [(key, entry) for key, entry in entries.items() if isinstance(entry, dict)
                       and entry.get('session_id') and entry.get('platform') == 'telegram'
                       and (entry.get('origin') or {}).get('chat_id') == '-5584379349'
                       and db.get_session(entry['session_id']) is None]
            if not missing:
                print(profile + ': no missing session headers')
                continue
            with sqlite3.connect(db_path) as src, sqlite3.connect(backup / (profile + '.db')) as dst:
                src.backup(dst)
            src.close()
            dst.close()
            for key, entry in missing:
                origin = entry['origin']
                db.record_gateway_session_peer(entry['session_id'], source='telegram',
                    session_key=key, chat_id=origin['chat_id'], chat_type=entry['chat_type'],
                    user_id=origin.get('user_id'), thread_id=origin.get('thread_id'),
                    display_name=entry.get('display_name'), origin_json=json.dumps(origin))
                assert db.get_session(entry['session_id']) is not None
            print(profile + ': restored ' + str(len(missing)) + ' routing header(s), transcripts preserved')
        finally:
            db.close()
    print('Backup:', backup)

if __name__ == '__main__':
    main()
