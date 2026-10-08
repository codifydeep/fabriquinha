"""Exercise the installed server function with an actual legacy receipt shape."""
import ast
import contextlib
import json
from pathlib import Path
import re
import sqlite3
import time
import unittest
import uuid
from unittest.mock import patch
from broker.suite_failure import FrozenSuiteFailure


class PortableSuiteDiagnosticsTests(unittest.TestCase):
    def test_legacy_receipt_without_file_inventory_retains_functional_failure(self):
        source = Path(__file__).parents[1] / 'broker/server.py'
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'run_portable_suite')
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.executescript('CREATE TABLE issue_editables(issue_id TEXT,path TEXT);'
                         'CREATE TABLE native_bindings(issue_id TEXT,task_id TEXT);')
        @contextlib.contextmanager
        def db():
            with con:
                yield con
        namespace = dict(json=json, re=re, time=time, PREFIX='delivery-kit-test', OWNER='owner',
            db=db, validation_job_name=lambda *_: 'fixed', handoff_context=lambda: None)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        specification = dict(test_image='python@sha256:' + 'a' * 64,
            test_command=['python3', '-m', 'unittest'], test_files=['tests/test_detail.py'])
        output = ("ERROR: test_get (tests.test_detail.Cases.test_get)\n"
                  "AttributeError: module 'app.db' has no attribute 'get_item'\nRan 3 tests\n")
        with patch('broker.validation_job.run', return_value=dict(exit_code=1, output=output)):
            with self.assertRaises(FrozenSuiteFailure) as raised:
                namespace['run_portable_suite']('volume', str(uuid.uuid4()), specification)
        failure = raised.exception.validation_failure
        self.assertEqual(failure['missing_module_attributes'], [dict(module='app.db', attribute='get_item')])
        self.assertEqual(failure['diagnostic_read_files'], ['tests/test_detail.py'])
        self.assertEqual(failure['tests_executed'], 3)
        self.assertEqual(con.execute('SELECT count(*) FROM frozen_suite_failures').fetchone()[0], 1)
