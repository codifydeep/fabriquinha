"""Native Hermes context -> scoped plugin -> real paused runtime subprocess.

No Telegram network, model calls, delivery approval or production installation.
This validates the seam, not the final human round trip.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.effects import write_json
from fabriquinha.source import freeze


def qualify(root,upstream,revision):
    root=root.resolve();upstream=upstream.resolve()
    if root.exists():raise ValueError('fresh private qualification root required')
    root.mkdir(mode=0o700,parents=True)
    exported=freeze(ROOT,root/'source',revision)
    installation=root/'installation';installation.mkdir(mode=0o700)
    write_json(installation/'project.json',dict(version=1,namespace='delivery-kit-channel-proof',
        repository='https://github.com/example/product',branch='release/fixture',
        validation_image='sha256:'+'a'*64,tests_dir='tests',reviewers={'backend':'lead','lead':'cto'},qualification=True))
    write_json(root/'policy.json',dict(version=1,chat_id='-123',user_ids=['456'],thread_id=None))
    write_json(root/'channel.json',dict(source=str(root/'source'),digest=exported['source_digest'],
        python=sys.executable,root=str(installation),upstream=str(upstream),policy=str(root/'policy.json')))
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','TMPDIR','LANG')}
    env.update(PYTHONPATH=os.pathsep.join([str(root/'source/src'),str(upstream)]),
        PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONSAFEPATH='1',
        FABRIQUINHA_SOURCE_DIGEST=exported['source_digest'],FABRIQUINHA_CHANNEL_CONFIG=str(root/'channel.json'))
    code='''
import json,os,sys
from fabriquinha.runtime import Runtime
r=Runtime(sys.argv[1],sys.argv[2]);r.control.pause()
from gateway.session_context import set_session_vars,clear_session_vars
from fabriquinha.channel_plugin import handle
before={k:os.environ.get(k) for k in ('HERMES_HOME','HERMES_KANBAN_DB')}
tokens=set_session_vars(platform='telegram',chat_id='-123',chat_type='group',user_id='456',message_id='10')
try:
    status=json.loads(handle('status'));assert status['paused'] and status['cards']==[]
    assert 'not completed' in handle('start v1 Should stay paused')
finally:clear_session_vars(tokens)
os.environ['HERMES_SESSION_USER_ID']='456'
assert 'refused' in handle('status')
tokens=set_session_vars(platform='telegram',chat_id='-123',chat_type='group',user_id='999',message_id='11')
try:assert 'refused' in handle('status')
finally:clear_session_vars(tokens)
from fabriquinha.channel_gateway import Commands
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource
from gateway.config import Platform
import asyncio
commands=Commands(dict(version=1,chat_id='-123',user_ids=['456'],thread_id=None))
event=MessageEvent(text='/fabrica status',source=SessionSource(platform=Platform.TELEGRAM,
    chat_id='-123',chat_type='group',user_id='456'),message_id='12')
assert json.loads(asyncio.run(commands.message(event)))['paused']
event.allow_gateway_control=False
assert asyncio.run(commands.message(event)) is None
assert before=={k:os.environ.get(k) for k in before}
from fabriquinha.kanban_lane import native
_,kbc,_=native()
with kbc.connect_closing() as conn:assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0
print(json.dumps(dict(passed=True,native_context=True,native_message_event=True,real_status_subprocess=True,paused_mutation_refused=True,
    stale_environment_refused=True,wrong_user_refused=True,gateway_environment_preserved=True,
    telegram_messages=0,model_calls=0,delivery_approval=False)))
'''
    reply=subprocess.run([sys.executable,'-B','-c',code,str(installation),str(upstream)],env=env,
        capture_output=True,text=True,timeout=60)
    write_json(root/'process.json',dict(code=reply.returncode,stdout=reply.stdout,stderr=reply.stderr))
    if reply.returncode:raise RuntimeError('native channel qualification failed; inspect private diagnostics')
    result=json.loads(reply.stdout);write_json(root/'result.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--upstream',type=Path,required=True);p.add_argument('--revision',required=True)
    args=p.parse_args();print(json.dumps(qualify(args.root,args.upstream,args.revision),indent=2))
