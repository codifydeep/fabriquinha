"""Operator registration of one ACP-qualified preserved SEARCHUI recovery."""
import json
import subprocess

from evalctl import PRIVATE, PROJECT
from release_eval import save_receipt
from start_eval import read_model_budget

# Exact proxy observed during the archived real ACP qualification.
QUALIFIED_PROXY = 'sha256:95938fdfabe7732bb9d57953d2de2d710786bce0b3cc40541d3469b1e6435ce9'
PROBE = '2397f69a-f539-4860-9e91-553ed33be636'


def main():
    if PROJECT != 'delivery-kit-port2' or read_model_budget()['remaining'] < 32:
        raise ValueError('isolated recovery reserve required')
    proof = json.loads((PRIVATE / 'provider-probes' / ('acp-' + PROBE + '.json')).read_text())
    if proof.get('execution_id') != PROBE:
        raise ValueError('qualification identity mismatch')
    proof['proxy_image'] = QUALIFIED_PROXY
    payload = {'issue_id': '01a0fc34-fa97-70ce-bcdb-5c48b62fdb42',
               'source_task': '01a0febb-a125-714b-a836-82d4128096fe', 'probe': proof}
    script = '''import json,sys,urllib.request,urllib.error,hashlib
from pathlib import Path
p=json.load(sys.stdin)
r=urllib.request.Request('http://127.0.0.1:8090/v1/test-first-transport-recovery',data=json.dumps(p).encode(),headers={'Authorization':'Bearer '+Path('/broker-state/token').read_text(),'Content-Type':'application/json'})
try:
 d=json.load(urllib.request.urlopen(r,timeout=120))
 print(json.dumps({'registered':True,'kind':d['kind'],'source_task':d['request']['source_task'],'cto_task':d['cto_task'],'diagnostic_sha256':d['diagnostic_sha256'],'receipt_sha256':hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()}))
except urllib.error.HTTPError as e:
 print(json.dumps({'registered':False,'http_status':e.code}));sys.exit(1)
'''
    process = subprocess.run(['docker', 'exec', '-i', PROJECT + '-execution-broker-1', 'python', '-c', script],
                             input=json.dumps(payload), text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError('ACP recovery registration rejected: ' + process.stdout.strip())
    receipt = json.loads(process.stdout)
    save_receipt(PRIVATE / 'acp-artifact-recovery.json', receipt)
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
