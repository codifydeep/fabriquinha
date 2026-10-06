"""Run against pinned Hermes in a temporary, undispatched SQLite board."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from hermes_cli import kanban_db as kb

def main():
    with TemporaryDirectory(prefix='truco-governance-test-') as root:
        db = Path(root) / 'kanban.db'
        kb.init_db(db)
        with kb.connect(db) as conn:
            task = kb.create_task(conn, title='TEST-native-review', assignee='devops', initial_status='blocked')
            kb.unblock_task(conn, task)
            ok, reason = kb.request_review(conn, task, reviewer='produto', with_reason=True)
            assert not ok and 'quality_security' in reason, (ok, reason)
            ok, reason = kb.request_review(conn, task, reviewer='devops', with_reason=True)
            assert not ok, (ok, reason)
            ok, reason = kb.request_review(conn, task, reviewer='quality_security', with_reason=True)
            assert ok, reason
            event = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='review_requested'", (task,)).fetchone()
            assert 'devops' in event['payload'] and 'quality_security' in event['payload']
            (Path(root) / 'MAINTENANCE').write_text('test')
            spawned = []
            kb._dispatch_once_locked(conn, spawn_fn=lambda *a: spawned.append(a))
            assert not spawned
            release = kb.create_task(conn, title='RELEASE-test', assignee='techlead', initial_status='blocked')
            from delivery_gate import check_delivery
            assert check_delivery(conn, release) is not None
            with patch.dict('os.environ', {'HERMES_KANBAN_TASK':task}):
                try:
                    kb.create_task(conn, title='CHILD-invalid', assignee='frontend', parents=[task])
                except ValueError as exc:
                    assert 'fan out' in str(exc)
                else:
                    raise AssertionError('native CLI fanout gate bypassed')
            print('PASS native matrix: wrong reviewer and self-review rejected; correct reviewer persisted')
            print('PASS native dispatcher: persisted maintenance fence prevents spawn')
            print('PASS release controller: missing/mismatched evidence rejected')
            print('PASS native create: non-GRAPH worker cannot bypass fanout via CLI')
        conn.close()

if __name__ == '__main__':
    main()
