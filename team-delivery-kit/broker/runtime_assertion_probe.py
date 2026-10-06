"""Fixed isolated Python-suite experiment; never substitutes delivery validation."""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import unittest

from assertion_witness import extract_trace


def safe_value(value,literals,depth=0):
    if depth>3:return {'redacted_type':'depth'}
    if value is None or type(value) is bool:return value
    if type(value) in (int,float):
        return value if abs(value)<1000000 else {'redacted_type':'number'}
    if type(value) is str:
        return value if value in literals and re.fullmatch(r'[\w .-]{0,80}',value) else {'redacted_type':'str'}
    if type(value) is list and len(value)<=16:return [safe_value(v,literals,depth+1) for v in value]
    if type(value) is dict and len(value)<=32:
        return {k:safe_value(v,literals,depth+1) for k,v in value.items()
                if type(k) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',k)}
    return {'redacted_type':type(value).__name__ if type(value) in (list,dict) else 'unsupported'}


def clean_event_report(report,literals):
    kinds={'context_created','event_registered','event_dispatched','dom_append','fetch_started','timer_registered','timer_fired'}
    if (type(report) is not dict or type(report.get('events')) is not list or len(report['events'])>256
            or type(report.get('total_events')) is not int or type(report.get('truncated')) is not bool):raise ValueError('bounded event report required')
    events=[];previous=0
    for item in report['events']:
        if (type(item) is not dict or item.get('kind') not in kinds or type(item.get('sequence')) is not int
                or item['sequence']<=previous or type(item.get('context')) is not int or not 1<=item['context']<=10000):raise ValueError('invalid event ordering')
        previous=item['sequence'];event={k:item[k] for k in ('sequence','context','kind')}
        for key in ('node','event','timer','method'):
            if key in item and type(item[key]) is str and re.fullmatch(r'[A-Za-z_][\w-]{0,79}',item[key]):event[key]=item[key]
        for key in ('value','query','count','delay'):
            if key in item:event[key]=safe_value(item[key],literals)
        events.append(event)
    return dict(events=events,total_events=report['total_events'],truncated=report['truncated'])


def run(root,hashes,saved_output,*,event_trace=False):
    proof=extract_trace(root,hashes,saved_output)
    manifest=json.loads((root/'manifest.json').read_bytes())['files']
    for path,item in manifest.items():
        if path.startswith('/') or '..' in Path(path).parts:raise ValueError('unsafe snapshot path')
        file=root/path
        if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('immutable snapshot mismatch')
    targets={a['qualified_name'] for a in proof['anchors']}
    locations={(a['qualified_name'],a['line']):a for a in proof['anchors'] if 'line' in a}
    if not targets:raise ValueError('trace-bound methods required')
    literals={n.value for p in hashes for n in ast.walk(ast.parse((root/p).read_bytes()))
              if isinstance(n,ast.Constant) and type(n.value) is str}
    observations=[];originals={};event_reports=[];original_run=subprocess.run
    def traced_run(*args,**kwargs):
        frame=sys._getframe(1);matched=False
        while frame:
            if frame.f_code.co_filename in {str(root/p) for p in hashes}:matched=True;break
            frame=frame.f_back
        command=args[0] if args else kwargs.get('args')
        eligible=matched and isinstance(command,(list,tuple)) and command and Path(str(command[0])).name=='node'
        if eligible:
            env=dict(kwargs.get('env') or os.environ)
            if env.get('NODE_OPTIONS'):raise ValueError('trace requires clean node options')
            env.update(NODE_OPTIONS='--require /event_trace.cjs',DELIVERY_EVENT_TRACE='1');kwargs['env']=env
        result=original_run(*args,**kwargs)
        if eligible:
            stderr=result.stderr.decode() if isinstance(result.stderr,bytes) else result.stderr
            if not isinstance(stderr,str) or 'DELIVERY_EVENT_TRACE_V1:' not in stderr:raise ValueError('actual node trace required')
            raw=stderr.rsplit('DELIVERY_EVENT_TRACE_V1:',1)[1].splitlines()[0]
            event_reports.append(clean_event_report(json.loads(raw),literals))
        return result
    def wrap(original):
        def observed(test,*args,**kwargs):
            frame=sys._getframe(1)
            anchor=locations.get((test.id(),frame.f_lineno))
            if test.id() in targets and (anchor or not locations) and len(observations)<32:
                reports={k:safe_value(v,literals) for k,v in frame.f_locals.items()
                         if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',k) and type(v) is dict and len(v)<=32}
                attributes=object.__getattribute__(test,'__dict__')
                shared=attributes.get('report')
                if shared is None:
                    # setUpClass may store report on the class, not the instance.
                    for cls in type(test).__mro__:
                        candidate=vars(cls).get('report')
                        if type(candidate) is dict:shared=candidate;break
                if type(shared) is dict and anchor:
                    reports['self_report']={k:safe_value(shared[k],literals) for k in anchor.get('fields',[]) if k in shared}
                observations.append(dict(test=test.id(),line=frame.f_lineno,assertion=original.__name__,
                    operands=[safe_value(v,literals) for v in args[:2]],reports=reports))
            return original(test,*args,**kwargs)
        return observed
    stream=io.StringIO();prior=list(sys.path)
    try:
        sys.path.insert(0,str(root))
        if event_trace:subprocess.run=traced_run
        for name in {a['assertion'] for a in proof['anchors']}:
            originals[name]=getattr(unittest.TestCase,name);setattr(unittest.TestCase,name,wrap(originals[name]))
        with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
            suite=unittest.defaultTestLoader.discover(str(root/'tests'),top_level_dir=str(root))
            result=unittest.TextTestRunner(stream=stream).run(suite)
    finally:
        for name,original in originals.items():setattr(unittest.TestCase,name,original)
        sys.path[:]=prior
        subprocess.run=original_run
    result_proof=dict(manifest_sha256=proof['manifest_sha256'],output_sha256=proof['output_sha256'],
        operation='frozen_python_suite_assertion_observations_v2',runtime_observations=observations,
        suite=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)),
        status='experiment_only_not_green_or_approval',approval=False)
    if event_trace:
        if not event_reports:raise ValueError('trace-bound node execution required')
        result_proof.update(operation='frozen_js_event_order_experiment_v1',event_reports=event_reports)
    return result_proof


if __name__=='__main__':
    print(json.dumps(run(Path('/delivery'),json.loads(os.environ['FROZEN_TEST_HASHES']),
        json.loads(os.environ['SAVED_OUTPUT']),event_trace=os.environ.get('EVENT_ORDER_TRACE')=='1'),sort_keys=True),flush=True)
