"""Regression: root observer creates evidence; UID 10000 worker must still use it."""
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from scratch_evidence import snapshot

assert os.geteuid()==0
with tempfile.TemporaryDirectory() as tmp:
    board=Path(tmp); board.chmod(0o755)
    work=board/'workspaces'/'t_owner'; work.mkdir(parents=True)
    os.chown(work,10000,10000)
    (work/'proof.txt').write_text('evidence')
    with sqlite3.connect(board/'kanban.db') as db:
        digest=snapshot(db,'t_owner',work)
    def worker():
        os.setgid(10000); os.setuid(10000)
    result=subprocess.run(['/opt/hermes/.venv/bin/python','-c',
        'from delivery_receipts import EvidenceStore; import sys; s=EvidenceStore(sys.argv[1],"t_owner"); s.load(sys.argv[2]); s.capture_bytes("new.txt",b"new"); print("PASS: worker reads root-created proof and writes next receipt")',
        str(board/'evidence'),digest],preexec_fn=worker,check=True,text=True,capture_output=True)
    print(result.stdout)
