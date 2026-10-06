"""Document/design adapter: artifacts follow ordinary snapshots, PRs and CI.

No synthetic Red: documentation is characterized alongside unchanged code tests.
Executable web implementation belongs to frontend, not this artifact capability.
"""
from pathlib import PurePosixPath

def editable(name):
    p=PurePosixPath(name)
    if name.startswith('docs/governance/') or name=='docs/product/ceo-goal-v0.1.md':return False
    return len(p.parts)>1 and p.parts[0] in ('docs','design') and p.suffix in ('.md','.json','.svg','.html','.css')

def validate_replacements(replacements):
    if not replacements or not all(editable(n) for n in replacements):raise PermissionError('document adapter may edit only docs/design artifacts')
    # Preview artifacts are untrusted, never executed by the controller.
    return True
