"""Copy reviewed helper/lock into persistent Hermes tools; npm ci runs separately."""
import shutil
from pathlib import Path
src=Path('/input/infra/defuddle'); dst=Path('/opt/data/company-tools/defuddle')
dst.mkdir(parents=True,exist_ok=True)
for name in ('package.json','package-lock.json','extract.mjs'):
    p=dst/name
    if p.exists() and p.read_bytes()!=(src/name).read_bytes():raise RuntimeError('Existing tool drift')
    shutil.copy2(src/name,p);p.chmod(0o644)
dst.chmod(0o755)
