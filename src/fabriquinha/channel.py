"""Deterministic human channel adapter; never an agent tool or workflow owner."""
from contextvars import copy_context
import re
from .artifacts import digest


def session_identity():
    """Use request-bound Hermes ContextVars only, never stale process env."""
    names=('PLATFORM','CHAT_ID','CHAT_TYPE','THREAD_ID','USER_ID','MESSAGE_ID')
    values={v.name:value for v,value in copy_context().items() if isinstance(value,str)}
    return {name.lower():values.get('HERMES_SESSION_'+name,'') for name in names}


def authorize(policy,identity):
    if (not isinstance(policy,dict) or set(policy)!={'version','chat_id','user_ids','thread_id'}
            or policy['version']!=1 or not re.fullmatch('-?[0-9]{1,22}',str(policy['chat_id']))
            or not isinstance(policy['user_ids'],list) or not policy['user_ids']
            or any(not re.fullmatch('[1-9][0-9]{0,21}',str(user)) for user in policy['user_ids'])
            or policy['thread_id'] is not None and (type(policy['thread_id']) is not int or policy['thread_id']<1)):
        raise ValueError('explicit private human channel policy required')
    if (identity.get('platform')!='telegram' or identity.get('chat_type') not in ('group','supergroup')
            or identity.get('chat_id')!=str(policy['chat_id'])
            or identity.get('user_id') not in {str(u) for u in policy['user_ids']}
            or identity.get('thread_id','')!=(str(policy['thread_id']) if policy['thread_id'] is not None else '')):
        raise ValueError('authorized human and exact Telegram destination required')


def command(raw,policy,identity):
    """Parse only explicit commands; a conversational yes never grants consent."""
    authorize(policy,identity)
    if not isinstance(raw,str) or not 0<len(raw)<=24000:raise ValueError('bounded command required')
    operation,_,arguments=raw.strip().partition(' ')
    if operation=='status' and not arguments:return dict(operation='status')
    if operation=='show' and re.fullmatch('t_[a-f0-9]{8}',arguments):
        return dict(operation='show',task=arguments)
    if operation=='start':
        label,_,objective=arguments.partition(' ')
        if (not re.fullmatch('[A-Za-z0-9._-]{1,80}',label) or not objective.strip()
                or not re.fullmatch('[1-9][0-9]*',identity.get('message_id',''))):
            raise ValueError('start needs label, objective and bound message identity')
        return dict(operation='start',value=dict(request='telegram-'+digest(identity),label=label,objective=objective.strip()))
    if operation in ('approve','changes','answer'):
        parts=arguments.split(' ',2)
        if (len(parts)!=3 or not re.fullmatch('t_[a-f0-9]{8}',parts[0])
                or not re.fullmatch('[a-f0-9]{64}',parts[1]) or not parts[2].strip()):
            raise ValueError('response needs card, exact request hash and explicit text')
        return dict(operation='respond',task=parts[0],expected=parts[1],decision=operation,answer=parts[2].strip())
    raise ValueError('use status, show CARD, start LABEL OBJECTIVE or approve|changes|answer CARD HASH TEXT')


def execute(runtime,value):
    """Runtime lives in a separate process: Hermes binding changes process env."""
    operation=value['operation']
    if operation=='status':
        status=runtime.status()
        return dict(paused=status.get('control',{}).get('paused'),
            cards=[{k:card[k] for k in ('id','title','kind','status','assignee','current_run_id') if k in card}
                   for card in status.get('cards',[])])
    if operation=='show':
        from .kanban_lane import native
        _,kbc,_=native()
        with kbc.connect_closing() as conn:return runtime.intake.pending(conn,value['task'])
    runtime.control.ensure()
    if operation=='start':return runtime.intake.start(value['value'])
    if operation=='respond':
        return runtime.intake.respond(value['task'],value['expected'],value['decision'],value['answer'])
    raise ValueError('fixed channel operation required')


def main():
    import argparse
    import json
    from pathlib import Path
    import sys
    from .runtime import Runtime
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    args=parser.parse_args()
    if args.policy.is_symlink() or args.policy.stat().st_mode&0o077:
        raise ValueError('private channel policy required')
    request=json.loads(sys.stdin.read(32769))
    if not isinstance(request,dict) or set(request)!={'raw','identity'}:raise ValueError('fixed channel request required')
    value=command(request['raw'],json.loads(args.policy.read_bytes()),request['identity'])
    runtime=Runtime(args.root,args.upstream)
    print(json.dumps(execute(runtime,value),ensure_ascii=False))


if __name__=='__main__':main()
