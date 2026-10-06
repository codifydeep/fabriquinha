from pathlib import Path
target=Path('/opt/hermes/hermes_cli/kanban_db.py')
source=target.read_text()
if 'snapshot_scratch_evidence' not in source:
    for variable,anchor in [
        ('task_id','                shutil.rmtree(wp, ignore_errors=True)\n                _log.debug("Removed scratch workspace: %s", wp)'),
        ('parent_id','                shutil.rmtree(wp, ignore_errors=True)\n                _log.debug("Deferred cleanup: removed parent %s scratch workspace: %s", parent_id, wp)')]:
        if source.count(anchor)!=1:
            raise SystemExit('native scratch cleanup changed; refusing patch')
        guard=f'                from scratch_evidence import snapshot as snapshot_scratch_evidence\n                snapshot_scratch_evidence(conn, {variable}, wp)\n'
        source=source.replace(anchor,guard+anchor)
    target.write_text(source)
