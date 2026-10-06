"""Register the frozen CTO-only SPIKE, preserving the held author/release."""
import hashlib
import json
import sqlite3
import broker as b
import admission_controls_spike
ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
with b.LOCK,b.db() as con:
    if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
        raise ValueError('idle maintenance required')
    backup=b.STATE/'u3-before-isolated-controls-spike-20261004.sqlite'
    if not backup.exists():
        with sqlite3.connect(backup) as target:
            con.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
result=admission_controls_spike.register(b.handoff_context(),ROOT,'U3')
result['backup_sha256']=hashlib.sha256(backup.read_bytes()).hexdigest()
print(json.dumps(result))
