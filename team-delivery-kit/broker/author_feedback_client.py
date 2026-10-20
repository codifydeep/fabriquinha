"""Opt-in worker feedback transport. No shell, controller token or approval.

The endpoint and source path come from controller-authored configuration. The
model cannot select a URL, command, image or another execution. Not active
unless a scoped capability is installed in this worker's environment.
"""
import hashlib
import asyncio
import json
import os
from pathlib import Path,PurePosixPath
import re
import time
import threading
import urllib.request
import uuid
from literal_feedback_wire import FALSE_FLAGS,validate,presentation,require,worker_config

VIRTUAL_PATH='/feedback/current.json'
ENDPOINT='http://execution-broker:8090/v1/author-feedback'
PAGES={}
FILE_LOCK=threading.Lock()


def configured():
    raw=os.environ.get('DELIVERY_AUTHOR_FEEDBACK_JSON')
    if not raw:return None
    require(os.environ.get('DELIVERY_EXECUTION_MODE')=='implementation' and len(raw)<=4096)
    cfg=worker_config(json.loads(raw),os.environ.get('DELIVERY_MODEL_EXECUTION_ID'))
    require(not os.environ.get('DELIVERY_SURGICAL_TEST_JSON') and not os.environ.get('DELIVERY_ADDITIVE_TEST_JSON'))
    return cfg


def read_current(cfg):
    path=Path('/workspace')/cfg['test_path']
    require(not any(p.is_symlink() for p in (path,*list(path.parents)[:len(PurePosixPath(cfg['test_path']).parts)]))
        and path.is_file() and 0<path.stat().st_size<=32768)
    return path.read_bytes()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('feedback_redirect_forbidden')


def request(cfg):
    sha=None
    try:
        sha=hashlib.sha256(read_current(cfg)).hexdigest()
        request=urllib.request.Request(ENDPOINT,data=json.dumps({'candidate_sha256':sha}).encode(),
            headers={'Authorization':'Bearer '+cfg['capability'],'Content-Type':'application/json'},method='POST')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        deadline=time.monotonic()+45
        while True:
            require(hashlib.sha256(read_current(cfg)).hexdigest()==sha)
            with opener.open(request,timeout=min(30,max(1,deadline-time.monotonic()))) as response:
                require(response.status==200);raw=response.read(16385)
            require(0<len(raw)<=16384);value=json.loads(raw)
            require(hashlib.sha256(read_current(cfg)).hexdigest()==sha)
            if value.get('operation')=='literal_author_feedback_pending_v1':
                require(value.get('candidate_sha256')==sha and value.get('next_action')=='observe_same_feedback_job'
                    and all(value.get(k) is False for k in FALSE_FLAGS))
                if time.monotonic()>=deadline:
                    return dict(status='pending',candidate_sha256=sha,instruction='Read '+VIRTUAL_PATH+
                        ' to observe this same feedback job; do not repeat an already saved patch.',**{k:False for k in FALSE_FLAGS})
                time.sleep(.2);continue
            validate(value,cfg,sha,bound=True);return presentation(value)
    except Exception:
        # Never expose a URL, capability, HTTP body, source or private traceback.
        return dict(status='unavailable',candidate_sha256=sha,instruction='Controller feedback unavailable or stale. '
            'Do not claim passing tests or repeat a saved patch; read '+VIRTUAL_PATH+' or report the technical blocker.',
            **{k:False for k in FALSE_FLAGS})


def observe(cfg,name,args,result):
    if name!='read_file' or not isinstance(args,dict) or args.get('path')!='/workspace/'+cfg['test_path']:return
    try:
        value=json.loads(result);total=value['total_lines'];offset=args.get('offset',1);limit=args.get('limit',200)
        require(not value.get('error') and isinstance(value.get('content'),str) and value['content']
            and type(total) is int and 0<total<=32768 and type(offset) is int and offset>0
            and type(limit) is int and 0<limit<=200)
        PAGES.setdefault(cfg['request_id'],set()).update(range(offset,min(total+1,offset+limit)))
    except (ValueError,TypeError,KeyError):return


def control(cfg,name,args):
    require(isinstance(args,dict))
    if name=='read_file' and args.get('path')==VIRTUAL_PATH:
        require(set(args)<={'path','offset','limit'})
        content=json.dumps(request(cfg),sort_keys=True)
        return json.dumps(dict(path=VIRTUAL_PATH,content=content,total_lines=1,controller_diagnostic=True))
    if name=='read_file':
        path=args.get('path');require(isinstance(path,str) and path.startswith('/workspace/')
            and PurePosixPath(path).as_posix()==path and '..' not in PurePosixPath(path).parts)
        return None
    require(name=='patch' and set(args)=={'path','old_string','new_string'} and args['path']=='/workspace/'+cfg['test_path']
        and all(isinstance(args[k],str) and 0<len(args[k].encode())<=4096 for k in ('old_string','new_string')))
    raw=read_current(cfg);source=raw.decode();require(set(range(1,len(source.splitlines())+1))<=PAGES.get(cfg['request_id'],set()))
    require(source.count(args['old_string'])==1 and args['old_string']!=args['new_string'])
    from literal_test_maintenance import compare
    compare(raw,source.replace(args['old_string'],args['new_string'],1).encode(),'NODE_HARNESS')
    return None


def enrich(cfg,name,args,raw):
    if name!='patch':return raw
    try:
        value=json.loads(raw)
        if not (isinstance(value,dict) and value.get('success') is True and not value.get('error')
                and not value.get('already_applied') and not value.get('no_change')
                and isinstance(value.get('diff'),str) and value['diff'].strip()):return raw
        PAGES.pop(cfg['request_id'],None)
        value['_author_feedback_v1']=request(cfg)
        return json.dumps(value)
    except (ValueError,TypeError):return raw


def wrap(name,handler,is_async):
    """Serialize reads/patches across sync and async direct handler calls."""
    if is_async:
        async def wrapped(args,**kwargs):
            await asyncio.to_thread(FILE_LOCK.acquire)
            try:
                cfg=configured();require(cfg is not None)
                controlled=await asyncio.to_thread(control,cfg,name,args)
                if controlled is not None:return controlled
                result=await handler(args,**kwargs);observe(cfg,name,args,result)
                return await asyncio.to_thread(enrich,cfg,name,args,result)
            except Exception:
                return json.dumps(dict(error='author_feedback_operation_rejected',delivery_approval=False))
            finally:FILE_LOCK.release()
        return wrapped
    def wrapped(args,**kwargs):
        with FILE_LOCK:
            try:
                cfg=configured();require(cfg is not None)
                controlled=control(cfg,name,args)
                if controlled is not None:return controlled
                result=handler(args,**kwargs);observe(cfg,name,args,result)
                return enrich(cfg,name,args,result)
            except Exception:
                return json.dumps(dict(error='author_feedback_operation_rejected',delivery_approval=False))
    return wrapped
