"""Explicit idle-only model migration through the native API, without dispatch.

Only runtime-bound agents in this installation are eligible. Historical task
receipts, instructions, tools, concurrency and unrelated runtimes are untouched.
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from bootstrap_multica import API, AUTH, PRIVATE, request
from evalctl import PROJECT
from model_policy import MODEL, PREVIOUS_MODEL


def targets(agents, runtime_id):
    selected=[a for a in agents if a.get('runtime_id')==runtime_id and a.get('model')]
    if not selected:raise ValueError('no owned model-bound agents')
    if any(a.get('model') not in (MODEL,PREVIOUS_MODEL) for a in selected):
        raise ValueError('unexpected model; explicit migration scope required')
    return selected


def owned_runtimes(runtimes, namespace, primary):
    ids={r['id'] for r in runtimes if r.get('provider')=='hermes' and
         r.get('device_info','').split(' · ',1)[0]==namespace}
    if primary not in ids:raise ValueError('owned primary Hermes runtime required')
    return ids


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    token=json.loads(AUTH.read_text())['token']
    workspace=json.loads((PRIVATE/'workspace.json').read_text())['id']
    runtime_id=json.loads((PRIVATE/'native.json').read_text())['runtime_id']
    runtimes=request('/api/runtimes/',token=token,workspace=workspace)
    ids=owned_runtimes(runtimes,PROJECT,runtime_id)
    inventory=request('/api/agents/',token=token,workspace=workspace)
    agents=[a for identity in sorted(ids) for a in targets(inventory,identity)]
    print(json.dumps({'model':MODEL,'previous_model':PREVIOUS_MODEL,
                      'agents':len(agents),'dispatch_performed':False}),flush=True)
    if not args.apply:return
    state=json.loads(subprocess.check_output([sys.executable,
        str(Path(__file__).with_name('controller_maintenance_cli.py')),
        '--namespace',PROJECT,'--action','status'],text=True))
    if not state or state.get('stage')!='sealed' or state.get('namespace')!=PROJECT:
        raise ValueError('sealed controller maintenance required')
    for agent in agents:
        tasks=request('/api/agents/'+agent['id']+'/tasks',token=token,workspace=workspace)
        if any(t.get('status') in ('pending','queued','running') for t in tasks):
            raise ValueError('agent has active work; migration deferred')
    updated=0
    for agent in agents:
        if agent['model']==MODEL:continue
        call=urllib.request.Request(API+'/api/agents/'+agent['id']+'/',
            data=json.dumps({'model':MODEL}).encode(),method='PUT',
            headers={'Authorization':'Bearer '+token,'X-Workspace-ID':workspace,
                     'Content-Type':'application/json'})
        with urllib.request.urlopen(call,timeout=15) as response:result=json.load(response)
        if result.get('model')!=MODEL or result.get('runtime_id')!=agent['runtime_id']:
            raise ValueError('agent model update not confirmed')
        for key in ('instructions','max_concurrent_tasks','visibility'):
            if result.get(key)!=agent.get(key):raise ValueError('unrequested agent field changed')
        updated+=1
    inventory=request('/api/agents/',token=token,workspace=workspace)
    verified=[a for identity in sorted(ids) for a in targets(inventory,identity)]
    if any(a['model']!=MODEL for a in verified):raise ValueError('model migration incomplete')
    print(json.dumps({'updated':updated,'verified':len(verified),'model':MODEL,
                      'dispatch_performed':False}))


if __name__=='__main__':main()
