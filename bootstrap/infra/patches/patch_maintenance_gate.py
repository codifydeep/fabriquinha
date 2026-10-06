from pathlib import Path
TARGET = Path('/opt/hermes/hermes_cli/kanban_db.py')
ANCHOR = '    # Reap zombie children from previously spawned workers. See\n'
BLOCK = '''    # A persisted board-local maintenance fence survives restarts.
    database = conn.execute("PRAGMA database_list").fetchone()[2]
    if database and Path(database).with_name("MAINTENANCE").exists():
        return DispatchResult()
'''

def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR) != 1:
        raise ValueError('unknown dispatch entry; refusing patch')
    return source.replace(ANCHOR, BLOCK + ANCHOR)

if __name__ == '__main__':
    TARGET.write_text(apply(TARGET.read_text()))
