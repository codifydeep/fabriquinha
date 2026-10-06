"""Register a source-bound CTO proposal; never launch an author correction."""
import argparse
import json
import subprocess
import uuid
from evalctl import PRIVATE,PROJECT
from start_eval import read_model_budget
from release_eval import save_receipt


def main():
    parser=argparse.ArgumentParser();parser.add_argument('source_task')
    parser.add_argument('--repair-task');parser.add_argument('--previous-proxy-image')
    parser.add_argument('--capture-stream-failure',action='store_true');parser.add_argument('--stream-repair',action='store_true');args=parser.parse_args()
    if str(uuid.UUID(args.source_task))!=args.source_task:raise ValueError('canonical source required')
    if PROJECT!='delivery-kit-port2' or read_model_budget()['remaining']<32:
        raise ValueError('isolated diagnostic reserve required')
    payload={'source_task':args.source_task};endpoint='/v1/test-decomposition'
    if args.repair_task:
        if str(uuid.UUID(args.repair_task))!=args.repair_task or (not args.previous_proxy_image and not args.capture_stream_failure):
            raise ValueError('exact previous CTO and historical proxy identities required')
        if args.capture_stream_failure:
            payload['previous_task']=args.repair_task;endpoint='/v1/test-decomposition-stream-failure'
        else:
            payload.update(previous_task=args.repair_task,previous_proxy_image=args.previous_proxy_image,
                           probe=json.loads((PRIVATE/'acp-decomposition-probe.json').read_text()))
            if args.stream_repair:payload['probe']['read_stream_recovery']=json.loads((PRIVATE/'read-stream-recovery-probe.json').read_text())
            endpoint='/v1/test-decomposition-transport-repair'
    elif args.capture_stream_failure or args.stream_repair:raise ValueError('exact stream recipient required')
    script='''import json,sys,urllib.request,urllib.error,hashlib
from pathlib import Path
p=json.load(sys.stdin)
r=urllib.request.Request('http://127.0.0.1:8090'+sys.argv[1],data=json.dumps(p).encode(),headers={'Authorization':'Bearer '+Path('/broker-state/token').read_text(),'Content-Type':'application/json'})
try:
 d=json.load(urllib.request.urlopen(r,timeout=120))
 print(json.dumps({'registered':True,'stage':d.get('stage','transport_repair_registered'),'source_task':p['source_task'],'execution_authorized':False}))
except urllib.error.HTTPError as e:
 print(json.dumps({'registered':False,'http_status':e.code,'category':'controller_registration_rejected'}));sys.exit(1)
'''
    p=subprocess.run(['docker','exec','-i',PROJECT+'-execution-broker-1','python','-c',script,endpoint],
        input=json.dumps(payload),text=True,capture_output=True)
    if p.returncode:raise RuntimeError('decomposition registration rejected; no raw output forwarded')
    result=json.loads(p.stdout)
    suffix=('-stream-failure' if args.capture_stream_failure else '-stream-repair' if args.stream_repair else
        {'acp-decomposition-probe-v4':'-deterministic-repair','acp-decomposition-probe-v3':'-allocation-repair','acp-decomposition-probe-v2':'-reader-repair'}.get(payload.get('probe',{}).get('schema'),'-transport-repair')) if args.repair_task else ''
    save_receipt(PRIVATE/'test-decompositions'/(args.source_task+suffix+'.json'),result)
    print(json.dumps(result))


if __name__=='__main__':main()
