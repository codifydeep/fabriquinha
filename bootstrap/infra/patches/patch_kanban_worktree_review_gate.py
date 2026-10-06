#!/usr/bin/env python3
"""Require independent review before completing worktree-backed cards."""

from pathlib import Path


TARGET = Path("/opt/hermes/hermes_cli/kanban_db.py")

OLD = '''    # Gate: verify created_cards BEFORE the main write txn. A rejected
    # completion still needs an auditable event, so we emit it in a
    # tiny dedicated txn, then raise. The caller is responsible for
'''

NEW = '''    # Gate: worktree-backed delivery must pass through the review lane.
    # Prompting alone is not a sufficient invariant: a local model can call
    # complete directly after opening its own PR, bypassing independent review.
    delivery = conn.execute(
        "SELECT status, workspace_kind, current_run_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if delivery and delivery["workspace_kind"] == "worktree":
        source_is_review = delivery["status"] == "review" or (
            delivery["status"] == "running"
            and _retry_status_for_run(conn, task_id, delivery["current_run_id"])
            == "review"
        )
        if not source_is_review:
            with write_txn(conn):
                _append_event(
                    conn,
                    task_id,
                    "completion_blocked_review_required",
                    {
                        "source_status": delivery["status"],
                        "workspace_kind": delivery["workspace_kind"],
                    },
                    run_id=delivery["current_run_id"],
                )
            return False

    # Gate: verify created_cards BEFORE the main write txn. A rejected
    # completion still needs an auditable event, so we emit it in a
    # tiny dedicated txn, then raise. The caller is responsible for
'''


def apply_hotfix(source: str) -> str:
    if NEW in source:
        return source
    if source.count(OLD) != 1:
        raise SystemExit(
            "Pinned Hermes worktree completion block did not match exactly; "
            "refusing unsafe patch"
        )
    return source.replace(OLD, NEW)


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    TARGET.write_text(apply_hotfix(source), encoding="utf-8")


if __name__ == "__main__":
    main()
