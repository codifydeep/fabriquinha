"""Register the driver prerequisite, without author or release activation."""
import hashlib,json,sqlite3
import broker as b,harness_prerequisite
with b.LOCK,b.db() as con:
    if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
        raise ValueError('idle registration required')
    backup=b.STATE/'u3-before-driver-prerequisite-20261004.sqlite'
    if not backup.exists():
        with sqlite3.connect(backup) as target:
            con.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
result=harness_prerequisite.register(b.handoff_context(),'01a10805-c9a1-709d-a87c-a2da01ddc4e9')
result['backup_sha256']=hashlib.sha256(backup.read_bytes()).hexdigest()
print(json.dumps(result))
