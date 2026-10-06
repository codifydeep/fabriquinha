from pathlib import Path
TARGET = Path('/opt/hermes/hermes_cli/kanban_db.py')
ANCHOR = '    if initial_status not in VALID_INITIAL_STATUSES:\n'
BLOCK = '''    # Enforce worker scope below CLI and tool surfaces.
    worker_task = os.environ.get("HERMES_KANBAN_TASK")
    if worker_task:
        parents = tuple(parents)
        owner = conn.execute("SELECT title FROM tasks WHERE id=?", (worker_task,)).fetchone()
        if not owner or not owner["title"].upper().startswith(("GRAPH-", "RECOVERY-")):
            raise ValueError("worker cannot fan out outside GRAPH/legacy RECOVERY")
        if worker_task not in parents or workspace_path is not None:
            raise ValueError("worker child requires its own parent and a fresh workspace")
        if title.upper().startswith("RELEASE-"):
            raise ValueError("worker cannot create RELEASE controller")
'''

def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR) != 1:
        raise ValueError('unknown create_task entry; refusing patch')
    return source.replace(ANCHOR, BLOCK + ANCHOR)

if __name__ == '__main__':
    TARGET.write_text(apply(TARGET.read_text()))
