"""Register the preserved SEARCHUI provider repair using the synthetic receipt."""
import json
import subprocess
from evalctl import PRIVATE, PROJECT


def main():
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('isolated port2 only')
    proof = json.loads((PRIVATE / 'artifact-provider-probe.json').read_text())
    payload = {'issue_id': '01a0fc34-fa97-70ce-bcdb-5c48b62fdb42',
               'failed_task': '01a0fea2-e91d-7d00-b498-3893a48f8976', 'probe': proof}
    script = '''import json,sys,urllib.request;from pathlib import Path
p=json.load(sys.stdin)
r=urllib.request.Request('http://127.0.0.1:8090/v1/test-first-provider-recovery',data=json.dumps(p).encode(),headers={'Authorization':'Bearer '+Path('/broker-state/token').read_text(),'Content-Type':'application/json'})
d=json.load(urllib.request.urlopen(r,timeout=120))
print(json.dumps({'registered':True,'kind':d['kind'],'failed_task':d['request']['failed_task'],'original_source':d['original_source']}))
'''
    subprocess.run(['docker', 'exec', '-i', PROJECT + '-execution-broker-1', 'python', '-c', script],
                   input=json.dumps(payload), text=True, check=True)


if __name__ == '__main__':
    main()
