#!/usr/bin/env python3
"""Safely retire terminal Hermes task branches already integrated upstream."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
import fcntl
from pathlib import Path


TASK_RE = re.compile(r"(?:^|[/_-])(t_[0-9a-f]{8})(?:$|[-_/])")
PROTECTED = {"main"}
TERMINAL = {"done", "archived"}


def command(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args), cwd=repo, text=True, capture_output=True, timeout=60, check=False
    )
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(args)}: {(result.stderr or result.stdout).strip()[:500]}")
    return result


def protected(branch: str) -> bool:
    return branch in PROTECTED or branch.startswith("release/")


def task_id_from_branch(branch: str) -> str | None:
    match = TASK_RE.search(branch)
    return match.group(1) if match else None


def worktrees(repo: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    record: dict[str, str] = {}
    for line in command(repo, "git", "worktree", "list", "--porcelain").stdout.splitlines() + [""]:
        if not line:
            branch = record.get("branch", "").removeprefix("refs/heads/")
            if branch and record.get("worktree"):
                result[branch] = Path(record["worktree"]).resolve()
            record = {}
        elif " " in line:
            key, value = line.split(" ", 1)
            record[key] = value
    return result


def terminal_tasks(db: Path) -> dict[str, dict[str, object]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT t.id,t.status,t.branch_name,t.workspace_path,
               COALESCE(t.completed_at,(
                   SELECT MAX(e.created_at) FROM task_events e
                    WHERE e.task_id=t.id AND e.kind IN ('archived','completed')
               ),t.created_at) AS terminal_at,
               EXISTS(
                   SELECT 1 FROM task_runs r
                    WHERE r.task_id=t.id AND r.status='running'
               ) AS has_running
          FROM tasks t
         WHERE t.status IN ('done','archived')
        """
    ).fetchall()
    conn.close()
    return {str(row["id"]): dict(row) for row in rows}


def open_pr_heads(repo: Path) -> set[str]:
    result = command(
        repo, "gh", "pr", "list", "--state", "open", "--limit", "200",
        "--json", "headRefName", check=False,
    )
    if result.returncode:
        raise RuntimeError(f"cannot inspect open PRs: {(result.stderr or result.stdout).strip()[:500]}")
    return {str(item["headRefName"]) for item in json.loads(result.stdout or "[]")}


def integrated(repo: Path, ref: str) -> str | None:
    releases = command(repo, 'git', 'for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin/release/').stdout.splitlines()
    for base in (*releases, "origin/main"):
        if command(repo, "git", "merge-base", "--is-ancestor", ref, base, check=False).returncode == 0:
            return base
    return None


def candidates(repo: Path, db: Path, *, now: int, grace_seconds: int) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    tasks = terminal_tasks(db)
    active_heads = open_pr_heads(repo)
    trees = worktrees(repo)
    refs = command(repo, "git", "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.splitlines()
    ready: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    for branch in refs:
        task_id = task_id_from_branch(branch)
        row = tasks.get(task_id or "")
        reason = None
        if protected(branch): reason = "protected"
        elif not task_id or row is None: reason = "no-terminal-card"
        elif row.get("has_running"): reason = "running-run"
        elif branch in active_heads: reason = "open-pr"
        elif now - int(row.get("terminal_at") or now) < grace_seconds: reason = "grace-period"
        if reason is None:
            with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
                descendant = conn.execute('''WITH RECURSIVE descendants(id) AS (
                    SELECT child_id FROM task_links WHERE parent_id=? UNION
                    SELECT l.child_id FROM task_links l JOIN descendants d ON l.parent_id=d.id
                ) SELECT 1 FROM descendants d JOIN tasks t ON t.id=d.id
                  WHERE t.status NOT IN ('done','archived') LIMIT 1''', (task_id,)).fetchone()
                if descendant:
                    reason = 'active-descendant-needs-delivery-evidence'
            conn.close()
        tree = trees.get(branch)
        if reason is None and tree:
            safe_root = (repo / ".worktrees").resolve()
            if tree == repo.resolve() or safe_root not in tree.parents:
                reason = "unsafe-worktree-path"
            else:
                status = command(repo, "git", "-C", str(tree), "status", "--porcelain", check=False)
                if status.returncode:
                    reason = "unreadable-worktree"
                elif status.stdout.strip():
                    reason = "dirty-worktree"
        base = integrated(repo, branch) if reason is None else None
        if reason is None and base is None: reason = "not-integrated"
        if reason:
            skipped.append({"branch": branch, "reason": reason})
            continue
        remote = command(repo, "git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}", check=False).returncode == 0
        sha = command(repo, 'git', 'rev-parse', branch).stdout.strip()
        if remote and command(repo, 'git', 'rev-parse', 'origin/' + branch).stdout.strip() != sha:
            skipped.append({'branch': branch, 'reason': 'remote-tip-differs'})
            continue
        ready.append({"task_id": task_id, "branch": branch, "sha": sha, "worktree": str(tree) if tree else None, "base": base, "remote": remote})
    return ready, skipped


def apply_cleanup(repo: Path, items: list[dict[str, object]], audit: Path, *, db: Path, grace_seconds: int) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    audit.parent.mkdir(parents=True, exist_ok=True)
    for item in items:
        branch = str(item["branch"])
        fresh, _ = candidates(repo, db, now=int(time.time()), grace_seconds=grace_seconds)
        if item not in fresh:
            continue
        # Namespace is shared with gateways in deployment. Fail closed on a
        # live worker even if its DB run has already become terminal.
        from kanban_watchdog import scan_worker_processes
        if scan_worker_processes().get(str(item['task_id'])):
            continue
        command(repo, "git", "check-ref-format", "--branch", branch)
        with audit.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({**item, 'action':'retirement-started', 'at':int(time.time())}) + '\n')
        if item.get("remote"):
            # Compare-and-delete prevents erasing a remote push after fetch.
            command(repo, 'git', 'push', 'origin', f"--force-with-lease=refs/heads/{branch}:{item['sha']}", '--delete', branch)
        if item.get("worktree"):
            command(repo, "git", "worktree", "remove", str(item["worktree"]))
        command(repo, "git", "branch", "-d", branch)
        event = {**item, "removed_at": int(time.time())}
        with audit.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        actions.append(event)
    return actions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=Path("/opt/data/observability/branch-janitor.jsonl"))
    parser.add_argument("--grace-seconds", type=int, default=86400)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if repo == Path("/") or not (repo / ".git").exists():
        raise SystemExit(f"unsafe or invalid repository: {repo}")
    command(repo, "git", "fetch", "--prune", "origin")
    ready, skipped = candidates(repo, args.db, now=int(time.time()), grace_seconds=max(0, args.grace_seconds))
    actions = []
    if args.apply:
        # Same lock as native dispatch; no new worker can be dispatched while
        # terminal-card eligibility is revalidated and refs are removed.
        with args.db.with_name(args.db.name + '.dispatch.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            actions = apply_cleanup(repo, ready, args.audit, db=args.db, grace_seconds=max(0, args.grace_seconds))
    payload = {"eligible": ready, "removed": actions, "skipped": skipped}
    print(json.dumps(payload, ensure_ascii=False) if args.json else json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
