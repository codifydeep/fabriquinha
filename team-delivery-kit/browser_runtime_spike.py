"""Controller-only fixed offline browser experiment on the historical image."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

from browser_evidence_trial import IMAGE, SOURCE, BROWSER
from evalctl import PRIVATE, PROJECT
from docker_grouping import args
from portable_browser_qa import docker, inspect, cleanup
from project_selection import current
from release_eval import save_receipt


def main():
    if PROJECT!='delivery-kit-port2' or current()['repository']!='codifydeep/descartavel2':
        raise ValueError('fixed isolated historical spike only')
    probe=Path(__file__).with_name('browser_runtime_probe.py')
    original=subprocess.check_output(['git','-C',str(current()['checkout']),
                                     'show',SOURCE+':app/static/app.js'])
    script_hash=hashlib.sha256(original).hexdigest()
    if inspect(IMAGE,'image')['Config']['Labels']['delivery-kit.source-sha']!=SOURCE:
        raise ValueError('immutable source image drift')
    folder=PRIVATE/'browser-runtime-spike'
    receipt_path=folder/'result.json'
    identity={'source_sha':SOURCE,'image':IMAGE,'browser_image':BROWSER,
              'script_sha256':script_hash,'probe_sha256':hashlib.sha256(probe.read_bytes()).hexdigest()}
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_text())
        if prior.get('identity')!=identity:raise ValueError('spike identity drift')
        return prior
    owner='delivery-kit-browser-spike-'+uuid.uuid4().hex
    resources=[('network',owner),('container',owner+'-app'),('container',owner+'-probe')]
    receipt={'identity':identity,'scope':'diagnostic_only_not_delivery','status':'running',
             'owner':owner,'resources':resources}
    save_receipt(folder/'intent.json',receipt)
    try:
        docker('network','create','--internal','--label','delivery-kit.browser-qa='+owner,owner)
        docker('run','-d','--name',owner+'-app','--network',owner,'--network-alias','fixture',
               *args('causal-spike-app',namespace=PROJECT),
               '--label','delivery-kit.browser-qa='+owner,'--read-only',
               '--tmpfs','/tmp:rw,nosuid,nodev,size=8m','--cap-drop','ALL',
               '--security-opt','no-new-privileges','--memory','128m','--pids-limit','64',
               '--env','FEEDBACK_DB_PATH=/tmp/feedback.db',IMAGE)
        for _ in range(30):
            ready=docker('exec',owner+'-app','python','-c',
                         'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=1)',check=False)
            if ready.returncode==0:break
            time.sleep(.2)
        else:raise ValueError('spike app startup deadline')
        result=docker('run','--name',owner+'-probe','--network',owner,
                      *args('causal-spike-browser',namespace=PROJECT),
                      '--label','delivery-kit.browser-qa='+owner,'--user','10000:10000',
                      '--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m',
                      '--env','HOME=/tmp','--env','EXPECTED_SCRIPT_SHA256='+script_hash,
                      '--env','EXPECTED_SOURCE_SHA='+SOURCE,'--cap-drop','ALL',
                      '--security-opt','no-new-privileges','--memory','768m','--cpus','1',
                      '--pids-limit','256','--shm-size','128m',
                      '--mount','type=bind,source='+str(probe)+',target=/probe.py,readonly',
                      '--entrypoint','python',BROWSER,'/probe.py',timeout=120)
        proof=json.loads(result.stdout)
        if (proof['status']!='causal_spike_passed' or proof['source_sha']!=SOURCE
                or proof['script_sha256']!=script_hash or proof['original_source_unchanged'] is not True):
            raise ValueError('spike proof drift')
        receipt.update(status='causal_spike_passed',proof=proof)
    except Exception as error:
        receipt.update(status='blocked',category=type(error).__name__+':'+str(error)[:1000])
        raise
    finally:
        try:
            cleanup(resources,owner);receipt['cleanup']='passed'
        except Exception:
            receipt.update(status='blocked',cleanup='failed');raise
        finally:save_receipt(receipt_path,receipt)
    return receipt


if __name__=='__main__':
    print(json.dumps(main()))
