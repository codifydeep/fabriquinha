#!/usr/bin/env python3
"""Deterministic Kanban/Telegram observability for the local Hermes PoC."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any


ACTIVE_STATUSES = ("triage", "todo", "ready", "running", "review", "blocked", "scheduled", "done")
TASK_ID_RE = re.compile(r"\bwork kanban task (t_[0-9a-f]+)\b")
PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ACTIVITY_EVENT_KINDS = (
    "claimed",
    "review_requested",
    "completed",
    "changes_requested",
    "blocked",
    "reclaimed",
    "timed_out",
    "crashed",
)


def connect_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_subscriptions(
    conn: sqlite3.Connection,
    *,
    chat_id: str,
    notifier_profile: str,
    now: int,
) -> int:
    """Subscribe the group to future events of every non-archived card."""
    added = 0
    tasks = conn.execute(
        "SELECT id FROM tasks WHERE status <> 'archived' ORDER BY created_at"
    ).fetchall()
    with conn:
        for row in tasks:
            task_id = str(row["id"])
            cursor = conn.execute(
                "SELECT COALESCE(MAX(id), 0) FROM task_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO kanban_notify_subs(
                    task_id, platform, chat_id, thread_id, user_id, user_id_alt,
                    chat_type, notifier_profile, delivery_mode, delivery_metadata,
                    created_at, last_event_id
                ) VALUES(?, 'telegram', ?, '', NULL, NULL, 'group', ?, 'notify', NULL, ?, ?)
                """,
                (task_id, chat_id, notifier_profile, now, int(cursor or 0)),
            )
            added += int(cur.rowcount == 1)
    return added


def ensure_failure_recovery_task(
    conn: sqlite3.Connection,
    *,
    board: str,
    project_id: str,
    now: int,
    executable: str = "/opt/hermes/.venv/bin/hermes",
) -> list[dict[str, str]]:
    """Create at most one gated Tech Lead recovery card for a gave-up task.

    The dispatcher circuit breaker intentionally parks a task after repeated
    failures.  Without this bridge, a board can remain blocked forever while
    the watchdog merely reports the condition.  Recovery cards are idempotent
    per gave_up event and serialized: only one active automatic recovery may
    exist at a time. RELEASE controllers and recovery cards themselves never
    recurse into another automatic recovery.
    """
    existing = conn.execute(
        """
        SELECT 1 FROM tasks
         WHERE created_by='watchdog-recovery'
           AND status NOT IN ('done','archived')
         LIMIT 1
        """
    ).fetchone()
    if existing:
        return []

    candidates = conn.execute(
        """
        SELECT t.id,t.title,t.assignee,t.last_failure_error,e.id AS event_id
          FROM tasks t
          JOIN task_events e ON e.id=(
              SELECT MAX(e2.id) FROM task_events e2
               WHERE e2.task_id=t.id AND e2.kind='gave_up'
          )
         WHERE t.status='blocked'
           AND UPPER(t.title) NOT LIKE 'RELEASE-%'
           AND UPPER(t.title) NOT LIKE 'RECOVERY-%'
           AND NOT EXISTS (
               SELECT 1 FROM tasks r
                WHERE r.idempotency_key='watchdog-recovery:' || t.id || ':' || e.id
           )
         ORDER BY e.id
         LIMIT 1
        """
    ).fetchall()
    if not candidates:
        return []

    row = candidates[0]
    source_id = str(row["id"])
    event_id = int(row["event_id"])
    original_assignee = str(row["assignee"] or "sem responsável")
    error = str(row["last_failure_error"] or "falha repetida sem erro registrado")
    body = (
        f"Recuperação automática do card `{source_id}` ({original_assignee}).\n\n"
        f"Falha que abriu o circuito: `{error}`.\n\n"
        "Diagnostique o log, o worktree e a base origin/release/v0.1. Não implemente "
        "a feature neste card e não reutilize workspace_path. Preserve qualquer "
        "mudança válida. Registre hipótese, evidência e correção. Se for necessário "
        "um replacement, crie exatamente um card pequeno, com este RECOVERY como "
        "pai, assignee original, projeto herdado, TDD, runtime máximo de 2h e "
        "reviewer conforme a matriz. Escreva o relatório em docs/recovery, abra PR "
        "contra release/v0.1 e solicite revisão deste card ao CTO. Não crie RELEASE."
    )
    key = f"watchdog-recovery:{source_id}:{event_id}"
    cmd = [
        executable,
        "-p", "techlead",
        "kanban", "--board", board,
        "create", f"RECOVERY-{source_id} — Diagnosticar e replanejar falha",
        "--body", body,
        "--assignee", "techlead",
        "--workspace", "worktree",
        "--project", project_id,
        "--priority", "2000",
        "--max-runtime", "2h",
        "--max-retries", "2",
        "--created-by", "watchdog-recovery",
        "--idempotency-key", key,
        "--skill", "systematic-debugging",
        "--skill", "company-delivery-contract",
        "--skill", "github",
        "--json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"automatic recovery create failed for {source_id}: "
            f"{(result.stderr or result.stdout).strip()[:500]}"
        )
    payload = json.loads(result.stdout)
    return [{"source_task_id": source_id, "recovery_task_id": str(payload["id"])}]


