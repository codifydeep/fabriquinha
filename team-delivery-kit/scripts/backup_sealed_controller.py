"""Private SQLite backup/restore proof for an exact sealed maintenance operation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from controller_maintenance_cli import arguments

PROGRAM='''import hashlib,json,os,sqlite3,sys
from pathlib import Path
sys.path.insert(0,"/")
import broker as b,controller_maintenance as maintenance
operation=sys.argv[1]
with b.LOCK,b.db() as con:
 state=maintenance.current(con)
 if not state or state["operation_id"]!=operation or state["stage"]!="sealed":raise ValueError("exact sealed maintenance required")
 if maintenance.native_active(b):raise ValueError("native tasks active")
 if con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]:raise ValueError("leases active")
 path=b.STATE/("sealed-backup-"+operation+".sqlite")
 # Persist a new backup once. Unknown acknowledgments require observation,
 # never replacing a potentially completed backup.
 fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
 destination=sqlite3.connect(path)
 try:
  con.backup(destination)
  if destination.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ValueError("backup integrity failed")
  # Keep restore verification off RAM: production history may exceed the
  # controller's memory limit. Retain an interrupted proof for inspection.
  proof=b.STATE/("sealed-restore-"+operation+".sqlite")
  proof_fd=os.open(proof,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(proof_fd)
  restored=sqlite3.connect(proof)
  try:
   destination.backup(restored)
   if restored.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ValueError("restore proof failed")
   receipt=restored.execute("SELECT receipt FROM controller_maintenance WHERE operation_id=?",(operation,)).fetchone()
   if not receipt or json.loads(receipt[0])!=state:raise ValueError("restored maintenance identity mismatch")
   tables=[r[0] for r in destination.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
   for table in tables:
    quoted='"'+table.replace('"','""')+'"'
    if destination.execute("SELECT count(*) FROM "+quoted).fetchone()!=restored.execute("SELECT count(*) FROM "+quoted).fetchone():raise ValueError("restore row count mismatch")
  finally:restored.close()
  proof.unlink()
 finally:destination.close()
 digest=hashlib.sha256()
 with path.open("rb") as stream:
  for chunk in iter(lambda:stream.read(1048576),b""):digest.update(chunk)
 print(json.dumps({"operation_id":operation,"path":str(path),"sha256":digest.hexdigest(),"backup_integrity":"ok","restore_integrity":"ok","native_active":0,"active_leases":0,"delivery_approval":False}))
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True);parser.add_argument('--operation',required=True)
    options=parser.parse_args()
    owned=arguments(options.namespace,'seal',options.operation)[4]
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',owned],text=True))
    if labels.get('com.docker.compose.project')!=options.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned Compose controller required')
    result=subprocess.check_output(['docker','exec','-w','/',owned,'python','-c',PROGRAM,options.operation],text=True,timeout=45)
    print(json.dumps(json.loads(result),sort_keys=True))


if __name__=='__main__':main()
