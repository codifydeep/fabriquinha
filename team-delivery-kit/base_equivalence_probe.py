"""Read-only comparison of complete original-base manifests and inventories."""
import json
import sys
from pathlib import Path
try:from initial_base_inspect import inspect
except ImportError:from broker.initial_base_inspect import inspect


def run(approved,current,manifest):
    a=inspect(approved,manifest);c=inspect(current,manifest)
    if a!=c:raise ValueError('complete original-base inventories must match')
    inventory=json.loads((Path(approved)/'manifest.json').read_text())['files']
    total=sum((Path(approved)/name).stat().st_size for name in inventory)
    if not 1<=len(inventory)<=2048 or total>134217728:raise ValueError('bounded original-base inventory required')
    return dict(operation='immutable_original_base_equivalence_v1',manifest_sha256=manifest,
        file_count=len(inventory),total_bytes=total,files_identical=True,
        source_modified=False,execution_authorized=False,delivery_approval=False)


if __name__=='__main__':print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
