"""Fixed diagnostic wrapper around the unchanged, pinned suite reporter.

No selection, timeout, assertion or verdict changes. Events are untrusted
diagnostic clues; only the wrapped reporter can produce the complete report.
"""
import importlib.util
import json
import sys
import time
from urllib.parse import urlsplit


def progress(event, **fields):
    print('FABRIQUINHA_PROGRESS '+json.dumps(dict(event=event,**fields),sort_keys=True),
          file=sys.__stdout__,flush=True)


def traced_result(base):
    class TracedResult(base):
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
                    def response_seen(response):
                        if response.status>=400:
                            # No bodies, cookies, headers or query strings in telemetry.
                            progress('http_error',case=self.trace_case,context_created_in=created_in,
                                     path=urlsplit(response.url).path[:500],status=response.status)
                    context.on('response',response_seen)
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
    return module.main()


if __name__=='__main__':raise SystemExit(main())
