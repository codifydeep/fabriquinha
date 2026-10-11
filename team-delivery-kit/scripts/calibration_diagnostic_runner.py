"""Explicitly authorized, bounded diagnostic; no native workflow transitions.

Input is privately exported by the controller after verifying snapshot ownership.
Raw replies and read pages stay in a private experiment directory. Proxy calls
are not repeated after an unknown acknowledgment or transport failure.
"""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calibration_diagnostic_probe import build,summarize_reply
from docker_grouping import args as group_args

IMAGE='sha256:358a4862d9d9a2fbdb95653f3e54e3b10680ed8f18893ff036e61583b857c16b'
PROXY='delivery-kit-port2-model-proxy-1'
TRANSPORT='''import sys,json,base64,urllib.request,urllib.error
sys.path.insert(0,"/");import model_proxy as p
v=json.load(sys.stdin);before=p.load_calls()
r=urllib.request.Request("http://127.0.0.1:8080/executions/"+v["experiment"]+"/api/v1/chat/completions",data=json.dumps(v["body"]).encode(),headers={"Authorization":p.PLACEHOLDER,"Content-Type":"application/json"})
try:
 with urllib.request.urlopen(r,timeout=150) as response:status=response.status;data=response.read()
except urllib.error.HTTPError as e:status=e.code;data=e.read()
print(json.dumps({"status":status,"data":base64.b64encode(data).decode(),"calls_before":before,"calls_after":p.load_calls()}))
'''


def command(argv,value,timeout):
    result=subprocess.run(argv,input=json.dumps(value),text=True,capture_output=True,timeout=timeout)
    if result.returncode:raise ValueError('diagnostic operation failed; do not repeat unknown effects')
    return json.loads(result.stdout)


def save(root,name,value):
    with os.fdopen(os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as file:
        json.dump(value,file,sort_keys=True)


def reader_code(operation='page'):
    if operation not in ('page','complete'):raise ValueError('fixed reader operation required')
    module=Path(__file__).resolve().parents[1];code='import sys,json,types\n'
    for name in ('artifact_read_evidence','calibration_response_contract','calibration_diagnostic_read'):
        text=(module/(name+'.py')).read_text()
        code+='m=types.ModuleType('+repr(name)+');sys.modules['+repr(name)+']=m;exec('+repr(text)+',m.__dict__)\n'
    return code+('v=json.load(sys.stdin);print(json.dumps(m.page(v["args"],v["manifest"])))'
        if operation=='page' else
        'v=json.load(sys.stdin);print(json.dumps([m.complete(p,v["manifest"]) for p in v["paths"]]))')


def main():
    source=json.load(sys.stdin)
    for role in ('candidate','previous'):
        if not re.fullmatch(r'delivery-kit-port2-test-first-[a-f0-9-]{36}',source[role+'_volume']):
            raise ValueError('exact owned test-first volume required')
    if not re.fullmatch('[a-f0-9]{64}',source['candidate_manifest_sha256']):
        raise ValueError('controller candidate manifest hash required')
    experiment=str(uuid.uuid4())
    body,receipt=build(source['note'],source['reads'],'anthropic/claude-haiku-5.5',
        experiment,source['source_task'])
    root=Path(__file__).resolve().parents[1]/'.local-port2'/'diagnostic-probes'/experiment
    root.mkdir(parents=True,mode=0o700)
    save(root,'input.json',source);save(root,'identity.json',receipt)
    # Modules are injected as source into a networkless, read-only helper. No
    # project source is imported or executed; only this fixed reader runs.
    code=reader_code()
    manifests={'candidate':source['candidate_manifest_sha256'],'previous':None}
    seen=set();events=[]
    for iteration in range(1,5):
        save(root,str(iteration)+'-request.json',body)
        wire=command(['docker','exec','-i','-w','/',PROXY,'python','-c',TRANSPORT],
            {'experiment':experiment,'body':body},160)
        save(root,str(iteration)+'-transport.json',wire)
        if wire['calls_after']-wire['calls_before']!=1:
            raise ValueError('unexpected diagnostic call count; no automatic replay')
        event={'iteration':iteration,'http_status':wire['status'],
            'call_number':wire['calls_after']}
        if wire['status']!=200:
            events.append(event);break
        data=base64.b64decode(wire['data']);summary=summarize_reply(body,data)
        event.update(summary);events.append(event)
        if not summary['requested_reads'] or iteration==4:break
        reply=json.loads(data)['choices'][0]['message'];body['messages'].append(reply)
        for call in reply['tool_calls']:
            request=json.loads(call['function']['arguments']);key=json.dumps(request,sort_keys=True)
            if key in seen:raise ValueError('repeated diagnostic read without progress')
            seen.add(key);role=request['path'].split('/')[2]
            name='delivery-kit-port2-diagnostic-'+experiment[:8]+'-'+str(len(seen))
            save(root,'read-'+str(len(seen))+'-intent.json',{'container':name,'request':request,
                'volume':source[role+'_volume'],'image':IMAGE,'read_only':True})
            read=command(['docker','run','--rm','--name',name,
                *group_args('calibration-diagnostic','delivery-kit-port2'),
                '--label','delivery-kit.owner=delivery-kit-port2',
                '--label','delivery-kit.diagnostic-experiment='+experiment,
                '--network','none','--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges','--pids-limit','32','--memory','128m',
                '--cpus','0.5','--mount','type=volume,src='+source[role+'_volume']+
                    ',dst=/evidence/'+role+',readonly',
                '-i','--entrypoint','python',IMAGE,'-I','-S','-B','-c',code],
                {'args':request,'manifest':manifests[role]},30)
            manifests[role]=read['manifest_sha256']
            save(root,'read-'+str(len(seen))+'.json',{'request':request,**read})
            body['messages'].append({'role':'tool','tool_call_id':call['id'],'content':read['output']})
    result={'experiment':receipt,'events':events,'model_calls':len(events),
        'local_read_pages':len(seen),'execution_authorized':False,'delivery_approval':False,
        'workflow_transition':False}
    save(root,'result.json',result)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps({'diagnostic_failed':True,'automatic_replay':False,
            'workflow_transition':False}),flush=True)
        sys.exit(1)
