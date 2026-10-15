"""Installed config + real ACP session, no prompt/model/credential authority."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
sys.path.insert(0,'/');sys.path.insert(0,'/opt/hermes')
import worker_model_config

home=Path('/tmp/hermes');home.mkdir(mode=0o700,exist_ok=True)
memory=home/'MEMORY.md';memory.write_text('preserved governed memory fixture\n')
worker_model_config.install_config(home,'00000000-0000-4000-8000-000000000001')
from hermes_cli.config import load_config_readonly
config=load_config_readonly()
assert config['memory']['nudge_interval']==0 and config['skills']['creation_nudge_interval']==0
assert config['auxiliary']['title_generation']['enabled'] is False
assert config['model']['default']=='anthropic/claude-haiku-5.5'
from agent.title_generator import _auto_title_enabled
assert _auto_title_enabled() is False
assert memory.read_text()=='preserved governed memory fixture\n'
for forbidden in ('/broker-state/token','/secret/openrouter.key','/var/run/docker.sock'):
    assert not Path(forbidden).exists()
process=subprocess.Popen(['python','/worker_model_config.py'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
pending=b''
def rpc(identifier,method,params):
    global pending
    process.stdin.write((json.dumps(dict(jsonrpc='2.0',id=identifier,method=method,params=params))+'\n').encode());process.stdin.flush()
    deadline=time.monotonic()+25
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout,selectors.EVENT_READ)
        while time.monotonic()<deadline:
            for key,_ in selector.select(timeout=1):
                chunk=key.fileobj.read1(65536)
                if not chunk:raise RuntimeError('unexpected ACP EOF')
                pending+=chunk;assert len(pending)<=1048576
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1)
                    try:frame=json.loads(line)
                    except ValueError:continue
                    if frame.get('id')==identifier:
                        assert 'error' not in frame;return frame['result']
    raise RuntimeError('observe same ACP qualification process; no automatic restart')
try:
    initialized=rpc(1,'initialize',dict(protocolVersion=1,clientCapabilities={},clientInfo=dict(name='governed-worker-probe',version='1')))
    assert initialized['protocolVersion']==1
    session=rpc(2,'session/new',dict(cwd='/tmp',mcpServers=[]));assert isinstance(session.get('sessionId'),str)
    print(json.dumps(dict(operation='governed_worker_config_acp_v1',config_loaded=True,acp_initialized=True,
        acp_session_created=True,memory_fixture_preserved=True,periodic_memory_review=False,
        periodic_skill_review=False,paid_auto_title=False,model_calls=0,prompt_executed=False,
        product_approved=False,full_delivery_qualified=False)))
finally:
    process.kill();process.communicate(timeout=5)
