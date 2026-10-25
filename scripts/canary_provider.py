"""One explicitly authorized small inference; never starts agents or retries.

Run only after a human authorizes archiving the existing financial pause. The
credential stays in its read-only Docker volume; stdout contains metadata only.
"""
import argparse
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.artifacts import digest
from fabriquinha.effects import write_json
from fabriquinha.provider import Ledger,Policy,Relay


def one(meter,key,authorization,model,expected,limit):
    if not re.fullmatch('[a-f0-9]{32}',authorization) or type(expected) is not int or not 0<=expected<limit:
        raise ValueError('explicit one-shot authorization and monotonic counter required')
    ledger=Ledger(meter,limit);folder=Path(meter)/'canaries'/authorization
    policy=Policy.parse(dict(version=1,project=digest(['provider-canary',authorization]),model=model,max_calls=limit,
        max_output_tokens=2048,enabled=True,client_token=secrets.token_urlsafe(32)))
    app=Relay(policy,meter,key)
    with ledger.owner():
        before=ledger.state()
        if before['calls']!=expected or before['relay_hold'] or not before['provider_pause'] or before['provider_pause']['upstream_status']!=402:
            raise ValueError('counter/pause changed; do not attempt inference')
        if folder.exists():raise ValueError('authorization already observed; never retry blindly')
        if not app.status().get('credential_present'):raise ValueError('credential unavailable; preserve pause without attempting inference')
        folder.mkdir(mode=0o700,parents=True)
        write_json(folder/'intent.json',dict(authorization=authorization,model=model,before=before,attempt_limit=1,output_limit=128))
        ledger.save(str(folder.relative_to(meter)/'pause-before.json'),before['provider_pause'])
        # Exact marker only, after its restricted durable archive. Counter and
        # existing meter history are untouched. No reset or automatic retry.
        pause=Path(meter)/'provider-pause.json'
        if ledger.read('provider-pause.json')!=before['provider_pause']:raise ValueError('pause changed before archive transition')
        pause.unlink()
        body=dict(model=model,stream=False,max_tokens=128,messages=[dict(role='user',content='Reply with exactly OK. Do not call tools.')])
        status,data=app.handle('Bearer '+policy.client_token,json.dumps(body).encode())
        after=ledger.state();valid=False;usage=None
        if status==200:
            try:
                reply=json.loads(data);message=reply['choices'][0]['message']
                valid=message.get('content','').strip()=='OK' and not message.get('tool_calls')
                usage={name:value for name,value in (reply.get('usage') or {}).items()
                       if name in ('prompt_tokens','completion_tokens','total_tokens') and type(value) is int}
            except (ValueError,KeyError,IndexError,TypeError,AttributeError):pass
        result=dict(status=status,valid_reply=valid,model=model,calls_before=expected,calls_after=after['calls'],
            attempts_reserved=after['calls']-expected,max_calls=limit,provider_pause=after['provider_pause'],
            relay_hold=after['relay_hold'],usage=usage,tools_executed=0,retries=0,agents_started=0)
        if after['calls']-expected not in (0,1):raise RuntimeError('one-call invariant violated')
        ledger.save(str(folder.relative_to(meter)/'receipt.json'),result)
        print(json.dumps(result),flush=True)
        return result


def run(root,image,authorization,model,expected,limit):
    sys.path.insert(0,str(ROOT/'team-delivery-kit'))
    from docker_grouping import args as grouping
    if root.exists():raise ValueError('fresh private canary root required; observe prior intent instead of rerunning')
    if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('cached image digest required')
    old='delivery-kit-port2-model-proxy-1'
    state=subprocess.run(['docker','inspect','--format','{{.State.Running}}',old],capture_output=True,text=True,check=True).stdout.strip()
    if state!='false':raise ValueError('old meter writer is not stopped; preserve it and do not infer')
    root.mkdir(mode=0o700,parents=True)
    name='delivery-kit-hermes-provider-canary-'+authorization[:12]
    write_json(root/'intent.json',dict(container=name,authorization=authorization,model=model,expected_calls=expected,max_calls=limit,attempt_limit=1))
    command=['docker','run','--rm','--name',name,*grouping('canary','delivery-kit-hermes-provider'),
        '--read-only','--user','10000:10000','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--memory','128m','--cpus','0.5','--pids-limit','32','--log-opt','max-size=1m','--log-opt','max-file=2',
        '--env','PYTHONPATH=/opt/src','--entrypoint','python',
        '--mount','type=bind,src='+str(ROOT/'src')+',dst=/opt/src,readonly',
        '--mount','type=bind,src='+str(Path(__file__).resolve())+',dst=/opt/canary.py,readonly',
        '--mount','type=volume,src=delivery-kit-port2_model_meter,dst=/meter',
        '--mount','type=volume,src=delivery-kit-port2_model_secret,dst=/secret,readonly',image,
        '-B','/opt/canary.py','--worker','--authorization',authorization,'--model',model,
        '--expect-calls',str(expected),'--max-calls',str(limit)]
    try:result=subprocess.run(command,capture_output=True,text=True,timeout=180)
    except subprocess.TimeoutExpired:
        write_json(root/'observation-pending.json',dict(container=name,authorization=authorization,retry_allowed=False));raise
    write_json(root/'output.json',dict(returncode=result.returncode,stdout=result.stdout[:8192],stderr=result.stderr[:8192]))
    if result.returncode:raise RuntimeError('canary worker ended; inspect private output, never replay automatically')
    receipt=json.loads(result.stdout);write_json(root/'receipt.json',receipt)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worker',action='store_true')
    parser.add_argument('--root',type=Path);parser.add_argument('--image');parser.add_argument('--authorization',required=True)
    parser.add_argument('--model',required=True);parser.add_argument('--expect-calls',type=int,required=True);parser.add_argument('--max-calls',type=int,required=True)
    args=parser.parse_args()
    if args.worker:one(Path('/meter'),Path('/secret/openrouter.key'),args.authorization,args.model,args.expect_calls,args.max_calls)
    else:print(json.dumps(run(args.root.resolve(),args.image,args.authorization,args.model,args.expect_calls,args.max_calls),indent=2))
