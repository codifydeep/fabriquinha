"""Fixed Python-unittest reporter, installed in the validation image.

No worker-selected shell/test expression. Tests execute in the unprivileged
job sandbox; only its controller can create a trusted execution receipt.
"""
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback
import unittest


class Output(io.StringIO):
    def write(self, text):
        if self.tell() + len(text) > 1024 * 1024:
            raise RuntimeError('test output exceeded limit')
        return super().write(text)


class Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.cases = []
        self.failure_details = []

    def failure(self, test, error):
        frames = [dict(file=f.filename.removeprefix('/workspace/'), line=f.lineno, function=f.name)
                  for f in traceback.extract_tb(error[2]) if f.filename.startswith('/workspace/')]
        self.failure_details.append(dict(case=test.id(), frames=frames, assertion=True,
                                        detail=str(error[1])[:1000]))

    def startTest(self, test):
        super().startTest(test)
        self.cases.append(test.id())

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.failure(test, error)

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None and issubclass(error[0], test.failureException):
            self.failure(test, error)


def main():
    root = Path('/workspace')
    preview_driver=None
    if 'FABRIQUINHA_QA_PREVIEW' in os.environ:
        # Product modules may also be named browser.py. Never resolve the
        # trusted read-only mounted interpreter through product sys.path.
        spec=importlib.util.spec_from_file_location('_fabriquinha_frozen_browser','/opt/fabriquinha/browser.py')
        preview_driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(preview_driver)
    test_dir = os.environ['FABRIQUINHA_TESTS_DIR']
    path = Path(test_dir)
    if path.is_absolute() or '..' in path.parts or str(path) != test_dir:
        raise ValueError('relative discovery directory required')
    sys.path.insert(0, str(root))
    os.chdir(root)
    result = Result()
    with contextlib.redirect_stdout(Output()), contextlib.redirect_stderr(Output()):
        tests = unittest.TestLoader().discover(str(root / path), pattern='test*.py')
        tests.run(result)
    report = dict(version=1, cases=result.cases, tests_run=result.testsRun,
                  failures=result.failure_details, errors=[t.id() for t, _ in result.errors],
                  skips=[t.id() for t, _ in result.skipped],
                  expected_failures=[t.id() for t, _ in result.expectedFailures],
                  unexpected_successes=[t.id() for t in result.unexpectedSuccesses])
    preview_ok=True
    if 'FABRIQUINHA_QA_PREVIEW' in os.environ:
        with contextlib.redirect_stdout(Output()), contextlib.redirect_stderr(Output()):
            report['qa_preview']=preview_driver.preview(root,test_dir,os.environ['FABRIQUINHA_QA_PREVIEW'])
        preview_ok=report['qa_preview']['status']=='passed'
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() and preview_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
