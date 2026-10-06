#!/usr/bin/env python3
"""Confine dispatcher worker file writes to its own resolved workspace."""

from pathlib import Path


TARGET = Path("/opt/hermes/hermes_cli/kanban_db.py")

OLD = '''    if workspace and os.path.isabs(workspace) and os.path.isdir(workspace):
        env["TERMINAL_CWD"] = workspace
    if task.branch_name:
'''

NEW = '''    if workspace and os.path.isabs(workspace) and os.path.isdir(workspace):
        env["TERMINAL_CWD"] = workspace
        # The container-level safe root covers the whole repository so the
        # interactive gateways can operate. A dispatcher worker is narrower:
        # pin its file-tool write boundary to this card's own workspace. This
        # rejects absolute writes to the primary checkout or sibling worktrees
        # even when a local model ignores the prompt-level isolation contract.
        env["HERMES_WRITE_SAFE_ROOT"] = workspace
    if task.branch_name:
'''


def apply_hotfix(source: str) -> str:
    if NEW in source:
        return source
    if source.count(OLD) != 1:
        raise SystemExit(
            "Pinned Hermes TERMINAL_CWD block did not match exactly; refusing unsafe patch"
        )
    return source.replace(OLD, NEW)


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    TARGET.write_text(apply_hotfix(source), encoding="utf-8")


if __name__ == "__main__":
    main()
