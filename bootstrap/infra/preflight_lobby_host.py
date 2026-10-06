"""Safer preflight: host invokes exact test container; no daemon socket mount."""
import json,subprocess
from pathlib import Path
from product_docker_runner import DockerRunner
def main():
    cmd=['docker','run','--rm','--network=none','-v','truco-online-lobby-control:/control:ro',
        '--entrypoint','python','estudo-hermes-product:20260918.2','-c',
        'from pathlib import Path;print(Path("/control/config.json").read_text())']
    cfg=json.loads(subprocess.check_output(cmd,text=True))
    image=subprocess.check_output(['docker','image','inspect','truco-online-lobby-toolchain:20260918.2','--format','{{.Id}}'],text=True).strip()
    card=next(iter(cfg['cards'].values()))
    result=DockerRunner(cfg['snapshot_root'],'lobby-ts')(card['files'],image)
    report=Path(__file__).parents[1]/'product-launch/lobby-toolchain-preflight.json'
    report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=result['passed'],image=image,output=result['output'],report=str(report))))
    if not result['passed']:raise SystemExit(1)
if __name__=='__main__':main()
