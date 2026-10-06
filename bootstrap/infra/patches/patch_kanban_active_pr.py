#!/usr/bin/env python3
"""Apply the Truco PoC respawn-guard hotfix to the pinned Hermes release."""

from pathlib import Path


TARGET = Path("/opt/hermes/hermes_cli/kanban_db.py")

OLD = '''    # 4. GitHub PR URL in a recent comment — prior worker already opened a PR.
    pr_cutoff = now - _RESPAWN_GUARD_PR_WINDOW
    for c in conn.execute(
        "SELECT body FROM task_comments WHERE task_id = ? AND created_at >= ?",
        (task_id, pr_cutoff),
    ).fetchall():
        if c["body"] and _RESPAWN_GUARD_PR_URL_RE.search(c["body"]):
            return "active_pr"

    return None
'''

NEW = '''    # 4. PR links are evidence, not a respawn lock.
    #
    # A free-form comment cannot prove that a PR belongs to this task: planning
    # and recovery cards routinely cite prerequisite or superseded PRs.  The
    # former heuristic trapped those cards forever after a timeout.  Retrying
    # the same task is safe because it reuses the same worktree/branch and
    # GitHub itself prevents a second open PR for the same head/base pair.
    # Independent review remains enforced by the worktree completion gate.
    return None
'''


def apply_hotfix(source: str) -> str:
    if NEW in source:
        return source
    if source.count(OLD) != 1:
        raise SystemExit("Pinned Hermes active_pr block did not match exactly; refusing unsafe patch")
    return source.replace(OLD, NEW)


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    TARGET.write_text(apply_hotfix(source), encoding="utf-8")


if __name__ == "__main__":
    main()
