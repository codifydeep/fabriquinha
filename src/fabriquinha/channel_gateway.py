"""Command-only embedding of the pinned Hermes Telegram adapter.

Hermes owns polling/delivery/reconnect. No GatewayRunner, cron, agent or Kanban
worker is started here; /fabrica invokes the existing scoped plugin handler.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
from .channel import authorize
from .channel_plugin import handle,private_json
from .source import verify
from .kanban_lane import UPSTREAM_COMMIT


class Commands:
    def __init__(self,policy):self.policy=policy

    def authorized(self,user_id,chat_type=None,chat_id=None,*,is_bot=False,thread_id=None):
        if is_bot:return False
        try:
            authorize(self.policy,dict(platform='telegram',user_id=str(user_id or ''),
                chat_type=chat_type,chat_id=str(chat_id or ''),thread_id=str(thread_id) if thread_id is not None else ''))
            return True
        except (ValueError,TypeError):return False

    async def message(self,event):
        if getattr(event,'internal',False) or not getattr(event,'allow_gateway_control',True):return None
        source=event.source
        if (source is None or not self.authorized(source.user_id,source.chat_type,source.chat_id,
                is_bot=source.is_bot,thread_id=source.thread_id)):return None
        if event.get_command()!='fabrica':return None
        from gateway.session_context import set_session_vars,clear_session_vars
        tokens=set_session_vars(platform='telegram',chat_id=str(source.chat_id),chat_type=source.chat_type,
            user_id=str(source.user_id),thread_id=str(source.thread_id) if source.thread_id is not None else '',
            message_id=str(event.message_id or ''))
        try:return await asyncio.to_thread(handle,event.get_command_args().strip())
        finally:clear_session_vars(tokens)


async def serve(config_path):
    config=private_json(config_path)
    if set(config)!={'channel_config','home','token_file'}:raise ValueError('fixed private gateway configuration required')
    channel=private_json(config['channel_config']);verify(channel['source'],channel['digest'])
    upstream=Path(channel['upstream'])
    if subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()!=UPSTREAM_COMMIT:
        raise ValueError('pinned native Telegram adapter required')
    if subprocess.check_output(['git','-C',str(upstream),'status','--porcelain'],text=True).strip():
        raise ValueError('unmodified Hermes upstream required')
    home=Path(config['home']).resolve();home.mkdir(mode=0o700,parents=True,exist_ok=True)
    if home.stat().st_mode&0o077:raise ValueError('private gateway home required')
    token_path=Path(config['token_file'])
    if token_path.is_symlink() or token_path.stat().st_mode&0o077:raise ValueError('private bot token file required')
    token=token_path.read_text().strip()
    import re
    if not re.fullmatch('[0-9]+:[A-Za-z0-9_-]+',token):raise ValueError('bot token format invalid')
    os.environ.update(HERMES_HOME=str(home),HERMES_DISABLE_LAZY_INSTALLS='1',FABRIQUINHA_CHANNEL_CONFIG=config['channel_config'])
    sys.path.insert(0,str(upstream))
    from gateway.config import PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter
    commands=Commands(private_json(channel['policy']))
    os.environ.update(TELEGRAM_ALLOWED_USERS=','.join(str(u) for u in commands.policy['user_ids']),
        TELEGRAM_ALLOWED_CHATS=str(commands.policy['chat_id']),TELEGRAM_REQUIRE_MENTION='true')
    adapter=TelegramAdapter(PlatformConfig(enabled=True,token=token,gateway_restart_notification=False,
        typing_indicator=False,extra=dict(drop_pending_on_cold_boot=False,unauthorized_dm_behavior='ignore')))
    adapter.set_authorization_check(commands.authorized);adapter.set_message_handler(commands.message)
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
    from .effects import write_json
    state=home/'channel-status.json'
    try:
        if not await adapter.connect():raise RuntimeError('native Telegram adapter could not connect')
        write_json(state,dict(state='running',pid=os.getpid(),mode='commands-only',source_digest=channel['digest']))
        while not stop.is_set():
            if adapter.has_fatal_error:raise RuntimeError('native Telegram adapter reported fatal transport error')
            try:await asyncio.wait_for(stop.wait(),timeout=2)
            except asyncio.TimeoutError:pass
    finally:
        await adapter.disconnect()
        write_json(state,dict(state='stopped',pid=os.getpid(),mode='commands-only'))


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True)
    args=parser.parse_args()
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    asyncio.run(serve(args.config))


if __name__=='__main__':main()
