"""Hermes slash-command seam: no shell, model turn, dispatcher or token access."""
import json
import os
from pathlib import Path
import subprocess
from .channel import command,session_identity,format_pending
from .source import verify


def private_json(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077:
        raise ValueError('private operator configuration required')
    return json.loads(path.read_bytes())


def handle(raw):
    # Return failures as handled text. Raising here would let the upstream
    # plugin exception path fall through to a conversational model turn.
    try:
        config=private_json(os.environ['FABRIQUINHA_CHANNEL_CONFIG'])
        if set(config)!={'source','digest','python','root','upstream','policy'}:
            raise ValueError('fixed channel installation binding required')
        identity=session_identity();policy=private_json(config['policy'])
        operation=command(raw,policy,identity)  # Reject before spawning a subprocess.
        verify(Path(config['source']),config['digest'])
        env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG')}
        env.update(PYTHONPATH=str(Path(config['source'])/'src'),PYTHONNOUSERSITE='1',
            PYTHONDONTWRITEBYTECODE='1',PYTHONSAFEPATH='1',FABRIQUINHA_SOURCE_DIGEST=config['digest'])
        result=subprocess.run([config['python'],'-B','-m','fabriquinha.channel',
            '--root',config['root'],'--upstream',config['upstream'],'--policy',config['policy']],
            input=json.dumps(dict(raw=raw,identity=identity)),capture_output=True,text=True,
            timeout=30,env=env,check=False)
        if result.returncode:return 'Command not completed. Check the exact card/request and operator status; no delivery approval is implied.'
        if operation['operation']=='show':return format_pending(json.loads(result.stdout))
        return result.stdout.strip() or 'No pending product question for this card.'
    except subprocess.TimeoutExpired:
        return 'Outcome not confirmed. Check status before resending; do not assume approval or failure.'
    except Exception:
        return 'Command refused. Use an authorized Telegram account/group and an exact card/request. No action was approved.'


def register(ctx):
    ctx.register_command('fabrica',handle,description='Fabriquinha: status, product intake and scoped responses',
        args_hint='status | show CARD | start LABEL OBJECTIVE | approve|changes|answer CARD HASH TEXT')
