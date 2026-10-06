"""Dedicated private control volume ownership; never expose it to workers."""
import os
from pathlib import Path
root=Path('/control')
for path in [root,*root.rglob('*')]:
    if path.is_symlink():raise ValueError('unexpected symlink')
    os.chown(path,10000,10000)
    if path.is_dir():path.chmod(0o2770)
    else:path.chmod(0o660)
print('Dedicated control volume prepared for non-root coordinator; no worker mount granted.')
