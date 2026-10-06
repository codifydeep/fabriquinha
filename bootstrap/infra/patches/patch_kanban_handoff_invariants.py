#!/usr/bin/env python3
"""Keep worker-created handoffs gated by the worker's own reviewed task."""

from pathlib import Path


TARGET = Path("/opt/hermes/tools/kanban_tools.py")

OLD = '''    if not isinstance(parents, (list, tuple)):
        return tool_error(
            f"parents must be a list of task ids, got {type(parents).__name__}"
        )
    board = args.get("board")
'''

NEW = '''    if not isinstance(parents, (list, tuple)):
        return tool_error(
            f"parents must be a list of task ids, got {type(parents).__name__}"
        )

    # Dispatcher workers may fan out follow-up work, but every child must be
    # gated by the worker's own task.  Linking children to an older completed
    # plan makes them immediately ready before the current plan is reviewed.
    # It also lets a confused local model bypass its task scope indirectly.
    scoped_task_id = os.environ.get("HERMES_KANBAN_TASK")
    if scoped_task_id:
        if str(title).strip().upper().startswith("RELEASE-"):
            return tool_error(
                "dispatcher workers cannot create RELEASE controllers; "
                "update the existing controller through the orchestrator"
            )
        if scoped_task_id not in parents:
            return tool_error(
                f"worker-created handoff must include its own task "
                f"{scoped_task_id} in parents so review gates dispatch"
            )
        if workspace_path is not None:
            return tool_error(
                "worker-created handoff cannot reuse an explicit workspace_path; "
                "omit it to receive a fresh task-id worktree"
            )

    board = args.get("board")
'''

OLD_FANOUT_ROLE = '''    try:
        kb, conn = _connect(board=board)
        try:
            # A project link is safe to inherit because ``create_task`` turns
'''

NEW_FANOUT_ROLE = '''    try:
        kb, conn = _connect(board=board)
        try:
            # Split planning from dispatch. PLAN/GOVERNANCE/implementation
            # workers produce one reviewed artifact; only GRAPH may materialize
            # a DAG, and RECOVERY may create one corrected replacement.
            if scoped_task_id:
                scoped_task = kb.get_task(conn, scoped_task_id)
                scoped_title = (
                    str(scoped_task.title).strip().upper()
                    if scoped_task is not None else ""
                )
                if not scoped_title.startswith(("GRAPH-", "RECOVERY-")):
                    return tool_error(
                        f"task {scoped_task_id} ({scoped_title or 'unknown'}) "
                        "cannot fan out; only GRAPH-* and RECOVERY-* workers "
                        "may create child tasks"
                    )

            # A project link is safe to inherit because ``create_task`` turns
'''


def apply_hotfix(source: str) -> str:
    if NEW in source and NEW_FANOUT_ROLE in source:
        return source
    if NEW not in source:
        if source.count(OLD) != 1:
            raise SystemExit(
                "Pinned Hermes kanban_create block did not match exactly; refusing unsafe patch"
            )
        source = source.replace(OLD, NEW)
    if source.count(OLD_FANOUT_ROLE) != 1:
        raise SystemExit(
            "Pinned Hermes kanban_create connection block did not match exactly; refusing unsafe patch"
        )
    return source.replace(OLD_FANOUT_ROLE, NEW_FANOUT_ROLE)


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    TARGET.write_text(apply_hotfix(source), encoding="utf-8")


if __name__ == "__main__":
    main()