def _alert(key: str, kind: str, text: str) -> dict[str, str]:
    return {"key": key, "kind": kind, "text": text}


def detect_database_anomalies(
    conn: sqlite3.Connection,
    *,
    now: int,
    heartbeat_stale_seconds: int,
    runtime_warn_seconds: int,
    ready_stale_seconds: int = 1200,
    max_concurrent_tasks: int | None = None,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    duplicate_rows = conn.execute(
        """
        SELECT task_id, COUNT(*) AS qty
          FROM task_runs
         WHERE status = 'running'
         GROUP BY task_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in duplicate_rows:
        task_id = str(row["task_id"])
        alerts.append(
            _alert(
                f"duplicate-db:{task_id}",
                "duplicate_workers",
                f"🚨 {task_id}: {row['qty']} runs simultâneos registrados no Kanban.",
            )
        )

    running = conn.execute(
        """
        SELECT t.id,t.title,t.assignee,
               COALESCE(r.started_at,t.started_at) AS run_started_at,
               t.last_heartbeat_at,t.consecutive_failures,t.max_runtime_seconds
          FROM tasks t
          LEFT JOIN task_runs r ON r.id=t.current_run_id
         WHERE t.status = 'running'
         ORDER BY run_started_at
        """
    ).fetchall()
    for row in running:
        task_id = str(row["id"])
        title = str(row["title"])
        assignee = str(row["assignee"] or "sem responsável")
        heartbeat = int(row["last_heartbeat_at"] or 0)
        started = int(row["run_started_at"] or now)
        elapsed = max(0, now - started)
        failures = int(row["consecutive_failures"] or 0)
        if heartbeat == 0 or now - heartbeat > heartbeat_stale_seconds:
            age = "ausente" if heartbeat == 0 else f"há {now - heartbeat}s"
            alerts.append(
                _alert(
                    f"stale:{task_id}",
                    "stale_heartbeat",
                    f"🚨 {task_id} ({assignee}) sem heartbeat recente: {age}. {title}",
                )
            )
        if elapsed >= runtime_warn_seconds:
            alerts.append(
                _alert(
                    f"runtime:{task_id}",
                    "runtime",
                    f"⚠️ {task_id} ({assignee}) está running há {elapsed // 60} min. {title}",
                )
            )
        if failures >= 2:
            alerts.append(
                _alert(
                    f"failures:{task_id}",
                    "failures",
                    f"🚨 {task_id} acumula {failures} falhas consecutivas e continua running.",
                )
            )

    running_count = int(
        conn.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]
    )
    queue_has_capacity = (
        max_concurrent_tasks is None or running_count < max_concurrent_tasks
    )
    ready = conn.execute(
        """
        SELECT t.id,t.title,t.assignee,t.created_at,
               COALESCE((
                   SELECT MAX(e.created_at) FROM task_events e
                    WHERE e.task_id=t.id
                      AND e.kind IN (
                          'created','status','promoted','unblocked','reclaimed',
                          'review_reopened','descendant_invalidated','assigned'
                      )
               ), t.created_at) AS ready_since
          FROM tasks t
         WHERE t.status='ready'
        """
    ).fetchall()
    for row in ready:
        task_id = str(row["id"])
        ready_for = max(0, now - int(row["ready_since"] or now))
        if queue_has_capacity and ready_for >= ready_stale_seconds:
            alerts.append(
                _alert(
                    f"ready-stalled:{task_id}",
                    "ready_stalled",
                    f"⚠️ {task_id} ({row['assignee']}) está ready sem worker há {ready_for // 60} min. {row['title']}",
                )
            )
        guarded = conn.execute(
            """
            SELECT payload FROM task_events
             WHERE task_id=? AND kind='respawn_guarded' AND created_at>=?
             ORDER BY id DESC
            """,
            (task_id, now - 300),
        ).fetchall()
        if len(guarded) >= 3:
            try:
                reason = json.loads(guarded[0]["payload"] or "{}").get("reason", "desconhecido")
            except (json.JSONDecodeError, AttributeError):
                reason = "desconhecido"
            alerts.append(
                _alert(
                    f"respawn-loop:{task_id}:{reason}",
                    "respawn_loop",
                    f"🚨 {task_id}: dispatcher recusou o respawn {len(guarded)} vezes em 5 min (motivo: {reason}).",
                )
            )
    return alerts


def scan_worker_processes(proc_root: Path = Path("/proc")) -> dict[str, list[int]]:
    workers: dict[str, list[int]] = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        match = TASK_ID_RE.search(command)
        if match:
            workers.setdefault(match.group(1), []).append(int(entry.name))
    return {task_id: sorted(pids) for task_id, pids in workers.items()}


def process_matches_task(pid: int, task_id: str, proc_root: Path = Path("/proc")) -> bool:
    """Revalidate a PID immediately before signalling it to avoid PID-reuse races."""
    try:
        command = (proc_root / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        )
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return False
    match = TASK_ID_RE.search(command)
    return bool(match and match.group(1) == task_id)


def reap_orphan_workers(
    conn: sqlite3.Connection,
    state: dict[str, Any],
    *,
    now: int,
    grace_seconds: int,
    kill_grace_seconds: int,
    proc_root: Path = Path("/proc"),
    signal_process: Any = os.kill,
) -> list[dict[str, Any]]:
    """Terminate workers whose PID is no longer the canonical active PID in Kanban."""
    canonical: dict[str, int] = {}
    rows = conn.execute(
        """
        SELECT t.id,t.status,t.worker_pid,r.status AS run_status
          FROM tasks t
          LEFT JOIN task_runs r ON r.id=t.current_run_id
         WHERE t.worker_pid IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        if row["status"] == "running" and row["run_status"] == "running":
            canonical[str(row["id"])] = int(row["worker_pid"])

    observed = scan_worker_processes(proc_root)
    tracked = state.setdefault("orphan_workers", {})
    present_keys: set[str] = set()
    actions: list[dict[str, Any]] = []

    for task_id, pids in observed.items():
        for pid in pids:
            key = f"{task_id}:{pid}"
            if canonical.get(task_id) == pid:
                tracked.pop(key, None)
                continue
            present_keys.add(key)
            record = tracked.setdefault(key, {"first_seen": now})
            term_sent_at = record.get("term_sent_at")
            if term_sent_at is None and now - int(record["first_seen"]) >= grace_seconds:
                if process_matches_task(pid, task_id, proc_root):
                    signal_process(pid, signal.SIGTERM)
                    record["term_sent_at"] = now
                    actions.append({"task_id": task_id, "pid": pid, "signal": "SIGTERM"})
                else:
                    tracked.pop(key, None)
            elif term_sent_at is not None and now - int(term_sent_at) >= kill_grace_seconds:
                if process_matches_task(pid, task_id, proc_root):
                    signal_process(pid, signal.SIGKILL)
                    record["kill_sent_at"] = now
                    actions.append({"task_id": task_id, "pid": pid, "signal": "SIGKILL"})
                else:
                    tracked.pop(key, None)

    for key in list(tracked):
        if key not in present_keys:
            tracked.pop(key, None)
    return actions


def workspace_fingerprint(path: str | None) -> str | None:
    if not path or not Path(path).is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", path, "status", "--porcelain=v1"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        head = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        diff = subprocess.run(['git', '-C', path, 'diff', 'HEAD', '--no-ext-diff', '--binary'],
                              capture_output=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    payload = f"{head.stdout.strip()}\n{result.stdout}".encode() + diff.stdout
    # New files are not present in git diff HEAD; metadata captures ongoing
    # edits without reading secrets or arbitrarily large generated files.
    for line in result.stdout.splitlines():
        if line.startswith('?? '):
            try:
                stat = (Path(path) / line[3:]).stat()
                payload += f'{stat.st_mtime_ns}:{stat.st_size}'.encode()
            except OSError:
                return None
    return hashlib.sha256(payload).hexdigest()


def detect_semantic_stalls(
    conn: sqlite3.Connection,
    state: dict[str, Any],
    *,
    now: int,
    stall_seconds: int,
) -> list[dict[str, str]]:
    tracked = state.setdefault("workspace_fingerprints", {})
    alerts: list[dict[str, str]] = []
    running = conn.execute(
        "SELECT id,title,assignee,workspace_path,current_run_id FROM tasks WHERE status = 'running'"
    ).fetchall()
    active_ids = {str(row["id"]) for row in running}
    for task_id in list(tracked):
        if task_id not in active_ids:
            tracked.pop(task_id, None)
    for row in running:
        task_id = str(row["id"])
        claimed = conn.execute(
            """
            SELECT payload FROM task_events
             WHERE task_id=? AND run_id=? AND kind='claimed'
             ORDER BY id DESC LIMIT 1
            """,
            (task_id, row["current_run_id"]),
        ).fetchone()
        try:
            source_status = json.loads(claimed["payload"] or "{}").get("source_status") if claimed else None
        except (json.JSONDecodeError, AttributeError):
            source_status = None
        # A reviewer normally does not modify the branch. Heartbeat and
        # runtime alerts still cover it; Git-fingerprint alerts would be a
        # permanent false positive for every legitimate review.
        if source_status == "review":
            tracked.pop(task_id, None)
            continue
        fingerprint = workspace_fingerprint(row["workspace_path"])
        if fingerprint is None:
            continue
        previous = tracked.get(task_id)
        if not previous or previous.get("fingerprint") != fingerprint or previous.get('run_id') != row['current_run_id']:
            tracked[task_id] = {"fingerprint": fingerprint, "since": now, 'run_id':row['current_run_id']}
            continue
        unchanged_for = now - int(previous.get("since", now))
        if unchanged_for >= stall_seconds:
            alerts.append(
                _alert(
                    f"semantic:{task_id}",
                    "semantic_stall",
                    f"⚠️ {task_id} ({row['assignee']}) está há {unchanged_for // 60} min sem mudança Git. Verifique o log: {row['title']}",
                )
            )
    return alerts


def reclaim_semantic_stalls(
    conn: sqlite3.Connection,
    state: dict[str, Any],
    *,
    now: int,
    reclaim_seconds: int,
    board: str,
    executable: str = "/opt/hermes/.venv/bin/hermes",
) -> list[dict[str, str]]:
    """Requeue live workers that make no durable Git progress.

    Heartbeats only prove that the wrapper process is alive. The fingerprint
    clock resets on every HEAD/index/worktree change. Review runs are excluded
    because a correct reviewer need not modify Git.
    """
    tracked = state.setdefault("workspace_fingerprints", {})
    reclaimed: list[dict[str, str]] = []
    for task_id, record in list(tracked.items()):
        unchanged_for = now - int(record.get("since", now))
        if unchanged_for < reclaim_seconds:
            continue
        row = conn.execute(
            """
            SELECT t.status,t.current_run_id,e.payload
              FROM tasks t
              LEFT JOIN task_events e ON e.id=(
                  SELECT MAX(e2.id) FROM task_events e2
                   WHERE e2.task_id=t.id AND e2.run_id=t.current_run_id
                     AND e2.kind='claimed'
              )
             WHERE t.id=?
            """,
            (task_id,),
        ).fetchone()
        if row is None or row["status"] != "running":
            tracked.pop(task_id, None)
            continue
        try:
            source_status = json.loads(row["payload"] or "{}").get("source_status")
        except (json.JSONDecodeError, AttributeError):
            source_status = None
        if source_status == "review":
            tracked.pop(task_id, None)
            continue
        budgets = state.setdefault('semantic_reclaim_budget', {})
        attempts = int(budgets.get(task_id, 0))
        reason = (
            f"Watchdog: {unchanged_for // 60} min sem mudança Git; "
            "requeue automático para romper loop sem progresso"
        )
        result = subprocess.run(
            [
                executable,
                "-p", "techlead",
                "kanban", "--board", board,
                "reclaim", task_id,
                "--reason", reason,
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"semantic-stall reclaim failed for {task_id}: "
                f"{(result.stderr or result.stdout).strip()[:500]}"
            )
        budgets[task_id] = attempts + 1
        if attempts >= 1:
            parked = subprocess.run([executable, '-p', 'techlead', 'kanban', '--board', board,
                'block', task_id, '--kind', 'needs_input', '--reason',
                'Impedimento técnico: dois reclaims sem progresso; Tech Lead/CTO deve diagnosticar causa e experimento antes de retomar. Não é decisão do CEO.'],
                capture_output=True, text=True, timeout=45)
            if parked.returncode:
                raise RuntimeError('could not park stalled task: ' + parked.stderr[:300])
        tracked.pop(task_id, None)
        reclaimed.append({"task_id": task_id, "reason": reason})
    return reclaimed


def detect_process_anomalies() -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    for task_id, pids in scan_worker_processes().items():
        if len(pids) > 1:
            alerts.append(
                _alert(
                    f"duplicate-proc:{task_id}",
                    "duplicate_workers",
                    f"🚨 {task_id}: {len(pids)} processos worker simultâneos (PIDs {', '.join(map(str, pids))}).",
                )
            )
    return alerts


def select_notifications(
    state: dict[str, Any],
    alerts: list[dict[str, str]],
    *,
    now: int,
    repeat_seconds: int,
) -> tuple[list[dict[str, str]], list[str]]:
    active = state.setdefault("active_alerts", {})
    current = {alert["key"]: alert for alert in alerts}
    selected: list[dict[str, str]] = []
    for key, alert in current.items():
        previous = active.get(key, {})
        if not previous or now - int(previous.get("last_sent", 0)) >= repeat_seconds:
            selected.append(alert)
            active[key] = {
                "kind": alert["kind"],
                "text": alert["text"],
                "last_sent": now,
            }
    recovered = sorted(set(active) - set(current))
    for key in recovered:
        active.pop(key, None)
    return selected, recovered


def build_digest(conn: sqlite3.Connection) -> str:
    counts = {
        str(row["status"]): int(row["qty"])
        for row in conn.execute(
            "SELECT status,COUNT(*) AS qty FROM tasks WHERE status <> 'archived' GROUP BY status"
        )
    }
    ordered = [
        f"{status}={counts[status]}"
        for status in ACTIVE_STATUSES
        if counts.get(status, 0)
    ]
    active = conn.execute(
        "SELECT id,assignee,status FROM tasks WHERE status IN ('running','review','blocked') ORDER BY created_at"
    ).fetchall()
    details = ", ".join(
        f"{row['id']}:{row['status']}@{row['assignee']}" for row in active
    ) or "nenhum card ativo"
    return "📊 Hermes Kanban: " + ", ".join(ordered) + ". Ativos: " + details


def load_token(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
            if token:
                return token
    raise RuntimeError(f"TELEGRAM_BOT_TOKEN ausente em {env_path}")


def send_telegram(token: str, chat_id: str, text: str) -> None:
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError("Telegram recusou a notificação")


def notify(config, token, chat_id, text, key=None):
    if not config.get('attempt'):
        return send_telegram(token, chat_id, text)
    from durable_notifications import enqueue
    profile = config['notifier_profile'] if token == config['token'] else next(
        (p for p, value in config.get('profile_token_cache', {}).items() if value == token), None)
    if profile is None or chat_id != config['chat_id']:
        raise ValueError('notification route is not registered')
    enqueue(config, profile, text, key)


def collect_activity_events(
    conn: sqlite3.Connection, *, after_event_id: int
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in ACTIVITY_EVENT_KINDS)
    rows = conn.execute(
        f"""
        SELECT e.id AS event_id,e.kind,e.payload,e.run_id,
               t.id AS task_id,t.title,t.assignee,r.profile
          FROM task_events e
          JOIN tasks t ON t.id=e.task_id
          LEFT JOIN task_runs r ON r.id=e.run_id
         WHERE e.id>? AND e.kind IN ({placeholders})
         ORDER BY e.id
        """,
        (after_event_id, *ACTIVITY_EVENT_KINDS),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        profile = str(row["profile"] or row["assignee"] or "techlead")
        kind = str(row["kind"])
        task = f"{row['task_id']} — {row['title']}"
        if kind == "claimed":
            if payload.get("source_status") == "review":
                text_value = f"🔎 Iniciei a revisão do card {task}."
            else:
                text_value = f"▶️ Iniciei a atividade do card {task}."
        elif kind == "review_requested":
            text_value = f"📤 Finalizei minha implementação do card {task} e encaminhei para revisão independente."
        elif kind == "completed":
            text_value = f"✅ Finalizei a atividade do card {task}."
        elif kind == "changes_requested":
            text_value = f"↩️ Finalizei a revisão do card {task}: solicitei mudanças ao implementador."
        elif kind == "blocked":
            text_value = f"⏸️ Encerrei a execução do card {task} como bloqueada; o motivo está registrado no Kanban."
        else:
            labels = {
                "reclaimed": "interrompida para recuperação",
                "timed_out": "encerrada por timeout",
                "crashed": "encerrada por falha",
            }
            if kind == 'timed_out' and 'Iteration budget exhausted' in str(payload):
                labels['timed_out'] = 'encerrada por orçamento de iterações esgotado (não é timeout de relógio)'
            text_value = f"⚠️ Minha atividade no card {task} foi {labels.get(kind, 'interrompida')}."
        if row['run_id']:
            evidence_run=conn.execute('SELECT metadata FROM task_runs WHERE id=?',(row['run_id'],)).fetchone()
            evidence=json.loads(evidence_run['metadata'] or '{}') if evidence_run else {}
            delivery=evidence.get('immutable_review') or evidence.get('immutable_delivery')
            if not delivery and kind in ('claimed','changes_requested'):
                prior=conn.execute("SELECT metadata FROM task_runs WHERE task_id=? AND id<=? AND outcome='review_requested' ORDER BY id DESC LIMIT 1",(row['task_id'],row['run_id'])).fetchone()
                delivery=json.loads(prior['metadata'] or '{}').get('immutable_delivery') if prior else None
            if delivery:
                mode='review' if kind in ('completed','changes_requested') or payload.get('source_status')=='review' else 'implementation'
                text_value+=f" Modo: {mode}; entrega: {delivery['revision'][:12]}; responsável: {profile}."
        result.append(
            {
                "event_id": int(row["event_id"]),
                "profile": profile,
                "text": text_value,
            }
        )
    return result


def _profile_token(config: dict[str, Any], profile: str) -> str:
    if not PROFILE_RE.fullmatch(profile):
        raise RuntimeError(f"perfil inválido no evento: {profile!r}")
    cache = config.setdefault("profile_token_cache", {})
    if profile not in cache:
        cache[profile] = load_token(config["profiles_root"] / profile / ".env")
    return str(cache[profile])


def emit_activity_updates(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    state: dict[str, Any],
) -> int:
    """Send start/end announcements from the bot that owns each run."""
    cursor_value = state.get("activity_event_cursor")
    sent = 0
    if cursor_value is None:
        cursor = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM task_events").fetchone()[0])
        # Avoid replaying history, but announce work already in flight when
        # this feature is enabled for the first time.
        rows = conn.execute(
            """
            SELECT t.id AS task_id,t.title,r.profile,e.payload
              FROM tasks t
              JOIN task_runs r ON r.id=t.current_run_id
              LEFT JOIN task_events e ON e.id=(
                  SELECT MAX(e2.id) FROM task_events e2
                   WHERE e2.task_id=t.id AND e2.run_id=t.current_run_id
                     AND e2.kind='claimed'
              )
             WHERE t.status='running'
            """
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            icon = "🔎" if isinstance(payload, dict) and payload.get("source_status") == "review" else "▶️"
            message = f"{icon} Atividade em andamento no card {row['task_id']} — {row['title']}."
            try:
                notify(config, _profile_token(config, str(row["profile"])), config["chat_id"], message,
                       key=f"initial:{row['task_id']}:{cursor}")
                sent += 1
            except Exception as exc:
                print(f"activity announcement failed profile={row['profile']}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        state["activity_event_cursor"] = cursor
        return sent

    cursor = int(cursor_value)
    for event in collect_activity_events(conn, after_event_id=cursor):
        try:
            notify(config,
                _profile_token(config, str(event["profile"])),
                config["chat_id"],
                str(event["text"]),
                key=f"event:{event['event_id']}",
            )
            sent += 1
        except Exception as exc:
            print(
                f"activity announcement failed event={event['event_id']} profile={event['profile']}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
        cursor = int(event["event_id"])
    state["activity_event_cursor"] = cursor
    return sent


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def run_branch_janitor(config: dict[str, Any]) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            sys.executable,
            str(config["branch_janitor_script"]),
            "--repo", str(config["branch_janitor_repo"]),
            "--db", str(config["db_path"]),
            "--audit", str(config["branch_janitor_audit"]),
            "--grace-seconds", str(config["branch_janitor_grace_seconds"]),
            "--apply", "--json",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "branch janitor failed: "
            + (result.stderr or result.stdout).strip()[:800]
        )
    payload = json.loads(result.stdout)
    return list(payload.get("removed") or [])


def run_cycle(config: dict[str, Any], state: dict[str, Any]) -> dict[str, int | bool]:
    if config.get('attempt'):
        from coordination_store import CoordinationStore
        store = CoordinationStore(config['coordination_path'])
        try:
            from release_lifecycle import finalize
            with closing(connect_database(config['db_path'])) as release_conn:
                finalize(release_conn,config,store)
            row = store.db.execute('SELECT board,state FROM attempts WHERE id=?', (config['attempt'],)).fetchone()
            if not row or row['board'] != config['board']:
                raise ValueError('observer execution attempt is stale')
            if row['state'] in {'CANCELADA_PELO_CEO','HOMOLOGADA'}:
                return dict(terminal=True,subscriptions_added=0,active_alerts=0,
                    notifications_sent=0,activity_sent=0,orphans_reaped=0,
                    recoveries_created=0,semantic_reclaims=0,branches_removed=0,digest_sent=False)
        finally:
            store.close()
    now = int(time.time())
    notifications_sent = 0
    activity_sent = 0
    digest_sent = False
    orphans_reaped = 0
    recoveries_created = 0
    semantic_reclaims = 0
    branches_removed = 0
    # sqlite3.Connection.__exit__ commits/rolls back, but does not close the
    # connection. Explicit closing prevents one DB/WAL descriptor leak per
    # polling cycle and avoids retaining a deleted WAL generation.
    with closing(connect_database(config["db_path"])) as conn:
        added = ensure_subscriptions(
            conn,
            chat_id=config["chat_id"],
            notifier_profile=config["notifier_profile"],
            now=now,
        )
        if config.get("activity_enabled", True):
            activity_sent = emit_activity_updates(conn, config, state)
        if config.get("reap_orphans_enabled", True):
            reaped = reap_orphan_workers(
                conn,
                state,
                now=now,
                grace_seconds=config["orphan_grace_seconds"],
                kill_grace_seconds=config["orphan_kill_grace_seconds"],
            )
            for action in reaped:
                notify(config,
                    config["token"],
                    config["chat_id"],
                    f"🧹 Hermes Watchdog: worker órfão do card {action['task_id']} "
                    f"(PID {action['pid']}) recebeu {action['signal']}.",
                )
                notifications_sent += 1
            orphans_reaped = len(reaped)
        if config.get("incident_supervisor_enabled", False):
            from delivery_gate import check_delivery
            try:
                if config.get('attempt'):
                    from durable_supervisor import tick
                    from coordination_store import CoordinationStore
                    store = CoordinationStore(config['coordination_path'])
                    try:
                        from handoff_bridge import sync_handoffs
                        from team_control import reconcile_questions
                        reconcile_questions(conn,config,store)
                        try:
                            sync_handoffs(conn, config, store)
                            state.pop('handoff_bridge_error',None)
                        except Exception as exc:
                            state['handoff_bridge_error'] = type(exc).__name__
                            print('handoff projection failed: ' + type(exc).__name__,flush=True)
                        from e2e_fault import tick as e2e_fault_tick
                        fault_notices=e2e_fault_tick(conn,config,store,now)
                        incident_notices = fault_notices+tick(conn, config, store, now, check_delivery)
                        state['handoff_incidents'] = {
                            row['id']: dict(json.loads(row['data']),
                                card=json.loads(row['data']).get('native_task', 'pending'),
                                phase=json.loads(row['data'])['status'])
                            for row in store.db.execute("SELECT id,data FROM records WHERE attempt=? AND kind='incident'", (config['attempt'],))}
                    finally:
                        store.close()
                else:
                    from incident_supervisor import tick
                    incident_notices = tick(conn, config, state, now, check_delivery)
                state.pop('incident_supervisor_error', None)
            except Exception as exc:
                # Keep liveness/diagnostics running if one operational action
                # fails. Persist an explicit unhealthy state, never a green OK.
                state['incident_supervisor_error'] = type(exc).__name__
                incident_notices = []
                print('incident supervisor failed: ' + type(exc).__name__ + ': ' + str(exc)[:400], flush=True)
            # Persist before delivery; notification failures must not duplicate
            # operational incident cards on the next cycle.
            pending = state.setdefault('incident_notifications_pending', [])
            pending.extend(incident_notices)
            save_state(config["state_path"], state)
            while pending:
                try:
                    notify(config, config["token"], config["chat_id"], pending[0])
                except Exception as exc:
                    print('incident notification pending: ' + type(exc).__name__, flush=True)
                    break
                pending.pop(0)
                save_state(config["state_path"], state)
                notifications_sent += 1
        elif config.get("auto_recovery_enabled", False):
            recoveries = ensure_failure_recovery_task(
                conn,
                board=config["board"],
                project_id=config["project_id"],
                now=now,
                executable=config["hermes_executable"],
            )
            for recovery in recoveries:
                notify(config,
                    config["token"],
                    config["chat_id"],
                    f"🛠 Hermes Watchdog criou {recovery['recovery_task_id']} para "
                    f"diagnosticar {recovery['source_task_id']}; o Tech Lead fará "
                    "plano/PR e revisão CTO antes de liberar replacement.",
                )
                notifications_sent += 1
            recoveries_created = len(recoveries)
        alerts = detect_database_anomalies(
            conn,
            now=now,
            heartbeat_stale_seconds=config["heartbeat_stale_seconds"],
            runtime_warn_seconds=config["runtime_warn_seconds"],
            ready_stale_seconds=config["ready_stale_seconds"],
            max_concurrent_tasks=config.get("max_concurrent_tasks"),
        )
        alerts.extend(detect_process_anomalies())
        if state.get('incident_supervisor_error'):
            alerts.append(_alert('supervisor:error', 'supervisor_failure',
                '🚨 Supervisor de incidentes falhou; recuperação não confirmada. Verificar log do observer.'))
        if state.get('handoff_bridge_error'):
            alerts.append(_alert('handoff-projection-error','handoff_projection',
                '🚨 Registro de handoffs inconsistente; recuperação de outros cards continua, mas exige diagnóstico do CTO.'))
        # Keep the supervisor's unresolved incidents visible in telemetry even
        # when no worker is running and no heartbeat/runtime alarm applies.
        if config.get('incident_supervisor_enabled', False):
            for sid, incident in state.get('handoff_incidents', {}).items():
                if incident['phase'] not in ('resolved', 'superseded'):
                    alerts.append(_alert(
                        'incident:' + sid, 'handoff_incident',
                        f"🚧 {incident['card']}: {sid} aguarda resolução; responsável {incident['owner']}, estado {incident['phase']}.",
                    ))
        alerts.extend(
            detect_semantic_stalls(
                conn,
                state,
                now=now,
                stall_seconds=config["semantic_stall_seconds"],
            )
        )
        if config.get("semantic_reclaim_enabled", False):
            reclaimed = reclaim_semantic_stalls(
                conn,
                state,
                now=now,
                reclaim_seconds=config["semantic_reclaim_seconds"],
                board=config["board"],
                executable=config["hermes_executable"],
            )
            for action in reclaimed:
                notify(config,
                    config["token"],
                    config["chat_id"],
                    f"🔄 Hermes Watchdog reencaminhou {action['task_id']}: "
                    "worker vivo, mas sem progresso Git durável. A tentativa foi "
                    "encerrada e o dispatcher poderá retomá-la.",
                )
                notifications_sent += 1
            semantic_reclaims = len(reclaimed)
        selected, recovered = select_notifications(
            state, alerts, now=now, repeat_seconds=config["repeat_seconds"]
        )
        for alert in selected:
            notify(config, config["token"], config["chat_id"], alert["text"])
            notifications_sent += 1
        if recovered:
            notify(config,
                config["token"],
                config["chat_id"],
                "✅ Hermes Watchdog: anomalia(s) normalizada(s): " + ", ".join(recovered),
            )
            notifications_sent += 1
        last_digest = int(state.get("last_digest_at", 0))
        if now - last_digest >= config["digest_seconds"]:
            suffix = f" Assinaturas novas: {added}." if added else ""
            notify(config, config["token"], config["chat_id"], build_digest(conn) + suffix)
            state["last_digest_at"] = now
            notifications_sent += 1
            digest_sent = True
    if config.get("branch_janitor_enabled", False):
        last_janitor = int(state.get("last_branch_janitor_at", 0))
        if now - last_janitor >= config["branch_janitor_interval_seconds"]:
            removed = run_branch_janitor(config)
            state["last_branch_janitor_at"] = now
            branches_removed = len(removed)
            for item in removed:
                notify(config,
                    config["token"],
                    config["chat_id"],
                    f"🧹 Git janitor: removi branch `{item['branch']}` do card "
                    f"{item['task_id']} após provar integração em {item['base']}. "
                    "Worktree local e branch remota também foram removidos quando existiam.",
                )
                notifications_sent += 1
    save_state(config["state_path"], state)
    return {
        "subscriptions_added": added,
        "active_alerts": len(alerts),
        "notifications_sent": notifications_sent,
        "activity_sent": activity_sent,
        "orphans_reaped": orphans_reaped,
        "recoveries_created": recoveries_created,
        "semantic_reclaims": semantic_reclaims,
        "branches_removed": branches_removed,
        "digest_sent": digest_sent,
    }


def main() -> int:
    profile_dir = Path(os.environ.get("HERMES_OBSERVER_PROFILE_DIR", "/opt/data/profiles/techlead"))
    config = {
        "db_path": Path(
            os.environ.get(
                "HERMES_OBSERVER_DB",
                "/opt/data/kanban/boards/truco-online/kanban.db",
            )
        ),
        "state_path": Path(
            os.environ.get(
                "HERMES_OBSERVER_STATE",
                "/opt/data/observability/truco-online-watchdog.json",
            )
        ),
        "chat_id": os.environ.get("HERMES_OBSERVER_CHAT_ID", "-5584379349"),
        "notifier_profile": os.environ.get("HERMES_OBSERVER_NOTIFIER", "techlead"),
        "profiles_root": Path(os.environ.get("HERMES_OBSERVER_PROFILES_ROOT", "/opt/data/profiles")),
        "board": os.environ.get("HERMES_OBSERVER_BOARD", "truco-online"),
        "attempt": os.environ.get("HERMES_EXECUTION_ATTEMPT"),
        "coordination_path": Path(os.environ.get("HERMES_COORDINATION_DB", "/opt/data/governance/coordination.db")),
        "project_id": os.environ.get("HERMES_OBSERVER_PROJECT_ID", "p_71f57328"),
        "hermes_executable": os.environ.get(
            "HERMES_OBSERVER_HERMES", "/opt/hermes/.venv/bin/hermes"
        ),
        "auto_recovery_enabled": os.environ.get(
            "HERMES_OBSERVER_AUTO_RECOVERY", "true"
        ).lower() not in {"0", "false", "no"},
        "incident_supervisor_enabled": os.environ.get(
            "HERMES_OBSERVER_INCIDENT_SUPERVISOR", "false"
        ).lower() in {"1", "true", "yes"},
        "activity_enabled": os.environ.get("HERMES_OBSERVER_ACTIVITY", "true").lower() not in {"0", "false", "no"},
        "reap_orphans_enabled": os.environ.get("HERMES_OBSERVER_REAP_ORPHANS", "true").lower() not in {"0", "false", "no"},
        "orphan_grace_seconds": env_int("HERMES_OBSERVER_ORPHAN_GRACE", 180),
        "orphan_kill_grace_seconds": env_int("HERMES_OBSERVER_ORPHAN_KILL_GRACE", 60),
        "heartbeat_stale_seconds": env_int("HERMES_OBSERVER_HEARTBEAT_STALE", 180),
        "runtime_warn_seconds": env_int("HERMES_OBSERVER_RUNTIME_WARN", 2700),
        "ready_stale_seconds": env_int("HERMES_OBSERVER_READY_STALE", 1200),
        "max_concurrent_tasks": env_int("HERMES_OBSERVER_MAX_CONCURRENT", 2),
        "semantic_stall_seconds": env_int("HERMES_OBSERVER_SEMANTIC_STALL", 1200),
        "semantic_reclaim_enabled": os.environ.get(
            "HERMES_OBSERVER_SEMANTIC_RECLAIM", "true"
        ).lower() not in {"0", "false", "no"},
        "semantic_reclaim_seconds": env_int(
            "HERMES_OBSERVER_SEMANTIC_RECLAIM_AFTER", 2700
        ),
        "branch_janitor_enabled": os.environ.get(
            "HERMES_OBSERVER_BRANCH_JANITOR", "true"
        ).lower() not in {"0", "false", "no"},
        "branch_janitor_script": Path(
            os.environ.get("HERMES_OBSERVER_BRANCH_JANITOR_SCRIPT", "/opt/observer/git_branch_janitor.py")
        ),
        "branch_janitor_repo": Path(
            os.environ.get("HERMES_OBSERVER_BRANCH_JANITOR_REPO", "/Users/weber/Documents/projetos_pessoais_desenv/hermes/truco-online")
        ),
        "branch_janitor_audit": Path(
            os.environ.get("HERMES_OBSERVER_BRANCH_JANITOR_AUDIT", "/opt/data/observability/branch-janitor.jsonl")
        ),
        "branch_janitor_grace_seconds": env_int("HERMES_OBSERVER_BRANCH_JANITOR_GRACE", 86400),
        "branch_janitor_interval_seconds": env_int("HERMES_OBSERVER_BRANCH_JANITOR_INTERVAL", 1800),
        "repeat_seconds": env_int("HERMES_OBSERVER_REPEAT", 1800),
        "digest_seconds": env_int("HERMES_OBSERVER_DIGEST", 1800),
        "poll_seconds": env_int("HERMES_OBSERVER_POLL", 60),
        "token": load_token(profile_dir / ".env"),
    }
    state = load_state(config["state_path"])
    print("Hermes Kanban watchdog started", flush=True)
    while True:
        try:
            if config['db_path'].with_name('MAINTENANCE').exists():
                print('watchdog maintenance: dispatch and automatic recovery paused', flush=True)
                time.sleep(config['poll_seconds'])
                continue
            result = run_cycle(config, state)
            from planning_status import reconcile as reconcile_planning_status
            reconcile_planning_status(os.environ.get('HERMES_TEAM_EXECUTION','/opt/data/governance/execution.json'))
            if config.get('attempt'):
                from durable_notifications import flush
                delivered = flush(config, send_telegram, lambda profile: _profile_token(config, profile))
                print(f'outbox delivered={delivered}', flush=True)
            print(
                "watchdog cycle ok "
                f"subscriptions_added={result['subscriptions_added']} "
                f"active_alerts={result['active_alerts']} "
                f"notifications_sent={result['notifications_sent']} "
                f"activity_sent={result['activity_sent']} "
                f"orphans_reaped={result['orphans_reaped']} "
                f"recoveries_created={result['recoveries_created']} "
                f"semantic_reclaims={result['semantic_reclaims']} "
                f"branches_removed={result['branches_removed']} "
                f"digest_sent={str(result['digest_sent']).lower()}",
                flush=True,
            )
        except Exception as exc:
            print(f"watchdog cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        time.sleep(config["poll_seconds"])


if __name__ == "__main__":
    raise SystemExit(main())
