"""Fixed diagnostic wrapper around the unchanged, pinned suite reporter.

No selection, timeout, assertion or verdict changes. Events are untrusted
diagnostic clues; only the wrapped reporter can produce the complete report.
"""
import importlib.util
import json
import sys
import re
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit


def progress(event, **fields):
    print('FABRIQUINHA_PROGRESS '+json.dumps(dict(event=event,**fields),sort_keys=True),
          file=sys.__stdout__,flush=True)


def resource_observation():
    result={}
    for name in ('pids.current','pids.max','memory.current','memory.max','pids.events'):
        try:
            value=(Path('/sys/fs/cgroup')/name).read_text().strip()
            if name=='pids.events':result['pids_limit_hits']=int(value.split('max ')[1].split()[0])
            elif value=='max' or value.isdigit():result[name]=value
        except (OSError,ValueError,IndexError):pass
    return result


def traced_result(base):
    class TracedResult(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.trace_context_count=0

        def startTest(self,test):
            super().startTest(test)
            self.trace_case=test.id()[:1000]
            module=sys.modules.get('fabriquinha_acceptance')
            acceptance=getattr(module,'AcceptanceTest',None)
            if acceptance is not None and not getattr(acceptance.new_context,'_diagnostic_trace',False):
                original=acceptance.new_context
                def context_with_trace(owner,*args,**kwargs):
                    context=original(owner,*args,**kwargs)
                    created_in=self.trace_case
                    self.trace_context_count+=1
                    context_id=self.trace_context_count
                    def fields(url):
                        path=urlsplit(url).path
                        if not re.fullmatch(r'/api/rooms(?:/[A-Za-z0-9_-]+(?:/(?:join|ready|play|leave|start|cancel))?)?',path):
                            return None
                        return dict(case=self.trace_case,context_created_in=created_in,
                                    context_id=context_id,path=path[:500],at=round(time.monotonic(),3))
                    def request_seen(request):
                        data=fields(request.url)
                        if data:progress('room_request',**data,method=request.method)
                    def response_seen(response):
                        data=fields(response.url)
                        if data:progress('room_response',**data,status=response.status)
                        if response.status>=400:
                            # No bodies, cookies, headers or query strings in telemetry.
                            progress('http_error',case=self.trace_case,context_created_in=created_in,
                                     context_id=context_id,path=urlsplit(response.url).path[:500],status=response.status)
                    def failed(request):
                        data=fields(request.url)
                        if data:progress('room_request_failed',**data,method=request.method,resources=resource_observation())
                    context.on('request',request_seen)
                    context.on('response',response_seen)
                    context.on('requestfailed',failed)
                    return context
                context_with_trace._diagnostic_trace=True
                acceptance.new_context=context_with_trace
            self.trace_started=time.monotonic()
            progress('test_started',case=test.id()[:1000])

        def stopTest(self,test):
            super().stopTest(test)
            progress('test_finished',case=test.id()[:1000],
                     elapsed_seconds=round(time.monotonic()-self.trace_started,3))
    return TracedResult


def main():
    progress('stage',phase='load_pinned_suite')
    spec=importlib.util.spec_from_file_location('_fixed_suite','/opt/fabriquinha/suite.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.Result=traced_result(module.Result)
    progress('stage',phase='execute_pinned_suite')
    original=subprocess.Popen
    captures=[]
    def observed_popen(command,*args,**kwargs):
        if isinstance(command,list) and len(command)>=3 and str(command[2]).endswith('/app.py') and kwargs.get('stderr')==subprocess.DEVNULL:
            capture=tempfile.TemporaryFile();kwargs['stderr']=capture
            try:process=original(command,*args,**kwargs)
            except BaseException:capture.close();raise
            captures.append((process,capture))
            return process
        return original(command,*args,**kwargs)
    subprocess.Popen=observed_popen
    try:return module.main()
    finally:
        subprocess.Popen=original
        for process,capture in captures:
            capture.seek(0,2);size=capture.tell();capture.seek(max(0,size-65536))
            tail=capture.read().decode('utf-8','replace');capture.close()
            progress('server_resources',exit_code=process.poll(),stderr_tail_truncated=size>65536,
                thread_start_failures=tail.count("can't start new thread"),
                resource_unavailable=tail.count('Resource temporarily unavailable'),resources=resource_observation())


if __name__=='__main__':raise SystemExit(main())
