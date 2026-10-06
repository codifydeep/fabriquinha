"""Run the fixed recovery canary in the installed proxy image, without its mounts."""
import json
import subprocess
import uuid
from evalctl import PROJECT,PRIVATE
from release_eval import save_receipt


def main():
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated recovery probe required')
    image=subprocess.check_output(['docker','inspect',PROJECT+'-model-proxy-1','--format','{{.Image}}'],text=True).strip()
    identifier=str(uuid.uuid4())
    command=['docker','run','--rm','--name',PROJECT+'-read-recovery-probe-'+identifier,
        '--label','com.docker.compose.project='+PROJECT+'-tests','--label','com.docker.compose.service=read-recovery-probe',
        '--network','none','--read-only','--user','10000:10000','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--memory','128m','--pids-limit','32',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=16m,mode=1777','--entrypoint','python',image,'/read_stream_recovery_probe.py']
    p=subprocess.run(command,capture_output=True,text=True,timeout=60)
    if p.returncode:raise RuntimeError('fixed isolated read recovery probe failed; raw output suppressed')
    result=json.loads(p.stdout);result.update(execution_id=identifier,proxy_image=image,fixture_removed=True)
    save_receipt(PRIVATE/'provider-probes'/('read-recovery-'+identifier+'.json'),result)
    save_receipt(PRIVATE/'read-stream-recovery-probe.json',result)
    print(json.dumps(result))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
