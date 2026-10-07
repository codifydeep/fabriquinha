"""Installed Hermes ACP initialize canary. Never sends a session or prompt.

Run in a network-none, credential-free, socket-free disposable image. This
proves real initialization only, not native handoff or autonomous delivery.
"""
import json
import os
from pathlib import Path
import selectors
import subprocess
import time


def main():
    if Path('/var/run/docker.sock').exists() or Path('/secret').exists():
        raise ValueError('credential-free isolated probe required')
    from acp_transport import worker_env
    environment=os.environ.copy()
    for key in list(environment):
        if any(value in key for value in ('TOKEN','API_KEY','PASSWORD','SECRET')):
            environment.pop(key)
    environment.update(dict(v.split('=',1) for v in worker_env('planning',False)))
    child=subprocess.Popen(['python','/worker_model_config.py'],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=environment)
    selector=selectors.DefaultSelector();selector.register(child.stdout,selectors.EVENT_READ)
    try:
        child.stdin.write(json.dumps(dict(jsonrpc='2.0',id='initialize-probe',method='initialize',
            params=dict(protocolVersion=1,clientCapabilities={},clientInfo=dict(name='offline-startup-probe',version='1')))).encode()+b'\n')
        child.stdin.flush()
        deadline=time.monotonic()+30;buffer=b'';result=None;frames=0
        while time.monotonic()<deadline and result is None:
            if not selector.select(min(1,max(0,deadline-time.monotonic()))):continue
            chunk=os.read(child.stdout.fileno(),65536)
            if not chunk:raise RuntimeError('real ACP exited before initialize')
            buffer+=chunk
            if len(buffer)>65536:raise ValueError('ACP initialize output bound')
            while b'\n' in buffer:
                line,buffer=buffer.split(b'\n',1);frames+=1
                if frames>100:raise ValueError('ACP initialize frame bound')
                message=json.loads(line)
                if message.get('id')=='initialize-probe':
                    if 'error' in message:raise RuntimeError('real ACP rejected initialize')
                    result=message['result'];break
        if not isinstance(result,dict) or result.get('protocolVersion')!=1 or not isinstance(result.get('agentCapabilities'),dict):
            raise RuntimeError('real ACP initialize not qualified')
        print(json.dumps(dict(schema='real-acp-initialize-probe-v1',status='passed',
            actual_hermes_initialize=True,prompts_sent=0,sessions_created=0,
            network='none',socket_absent=True,delivery_approval=False)))
    finally:
        selector.close();child.stdin.close()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)


if __name__=='__main__':main()
