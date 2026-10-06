"""Disposable socketless real Hermes tool test; no model or product workspace."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    root = Path('/workspace')
    (root / 'tests').mkdir()
    baseline = {'app.py': 'VALUE = 0\n', 'tests/test_old.py':
        'import unittest, app\nclass Old(unittest.TestCase):\n def test_old(self): self.assertEqual(app.VALUE, 0)\n'}
    for name, content in baseline.items():
        target = root / name
        target.write_text(content)
        target.chmod(0o444)
    target = root / 'tests/test_new.py'
    target.write_text('')
    target.chmod(0o666)
    (root / 'tests').chmod(0o555)
    root.chmod(0o555)
    expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in baseline}
    # Setup is controller-only. Actual tools execute as the ordinary worker UID.
    os.setgroups([])
    os.setgid(10000)
    os.setuid(10000)
    assert os.getuid() == 10000
    os.environ['HERMES_FENCED_INPLACE_WRITES'] = '1'
    os.environ['HERMES_WRITE_SAFE_ROOT'] = '/workspace'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    from tools.file_tools import read_file_tool, write_file_tool, READ_FILE_SCHEMA, WRITE_FILE_SCHEMA
    from test_artifact_schema import apply
    body = {'messages': [{'role': 'user', 'content':
        'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
        'DELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'}],
        'tools': [{'type': 'function', 'function': schema} for schema in (READ_FILE_SCHEMA, WRITE_FILE_SCHEMA)]}
    assert apply(body)['tool_choice']['function']['name'] == 'read_file'
    read_args = {'path': '/workspace/app.py', 'offset': 1, 'limit': 50}
    observed = read_file_tool(**read_args)
    body['messages'] += [{'role': 'assistant', 'tool_calls': [{'id': 'r', 'function': {
        'name': 'read_file', 'arguments': json.dumps(read_args)}}]},
        {'role': 'tool', 'tool_call_id': 'r', 'content': observed}]
    assert apply(body)['tool_choice']['function']['name'] == 'write_file'
    content = 'import unittest, app\nclass New(unittest.TestCase):\n def test_new(self): self.assertEqual(app.VALUE, 1)\n'
    receipt = json.loads(write_file_tool(str(target), content))
    assert not receipt.get('error'), 'fixture write rejected: ' + str(receipt.get('error'))[:500]
    assert receipt.get('verified') is True, 'actual write was not hash verified'
    assert receipt.get('bytes_written') == len(content.encode())
    assert target.read_text() == content
    body['messages'] += [{'role': 'assistant', 'tool_calls': [{'id': 'w', 'function': {
        'name': 'write_file', 'arguments': json.dumps({'path': str(target), 'content': content})}}]},
        {'role': 'tool', 'tool_call_id': 'w', 'content': json.dumps(receipt)}]
    assert apply(body) is body, 'verified actual tool receipt did not open ordinary work'
    denied = json.loads(write_file_tool('/workspace/app.py', 'VALUE = 1\n'))
    assert denied.get('error'), 'baseline write was not denied'
    assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha for name, sha in expected.items())
    suite = subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                           cwd=root, capture_output=True, text=True)
    assert suite.returncode == 1 and 'FAIL: test_new' in suite.stderr and 'ERROR:' not in suite.stderr
    print(json.dumps({'status': 'passed', 'worker_uid': os.getuid(), 'actual_write_verified': True,
        'baseline_write_denied': True, 'baseline_hashes_unchanged': True, 'red_exit_code': suite.returncode,
        'test_count': int(re.search(r'Ran (\d+) tests', suite.stderr).group(1)),
        'new_test_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'model_calls': 0, 'delivery_approval': False}))


if __name__ == '__main__':
    main()
