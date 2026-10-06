import importlib.util
import signal
import sqlite3
import tempfile
import unittest
from subprocess import CompletedProcess
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "kanban_watchdog.py"
SPEC = importlib.util.spec_from_file_location("kanban_watchdog", MODULE_PATH)
watchdog = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(watchdog)


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    unittest.addModuleCleanup(conn.close)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            assignee TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            workspace_path TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            max_runtime_seconds INTEGER,
            last_heartbeat_at INTEGER,
            current_run_id INTEGER
            ,worker_pid INTEGER,
            created_by TEXT,
            idempotency_key TEXT,
            last_failure_error TEXT
        );
        CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY,
            task_id TEXT NOT NULL,
            profile TEXT,
            status TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            outcome TEXT,
            error TEXT
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY,
            task_id TEXT NOT NULL,
            run_id INTEGER,
            kind TEXT NOT NULL,
            payload TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE kanban_notify_subs (
            task_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            thread_id TEXT NOT NULL DEFAULT '',
            user_id TEXT,
            user_id_alt TEXT,
            chat_type TEXT,
            notifier_profile TEXT,
            delivery_mode TEXT NOT NULL DEFAULT 'notify',
            delivery_metadata TEXT,
            created_at INTEGER NOT NULL,
            last_event_id INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (task_id, platform, chat_id, thread_id)
        );
        """
    )
    return conn


class WatchdogTests(unittest.TestCase):
    def test_run_cycle_closes_database_connection(self):
        class TrackingConnection(sqlite3.Connection):
            closed = False

            def close(self):
                self.closed = True
                super().close()

        conn = sqlite3.connect(":memory:", factory=TrackingConnection)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, assignee TEXT,
                status TEXT NOT NULL, created_at INTEGER NOT NULL,
                started_at INTEGER, completed_at INTEGER, workspace_path TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                max_runtime_seconds INTEGER, last_heartbeat_at INTEGER,
                current_run_id INTEGER
                ,worker_pid INTEGER
            );
            CREATE TABLE task_runs (
                id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, profile TEXT,
                status TEXT NOT NULL, started_at INTEGER NOT NULL,
                ended_at INTEGER, outcome TEXT, error TEXT
            );
            CREATE TABLE task_events (
                id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, run_id INTEGER,
                kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL
            );
            CREATE TABLE kanban_notify_subs (
                task_id TEXT NOT NULL, platform TEXT NOT NULL, chat_id TEXT NOT NULL,
                thread_id TEXT NOT NULL DEFAULT '', user_id TEXT, user_id_alt TEXT,
                chat_type TEXT, notifier_profile TEXT, delivery_mode TEXT NOT NULL,
                delivery_metadata TEXT, created_at INTEGER NOT NULL,
                last_event_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (task_id, platform, chat_id, thread_id)
            );
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            config = {
                "db_path": Path(directory) / "unused.db",
                "state_path": Path(directory) / "state.json",
                "chat_id": "-123",
                "notifier_profile": "techlead",
                "heartbeat_stale_seconds": 180,
                "runtime_warn_seconds": 2700,
                "ready_stale_seconds": 1200,
                "semantic_stall_seconds": 1200,
                "repeat_seconds": 1800,
                "digest_seconds": 1800,
                "token": "not-used",
                "activity_enabled": False,
                "reap_orphans_enabled": False,
            }
            with (
                patch.object(watchdog, "connect_database", return_value=conn),
                patch.object(watchdog, "detect_process_anomalies", return_value=[]),
                patch.object(watchdog, "send_telegram"),
            ):
                result = watchdog.run_cycle(config, {})

        self.assertTrue(conn.closed)
        self.assertEqual(result["active_alerts"], 0)
        self.assertEqual(result["notifications_sent"], 1)
        self.assertTrue(result["digest_sent"])

    def test_activity_events_use_run_profile_and_distinguish_review(self):
        import json
        conn = make_db()
        conn.execute('ALTER TABLE task_runs ADD COLUMN metadata TEXT')
        conn.execute(
            "INSERT INTO tasks(id,title,assignee,status,created_at,current_run_id) VALUES(?,?,?,?,?,?)",
            ("t_work", "Feature", "techlead", "running", 1, 2),
        )
        conn.executemany(
            "INSERT INTO task_runs(id,task_id,profile,status,started_at) VALUES(?,?,?,?,?)",
            [
                (1, "t_work", "produto", "review_requested", 10),
                (2, "t_work", "techlead", "running", 20),
            ],
        )
        conn.executemany(
            "INSERT INTO task_events(id,task_id,run_id,kind,payload,created_at) VALUES(?,?,?,?,?,?)",
            [
                (1, "t_work", 1, "review_requested", '{"reviewer":"techlead"}', 11),
                (2, "t_work", 2, "claimed", '{"source_status":"review"}', 20),
                (3, "t_work", 2, "changes_requested", '{}', 30),
            ],
        )

        conn.execute('UPDATE task_runs SET outcome=?,metadata=? WHERE id=1',('review_requested',json.dumps({'immutable_delivery':{'revision':'abc123def456789'}})))
        events = watchdog.collect_activity_events(conn, after_event_id=0)

        self.assertEqual([event["profile"] for event in events], ["produto", "techlead", "techlead"])
        self.assertIn("encaminhei para revisão", events[0]["text"])
        self.assertIn("Iniciei a revisão", events[1]["text"])
        self.assertIn("solicitei mudanças", events[2]["text"])
        self.assertIn('abc123def456',events[1]['text'])

    def test_ensure_subscriptions_adds_unarchived_cards_at_current_cursor(self):
        conn = make_db()
        conn.executemany(
            "INSERT INTO tasks(id,title,status,created_at) VALUES(?,?,?,?)",
            [
                ("t_active", "Active", "running", 10),
                ("t_done", "Done", "done", 10),
                ("t_old", "Old", "archived", 10),
            ],
        )
        conn.executemany(
            "INSERT INTO task_events(id,task_id,kind,created_at) VALUES(?,?,?,?)",
            [(3, "t_active", "heartbeat", 20), (7, "t_done", "completed", 30)],
        )

        added = watchdog.ensure_subscriptions(
            conn, chat_id="-123", notifier_profile="techlead", now=100
        )

        self.assertEqual(added, 2)
        rows = conn.execute(
            "SELECT task_id,last_event_id FROM kanban_notify_subs ORDER BY task_id"
        ).fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [("t_active", 3), ("t_done", 7)])

    def test_gave_up_creates_one_idempotent_recovery_card(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,last_failure_error
            ) VALUES(?,?,?,?,?,?)""",
            ("t_failed", "Backend", "backend_data", "blocked", 10, "timeout"),
        )
        conn.execute(
            "INSERT INTO task_events(id,task_id,kind,created_at) VALUES(?,?,?,?)",
            (9, "t_failed", "gave_up", 20),
        )
        completed = CompletedProcess(
            args=[], returncode=0, stdout='{"id":"t_recovery"}', stderr=""
        )

        with patch.object(watchdog.subprocess, "run", return_value=completed) as run:
            created = watchdog.ensure_failure_recovery_task(
                conn, board="truco-online", project_id="p_1", now=30
            )

        self.assertEqual(
            created,
            [{"source_task_id": "t_failed", "recovery_task_id": "t_recovery"}],
        )
        command = run.call_args.args[0]
        self.assertIn("watchdog-recovery:t_failed:9", command)
        self.assertIn("RECOVERY-t_failed — Diagnosticar e replanejar falha", command)

    def test_release_gave_up_does_not_recurse_into_recovery(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,last_failure_error
            ) VALUES(?,?,?,?,?,?)""",
            ("t_release", "RELEASE-v0.1", "techlead", "blocked", 10, "timeout"),
        )
        conn.execute(
            "INSERT INTO task_events(id,task_id,kind,created_at) VALUES(?,?,?,?)",
            (9, "t_release", "gave_up", 20),
        )

        with patch.object(watchdog.subprocess, "run") as run:
            created = watchdog.ensure_failure_recovery_task(
                conn, board="truco-online", project_id="p_1", now=30
            )

        self.assertEqual(created, [])
        run.assert_not_called()

    def test_detects_stale_heartbeat_duplicate_worker_and_repeated_failures(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,started_at,
                consecutive_failures,last_heartbeat_at,current_run_id
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("t_bad", "Bad task", "cto", "running", 1, 100, 2, 700, 2),
        )
        conn.executemany(
            "INSERT INTO task_runs(id,task_id,profile,status,started_at) VALUES(?,?,?,?,?)",
            [(1, "t_bad", "cto", "running", 100), (2, "t_bad", "cto", "running", 200)],
        )

        alerts = watchdog.detect_database_anomalies(
            conn, now=1000, heartbeat_stale_seconds=180, runtime_warn_seconds=600
        )
        kinds = {alert["kind"] for alert in alerts}

        self.assertEqual(kinds, {"duplicate_workers", "stale_heartbeat", "runtime", "failures"})

    def test_detects_stranded_ready_and_repeated_respawn_guard(self):
        conn = make_db()
        conn.execute(
            "INSERT INTO tasks(id,title,assignee,status,created_at) VALUES(?,?,?,?,?)",
            ("t_stuck", "Stuck", "cto", "ready", 100),
        )
        conn.executemany(
            "INSERT INTO task_events(id,task_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
            [
                (1, "t_stuck", "respawn_guarded", '{"reason":"active_pr"}', 850),
                (2, "t_stuck", "respawn_guarded", '{"reason":"active_pr"}', 900),
                (3, "t_stuck", "respawn_guarded", '{"reason":"active_pr"}', 950),
            ],
        )

        alerts = watchdog.detect_database_anomalies(
            conn,
            now=1000,
            heartbeat_stale_seconds=180,
            runtime_warn_seconds=600,
            ready_stale_seconds=600,
        )

        self.assertEqual(
            {alert["kind"] for alert in alerts},
            {"ready_stalled", "respawn_loop"},
        )

    def test_ready_waiting_at_full_capacity_is_not_stalled(self):
        conn = make_db()
        conn.executemany(
            "INSERT INTO tasks(id,title,assignee,status,created_at) VALUES(?,?,?,?,?)",
            [
                ("t_waiting", "Waiting", "devops", "ready", 100),
                ("t_run_a", "Running A", "backend_data", "running", 100),
                ("t_run_b", "Running B", "frontend", "running", 100),
            ],
        )

        alerts = watchdog.detect_database_anomalies(
            conn,
            now=1000,
            heartbeat_stale_seconds=2000,
            runtime_warn_seconds=2000,
            ready_stale_seconds=600,
            max_concurrent_tasks=2,
        )

        self.assertNotIn("ready_stalled", {alert["kind"] for alert in alerts})

    def test_runtime_uses_current_run_start_not_historic_task_start(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,started_at,
                last_heartbeat_at,current_run_id
            ) VALUES(?,?,?,?,?,?,?,?)""",
            ("t_retry", "Retry", "cto", "running", 1, 100, 950, 7),
        )
        conn.execute(
            "INSERT INTO task_runs(id,task_id,profile,status,started_at) VALUES(?,?,?,?,?)",
            (7, "t_retry", "cto", "running", 950),
        )

        alerts = watchdog.detect_database_anomalies(
            conn, now=1000, heartbeat_stale_seconds=180, runtime_warn_seconds=600
        )

        self.assertNotIn("runtime", {alert["kind"] for alert in alerts})

    def test_review_run_is_not_flagged_for_unchanged_git(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,started_at,workspace_path,
                last_heartbeat_at,current_run_id
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("t_review", "Review", "techlead", "running", 1, 900, ".", 990, 8),
        )
        conn.execute(
            "INSERT INTO task_runs(id,task_id,profile,status,started_at) VALUES(?,?,?,?,?)",
            (8, "t_review", "techlead", "running", 900),
        )
        conn.execute(
            "INSERT INTO task_events(id,task_id,run_id,kind,payload,created_at) VALUES(?,?,?,?,?,?)",
            (1, "t_review", 8, "claimed", '{"source_status":"review"}', 900),
        )
        state = {"workspace_fingerprints": {"t_review": {"fingerprint": "x", "since": 1}}}

        alerts = watchdog.detect_semantic_stalls(conn, state, now=1000, stall_seconds=10)

        self.assertEqual(alerts, [])
        self.assertEqual(state["workspace_fingerprints"], {})

    def test_semantic_stall_reclaims_running_worker_after_threshold(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,started_at,workspace_path,
                last_heartbeat_at,current_run_id
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("t_stuck", "Stuck", "frontend", "running", 1, 100, ".", 995, 9),
        )
        conn.execute(
            "INSERT INTO task_runs(id,task_id,profile,status,started_at) VALUES(?,?,?,?,?)",
            (9, "t_stuck", "frontend", "running", 100),
        )
        conn.execute(
            "INSERT INTO task_events(id,task_id,run_id,kind,payload,created_at) VALUES(?,?,?,?,?,?)",
            (1, "t_stuck", 9, "claimed", '{"source_status":"ready"}', 100),
        )
        state = {
            "workspace_fingerprints": {
                "t_stuck": {"fingerprint": "same", "since": 100}
            }
        }

        with patch.object(
            watchdog.subprocess,
            "run",
            return_value=CompletedProcess([], 0, "Reclaimed", ""),
        ) as run:
            actions = watchdog.reclaim_semantic_stalls(
                conn,
                state,
                now=1000,
                reclaim_seconds=600,
                board="truco-online",
            )

        self.assertEqual(actions[0]["task_id"], "t_stuck")
        self.assertNotIn("t_stuck", state["workspace_fingerprints"])
        self.assertIn("reclaim", run.call_args.args[0])
        self.assertIn("t_stuck", run.call_args.args[0])

    def test_semantic_stall_never_reclaims_review(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,started_at,workspace_path,
                last_heartbeat_at,current_run_id
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("t_review", "Review", "cto", "running", 1, 100, ".", 995, 10),
        )
        conn.execute(
            "INSERT INTO task_runs(id,task_id,profile,status,started_at) VALUES(?,?,?,?,?)",
            (10, "t_review", "cto", "running", 100),
        )
        conn.execute(
            "INSERT INTO task_events(id,task_id,run_id,kind,payload,created_at) VALUES(?,?,?,?,?,?)",
            (1, "t_review", 10, "claimed", '{"source_status":"review"}', 100),
        )
        state = {
            "workspace_fingerprints": {
                "t_review": {"fingerprint": "same", "since": 100}
            }
        }

        with patch.object(watchdog.subprocess, "run") as run:
            actions = watchdog.reclaim_semantic_stalls(
                conn,
                state,
                now=1000,
                reclaim_seconds=600,
                board="truco-online",
            )

        self.assertEqual(actions, [])
        run.assert_not_called()
        self.assertNotIn("t_review", state["workspace_fingerprints"])

    def test_deduplicator_repeats_only_after_interval_and_reports_recovery(self):
        state = {"active_alerts": {}, "last_digest_at": 0}
        alerts = [{"key": "stale:t_1", "kind": "stale_heartbeat", "text": "stale"}]

        first, recovered = watchdog.select_notifications(state, alerts, now=100, repeat_seconds=300)
        second, _ = watchdog.select_notifications(state, alerts, now=200, repeat_seconds=300)
        third, _ = watchdog.select_notifications(state, alerts, now=401, repeat_seconds=300)
        none, recovered = watchdog.select_notifications(state, [], now=402, repeat_seconds=300)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(third), 1)
        self.assertEqual(none, [])
        self.assertEqual(recovered, ["stale:t_1"])

    def test_digest_summarizes_board(self):
        conn = make_db()
        conn.executemany(
            "INSERT INTO tasks(id,title,assignee,status,created_at) VALUES(?,?,?,?,?)",
            [
                ("t_1", "One", "produto", "running", 1),
                ("t_2", "Two", "techlead", "review", 1),
                ("t_3", "Three", "designer", "todo", 1),
                ("t_4", "Old", "cto", "archived", 1),
            ],
        )

        text = watchdog.build_digest(conn)

        self.assertIn("running=1", text)
        self.assertIn("review=1", text)
        self.assertIn("todo=1", text)
        self.assertNotIn("archived", text)

    def test_scan_worker_processes_groups_same_task(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            for pid in ("101", "202"):
                child = proc / pid
                child.mkdir()
                (child / "cmdline").write_bytes(
                    b"python\0hermes\0-p\0techlead\0chat\0-q\0work kanban task t_deadbeef\0"
                )
            unrelated = proc / "303"
            unrelated.mkdir()
            (unrelated / "cmdline").write_bytes(b"python\0other.py\0")

            workers = watchdog.scan_worker_processes(proc)

        self.assertEqual(workers, {"t_deadbeef": [101, 202]})

    def test_reaper_terminates_only_noncanonical_worker_after_grace(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO tasks(
                id,title,assignee,status,created_at,current_run_id,worker_pid
            ) VALUES(?,?,?,?,?,?,?)""",
            ("t_deadbeef", "Review", "techlead", "running", 1, 2, 202),
        )
        conn.execute(
            "INSERT INTO task_runs(id,task_id,profile,status,started_at) VALUES(?,?,?,?,?)",
            (2, "t_deadbeef", "techlead", "running", 10),
        )
        state = {}
        signals = []
        with (
            patch.object(watchdog, "scan_worker_processes", return_value={"t_deadbeef": [101, 202]}),
            patch.object(watchdog, "process_matches_task", return_value=True),
        ):
            first = watchdog.reap_orphan_workers(
                conn, state, now=100, grace_seconds=180, kill_grace_seconds=60,
                signal_process=lambda pid, sig: signals.append((pid, sig)),
            )
            second = watchdog.reap_orphan_workers(
                conn, state, now=281, grace_seconds=180, kill_grace_seconds=60,
                signal_process=lambda pid, sig: signals.append((pid, sig)),
            )

        self.assertEqual(first, [])
        self.assertEqual(second, [{"task_id": "t_deadbeef", "pid": 101, "signal": "SIGTERM"}])
        self.assertEqual(signals, [(101, signal.SIGTERM)])
        self.assertNotIn("t_deadbeef:202", state["orphan_workers"])

    def test_reaper_escalates_persistent_orphan_to_sigkill(self):
        conn = make_db()
        state = {"orphan_workers": {"t_deadbeef:101": {"first_seen": 1, "term_sent_at": 100}}}
        signals = []
        with (
            patch.object(watchdog, "scan_worker_processes", return_value={"t_deadbeef": [101]}),
            patch.object(watchdog, "process_matches_task", return_value=True),
        ):
            actions = watchdog.reap_orphan_workers(
                conn, state, now=161, grace_seconds=180, kill_grace_seconds=60,
                signal_process=lambda pid, sig: signals.append((pid, sig)),
            )

        self.assertEqual(actions, [{"task_id": "t_deadbeef", "pid": 101, "signal": "SIGKILL"}])
        self.assertEqual(signals, [(101, signal.SIGKILL)])


if __name__ == "__main__":
    unittest.main()
