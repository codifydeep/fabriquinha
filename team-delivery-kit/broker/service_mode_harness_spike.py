"""Fixed read-only harness schema experiment; never delivery/test approval.

Extract a literal with AST, not module import (which could execute Python).
Run only the frozen fixture in a caller-provided credential-free sandbox.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

TEST = 'tests/test_service_mode_indicator.py'
APP = 'app/static/app.js'


def extract_template(source):
    values = [node.value for node in ast.parse(source).body
              if isinstance(node, ast.Assign) and any(
                  isinstance(t, ast.Name) and t.id == 'NODE_HARNESS_TEMPLATE'
                  for t in node.targets)]
    if len(values) != 1 or not isinstance(values[0], ast.Constant) or not isinstance(values[0].value, str):
        raise ValueError('one literal harness required')
    return values[0].value


def shape(report):
    if not isinstance(report, dict):
        raise ValueError('object report required')
    result = {}
    for name in ('after_ok', 'pending_observed', 'after_deferred'):
        if name not in report:
            raise ValueError('required report field missing')
        value = report[name]
        result[name] = {'value_type': type(value).__name__,
                        'has_calls': isinstance(value, dict) and 'calls' in value,
                        'has_issued': isinstance(value, dict) and 'issued' in value,
                        'text_type': type(value.get('text')).__name__ if isinstance(value, dict) else None}
        text = value.get('text') if isinstance(value, dict) else value
        result[name]['is_checking'] = text == 'Checking environment…'
        result[name]['is_demo'] = text == 'Demo environment'
        if isinstance(value, dict) and type(value.get('calls')) is int:
            result[name]['calls'] = value['calls']
    return result


def run(root, expected_test_hash):
    root = Path(root)
    def hashes():
        return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in (TEST, APP)}
    before = hashes()
    if before[TEST] != expected_test_hash:
        raise ValueError('frozen test hash mismatch')
    template = extract_template((root / TEST).read_text())
    source_path = json.dumps(str(root / APP))
    script = template % {'source_path': source_path, 'source_filename': source_path}
    process = subprocess.run(['node', '--input-type=commonjs'], input=script,
                             text=True, capture_output=True, timeout=20, cwd=root)
    if process.returncode:
        raise ValueError('fixed harness execution failed')
    facts = shape(json.loads(process.stdout))
    if hashes() != before:
        raise ValueError('immutable inputs changed')
    return {'operation': 'service_mode_harness_schema_v1', 'input_sha256': before,
            'report_sha256': hashlib.sha256(process.stdout.encode()).hexdigest(),
            'facts': facts, 'inputs_unchanged': True, 'delivery_approval': False,
            'valid_red_green_receipt': False}


if __name__ == '__main__':
    import sys
    print(json.dumps(run('/delivery', sys.argv[1]), sort_keys=True))
