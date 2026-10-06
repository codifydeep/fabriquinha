"""Ownership only inside the dedicated product worker profile volume."""
import os
from pathlib import Path
root=Path('/trial-profiles')
for path in [root,*root.rglob('*')]:
    if path.is_symlink():raise RuntimeError('unexpected profile symlink')
    os.chown(path,10000,10000)
