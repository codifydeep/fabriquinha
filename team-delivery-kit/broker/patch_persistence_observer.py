"""Bounded before/after facts for the existing handler, never write authority."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat

SOURCE_SHA='5b28b4de9711e50b4ead0422dac4eb04bd141d55f49d4e33bb9cfd77104e9019'
FIELD='_patch_persistence_v1'


def observe(path,root='/workspace'):
    """Open each path component without following links; never return content."""
    fd=None
    try:
        p=Path(path);base=Path(root);parts=p.relative_to(base).parts
        if (not p.is_absolute() or len(parts)<2 or parts[0]!='tests'
                or any(v in ('..','.') for v in parts) or p.suffix!='.py'):return None
        fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        child=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        os.close(fd);fd=child
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<=info.st_size<=32768:return None
        data=os.read(fd,32769);after=os.fstat(fd)
        if (len(data)>32768 or len(data)!=info.st_size or info.st_mtime_ns!=after.st_mtime_ns
                or info.st_size!=after.st_size):return None
        return dict(path='/'.join(parts),sha256=hashlib.sha256(data).hexdigest())
    except (OSError,ValueError,TypeError):return None
    finally:
        if fd is not None:os.close(fd)


def observed_call(handler,args,kw,resolver):
    """Run the unchanged handler once. Observation cannot bypass its guards."""
    if (os.environ.get('DELIVERY_EXECUTION_MODE')!='implementation'
            or os.environ.get('HERMES_FENCED_INPLACE_WRITES')!='1'
            or not isinstance(args,dict) or args.get('mode','replace')!='replace'):
        return handler(args,**kw)
    try:resolved=str(resolver(args.get('path'),kw.get('task_id') or 'default'))
    except Exception:resolved=None
    before=observe(resolved)
    raw=handler(args,**kw)
    after=observe(resolved)
    if not before or not after or before['path']!=after['path']:return raw
    try:value=json.loads(raw)
    except (ValueError,TypeError):return raw
    if not isinstance(value,dict):return raw
    value[FIELD]=dict(operation='handler_test_hash_observation_v1',path=before['path'],
        before_sha256=before['sha256'],after_sha256=after['sha256'],
        changed=before['sha256']!=after['sha256'],
        evidence_scope='immediate_handler_observation_not_final_snapshot',
        delivery_approval=False,author_retry_authorized=False)
    return json.dumps(value,sort_keys=True)


def adapt(source):
    if hashlib.sha256(source.encode()).hexdigest()!=SOURCE_SHA:
        raise ValueError('exact installed handler source required')
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_handle_patch')
    lines=source.splitlines(keepends=True)
    original=''.join(lines[node.lineno-1:node.end_lineno])
    renamed=original.replace('def _handle_patch(', 'def _handle_patch_unobserved(',1)
    wrapper='''\n\ndef _handle_patch(args, **kw):
    from patch_persistence_observer import observed_call
    return observed_call(_handle_patch_unobserved, args, kw, _resolve_path_for_task)
'''
    result=''.join(lines[:node.lineno-1])+renamed+wrapper+''.join(lines[node.end_lineno:])
    compile(result,'<observed-handler>','exec')
    return result


if __name__=='__main__':
    path=Path('/opt/hermes/tools/file_tools.py')
    if path.is_symlink():raise ValueError('unsafe handler source')
    path.write_text(adapt(path.read_text()))
