"""Validate the actual registered baseline/toolchain before author dispatch."""
import json
from pathlib import Path
from product_docker_runner import DockerRunner
cfg=json.loads(Path('/control/config.json').read_text())
card=next(iter(cfg['cards'].values()))
result=DockerRunner(cfg['snapshot_root'],'lobby-ts')(card['files'],cfg['image'])
Path('/control/toolchain-preflight.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('passed','exit_code','image','output')}))
if not result['passed']:raise SystemExit(1)
