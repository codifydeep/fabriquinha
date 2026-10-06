import hashlib,json,os
from maintenance_snapshot_validate import manifest
from u3_controls_execution import SOURCES
from pathlib import Path
raw,files=manifest(Path('/seed'))
if hashlib.sha256(raw).hexdigest()!=os.environ['SEED_MANIFEST']:raise ValueError('seed identity required')
print(json.dumps({'/workspace/'+p:files[p] for p in SOURCES}))
