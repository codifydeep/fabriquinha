"""Execute the frozen candidate tests for diagnosis, NEVER approve Red/calibration.

Must run in the isolated no-network/no-credentials test container, not inside
the controller. Uses original product bytes; no reference fixtures or test edits.
"""
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import sys
import traceback
import unittest
from generic_harness_calibration import require,relative
from r3_snapshot_probe import probe


class OutputDigest:
    def __init__(self):self.hash=hashlib.sha256();self.bytes=0
    def write(self,text):
        data=text.encode('utf-8','replace');self.hash.update(data);self.bytes+=len(data);return len(text)
    def flush(self):pass


class Results(unittest.TestResult):
    def __init__(self,source_file=None):super().__init__();self._observations={};self.source_file=source_file
    @property
    def observations(self):return list(self._observations.values())
    def record(self,test,outcome,error=None):
        value=dict(test=test.__class__.__name__+'.'+test._testMethodName,outcome=outcome)
        if error:
            value.update(exception_type=error[0].__name__,details_sha256=hashlib.sha256(
                ''.join(traceback.format_exception(*error)).encode()).hexdigest())
            phase='test_body';frames=[];tb=error[2]
            while tb is not None:
                frame=tb.tb_frame;function=frame.f_code.co_name
                if frame.f_globals.get('__name__')=='unittest.case':
                    phase={'_callSetUp':'set_up','_callTearDown':'tear_down'}.get(function,phase)
                if frame.f_code.co_filename==self.source_file:
                    frames.append(dict(function=function,line=tb.tb_lineno))
                tb=tb.tb_next
            value.update(phase=phase,source_frames=frames[-8:])
        prior=self._observations.get(test.id())
        if prior is None or prior['outcome']=='passed':self._observations[test.id()]=value
    def stopTest(self,test):
        if test.id() not in self._observations:self.record(test,'passed')
        super().stopTest(test)
    def addSubTest(self,test,subtest,error):
        if error is not None:
            failure=issubclass(error[0],test.failureException)
            (self.failures if failure else self.errors).append((subtest,'digest only'))
            self.record(test,'failure' if failure else 'error',error)
    def addSuccess(self,test):self.record(test,'passed')
    def addFailure(self,test,error):self.failures.append((test,'digest only'));self.record(test,'failure',error)
    def addError(self,test,error):self.errors.append((test,'digest only'));self.record(test,'error',error)
    def addSkip(self,test,reason):self.skipped.append((test,'reason omitted'));self.record(test,'skipped')
    def addExpectedFailure(self,test,error):self.expectedFailures.append((test,'digest only'));self.record(test,'expected_failure',error)
    def addUnexpectedSuccess(self,test):self.unexpectedSuccesses.append(test);self.record(test,'unexpected_success')


def cases(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from cases(item)
        else:yield item


def run(candidate,manifest,test_hashes,test_methods):
    candidate=Path(candidate);probe(candidate,manifest)
    # probe validates the whole snapshot; check the exact independent input set.
    entries=json.loads((candidate/'manifest.json').read_text())['files']
    require(set(test_hashes)==set(test_methods) and bool(test_hashes))
    for path,sha in test_hashes.items():
        relative(path);require(path.endswith('.py') and entries.get(path,{}).get('sha256')==sha
            and isinstance(test_methods[path],list) and test_methods[path]
            and len(set(test_methods[path]))==len(test_methods[path]))
    loaded={};bytecode=sys.dont_write_bytecode;sys.dont_write_bytecode=True;modules={};output=OutputDigest()
    try:
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            for i,path in enumerate(sorted(test_hashes)):
                name='_frozen_harness_diagnostic_'+manifest[:16]+'_'+str(i);require(name not in sys.modules)
                spec=importlib.util.spec_from_file_location(name,candidate/path);module=importlib.util.module_from_spec(spec)
                sys.modules[name]=module;loaded[name]=module;spec.loader.exec_module(module)
                suite=unittest.defaultTestLoader.loadTestsFromModule(module);selected=list(cases(suite))
                require(all(isinstance(t,unittest.TestCase) and t.__class__.__module__==name for t in selected)
                    and sorted(t._testMethodName for t in selected)==sorted(test_methods[path]))
                result=Results(str(candidate/path));suite.run(result)
                require(result.testsRun==len(test_methods[path]) and len(result.observations)==result.testsRun)
                modules[path]=dict(tests=result.testsRun,outcomes=result.observations,
                    failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
                    expected_failures=len(result.expectedFailures),unexpected_successes=len(result.unexpectedSuccesses))
        return dict(operation='frozen_harness_diagnostic_v1',candidate_manifest_sha256=manifest,test_sha256=test_hashes,
            modules=modules,product_bytes='original_frozen_candidate',snapshot_unchanged=True,
            captured_output_sha256=output.hash.hexdigest(),captured_output_bytes=output.bytes,
            model_calls=0,full_regression_suite_executed=False,calibration_approved=False,red_approved=False,
            product_green=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
    finally:
        for name,module in loaded.items():
            if sys.modules.get(name) is module:del sys.modules[name]
        sys.dont_write_bytecode=bytecode;probe(candidate,manifest)


if __name__=='__main__':
    require(len(sys.argv)==5);signal.alarm(180)
    print(json.dumps(run(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]),json.loads(sys.argv[4])),sort_keys=True))
