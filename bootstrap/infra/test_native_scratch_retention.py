import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from delivery_receipts import EvidenceStore
from scratch_evidence import snapshot

with tempfile.TemporaryDirectory() as tmp:
    board=Path(tmp)/'board'
    board.mkdir()
    kb.init_db(board/'kanban.db')
    conn=kb.connect(board/'kanban.db')
    try:
        parent=kb.create_task(conn,title='parent',assignee='backend_data')
        child=kb.create_task(conn,title='child',assignee='quality_security',parents=[parent])
        for task in [parent,child]:
            work=board/'workspaces'/task
            work.mkdir(parents=True)
            (work/'artifact.txt').write_text('durable '+task)
            conn.execute("UPDATE tasks SET status='done',workspace_path=? WHERE id=?",(str(work),task))
        conn.commit()
        with patch.object(kb,'_is_managed_scratch_path',return_value=True):
            kb._cleanup_workspace(conn,child)
        for task in [parent,child]:
            assert not (board/'workspaces'/task).exists()
            evidence=EvidenceStore(board/'evidence',task)
            ref=json.loads((evidence.root/'latest.json').read_text())
            receipt=evidence.load(ref['sha256'])
            assert receipt['artifacts'][0]['path']=='artifact.txt'
        print('PASS: native cleanup archives both completed child and deferred parent')
        work=board/'workspaces'/child
        work.mkdir()
        (work/'unsafe-link').symlink_to(board/'kanban.db')
        with patch.object(kb,'_is_managed_scratch_path',return_value=True):
            kb._cleanup_workspace(conn,child)
        assert work.exists()
        print('PASS: failed archival retains original workspace instead of deleting it')
    finally: conn.close()
