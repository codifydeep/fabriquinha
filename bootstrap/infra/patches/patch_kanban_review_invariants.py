#!/usr/bin/env python3
"""Enforce non-circular, independent Kanban reviews in pinned Hermes."""

from pathlib import Path


TARGET = Path("/opt/hermes/hermes_cli/kanban_db.py")

OLD_RUNNING_GUARD = '''        # Refuse to clear a live worker's claim without proof of ownership
        # (expected_run_id) or an explicit human override (force=True).
        if (
            expected_run_id is None
            and not force
            and trow["status"] == "running"
            and trow["claim_lock"] is not None
        ):
'''

NEW_RUNNING_GUARD = '''        # A run claimed from the review lane must produce a verdict. Allowing
        # it to call request_review again reverses implementer/reviewer roles and
        # creates an endless review ping-pong. This is a state-machine invariant,
        # not a prompting convention.
        if (
            trow["status"] == "running"
            and _retry_status_for_run(conn, task_id, trow["current_run_id"])
            == "review"
        ):
            return _ret(
                False,
                "active run is a reviewer run; use complete to approve or "
                "request_changes to return work to the original implementer",
            )
        # Refuse to clear a live worker's claim without proof of ownership
        # (expected_run_id) or an explicit human override (force=True).
        if (
            expected_run_id is None
            and not force
            and trow["status"] == "running"
            and trow["claim_lock"] is not None
        ):
'''

OLD_REVIEWER_CANONICALIZATION = '''        reviewer = _canonical_assignee(reviewer) if reviewer is not None else None
        assignee_sql = ", assignee = ?" if reviewer is not None else ""
'''

NEW_REVIEWER_CANONICALIZATION = '''        reviewer = _canonical_assignee(reviewer) if reviewer is not None else None
        if reviewer is None:
            return _ret(False, "reviewer is required for an independent review")
        canonical_implementer = (
            _canonical_assignee(implementer) if implementer is not None else None
        )
        if reviewer == canonical_implementer:
            return _ret(False, "reviewer must be different from the implementer")
        assignee_sql = ", assignee = ?"
'''


def apply_hotfix(source: str) -> str:
    if NEW_RUNNING_GUARD in source and NEW_REVIEWER_CANONICALIZATION in source:
        return source
    if source.count(OLD_RUNNING_GUARD) != 1:
        raise SystemExit(
            "Pinned Hermes reviewer-run guard did not match exactly; refusing unsafe patch"
        )
    if source.count(OLD_REVIEWER_CANONICALIZATION) != 1:
        raise SystemExit(
            "Pinned Hermes reviewer canonicalization did not match exactly; refusing unsafe patch"
        )
    source = source.replace(OLD_RUNNING_GUARD, NEW_RUNNING_GUARD)
    return source.replace(
        OLD_REVIEWER_CANONICALIZATION, NEW_REVIEWER_CANONICALIZATION
    )


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    TARGET.write_text(apply_hotfix(source), encoding="utf-8")


if __name__ == "__main__":
    main()
