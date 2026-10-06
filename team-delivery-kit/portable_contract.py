"""Operator-owned, fail-closed contract for a portable repository delivery.

The contract is loaded from an absolute local file, never from an agent message
or from the repository being delivered. Version 1 deliberately preserves every
pre-existing test file byte-for-byte; contract changes require a new version.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re

from test_runner_policy import validate_argv


MAX_FILES = 128
MAX_FILE_BYTES = 2 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}\Z')
REPOSITORY = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+\Z')
IMAGE = re.compile(r'[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}\Z')


def safe_path(value):
    if not isinstance(value, str) or not value or len(value) > 240 or '\\' in value:
        raise ValueError('invalid contract path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('unsafe contract path')
    if any(part in ('.git', '.delivery-kit') for part in path.parts):
        raise ValueError('controller or Git path forbidden')
    return value


def is_test_path(name, root, runner):
    if root == '.':
        if runner == 'python3':
            return PurePosixPath(name).name.startswith('test_') and name.endswith('.py')
        return name.endswith(('.test.js', '.spec.js'))
    return name == root or name.startswith(root + '/')


def validate(data):
    expected = {'schema_version', 'repository', 'base_branch', 'files',
                'protected_files', 'editable_files', 'test_files',
                'test_roots', 'test_command', 'test_image',
                'test_success_pattern', 'test_count_pattern', 'qa_cases'}
    version = data.get('schema_version') if isinstance(data, dict) else None
    if version == 2:
        expected |= {'required_files'}
    if not isinstance(data, dict) or set(data) != expected or version not in (1, 2):
        raise ValueError('invalid portable contract schema')
    if not isinstance(data['repository'], str) or not REPOSITORY.fullmatch(data['repository']):
        raise ValueError('invalid repository')
    if data['base_branch'] != 'main':
        raise ValueError('only protected main is supported in v1')
    for key in ('files', 'protected_files', 'editable_files', 'test_files'):
        values = data[key]
        if not isinstance(values, list) or not values or len(values) > MAX_FILES or len(set(values)) != len(values):
            raise ValueError('invalid ' + key)
        for value in values:
            safe_path(value)
    files = set(data['files'])
    if files & {'contract.json', 'manifest.json', '.delivery-kit-base.json'}:
        raise ValueError('controller-owned filename in contract')
    protected, editable, tests = (set(data[k]) for k in ('protected_files', 'editable_files', 'test_files'))
    if protected & editable or protected | editable != files or not tests <= files:
        raise ValueError('file ownership sets inconsistent')
    if not protected & tests or not editable & tests or not editable - tests:
        raise ValueError('need protected baseline tests, new editable tests and code')
    if version == 2:
        required = data['required_files']
        if (not isinstance(required, list) or not required
                or any(not isinstance(name, str) for name in required)
                or len(set(required)) != len(required)
                or not protected | tests <= set(required) <= files):
            raise ValueError('required files must preserve every protected file and test')
    roots = data['test_roots']
    if not isinstance(roots, list) or not roots or len(roots) > 16 or len(set(roots)) != len(roots):
        raise ValueError('invalid test roots')
    for root in roots:
        if root != '.':
            safe_path(root)
    if any(not any(is_test_path(name, root, data['test_command'][0]) for root in roots)
           for name in tests):
        raise ValueError('test file outside declared roots')
    command = data['test_command']
    if (not isinstance(command, list) or not 1 <= len(command) <= 16
            or any(not isinstance(arg, str) or not arg or len(arg) > 256
                   or '\x00' in arg for arg in command)):
        raise ValueError('test command must be a bounded argv array')
    validate_argv(command, roots)
    if not isinstance(data['test_image'], str) or not IMAGE.fullmatch(data['test_image']):
        raise ValueError('test image must be pinned by digest')
    pattern = data['test_success_pattern']
    if not isinstance(pattern, str) or not 1 <= len(pattern) <= 160:
        raise ValueError('invalid test success pattern')
    re.compile(pattern)
    count_pattern = data['test_count_pattern']
    if (not isinstance(count_pattern, str) or not 1 <= len(count_pattern) <= 160
            or re.compile(count_pattern).groups != 1):
        raise ValueError('test count pattern requires one capture group')
    cases = data['qa_cases']
    if not isinstance(cases, list) or not cases or len(cases) > 64:
        raise ValueError('invalid QA cases')
    for case in cases:
        json_case = (isinstance(case, dict) and
                     set(case) in ({'path', 'status', 'expected_json'},
                                   {'path', 'status', 'expected_json', 'bind_source_sha'}))
        text_case = (version == 2 and isinstance(case, dict) and
                     set(case) == {'path', 'status', 'content_type', 'text_contains'})
        if not (json_case or text_case):
            raise ValueError('invalid QA case')
        path = case['path']
        if not isinstance(path, str) or not path.startswith('/') or '://' in path or len(path) > 512:
            raise ValueError('invalid QA path')
        if type(case['status']) is not int or not 200 <= case['status'] <= 399:
            raise ValueError('invalid QA status')
        if json_case:
            if 'bind_source_sha' in case and (version != 2 or type(case['bind_source_sha']) is not bool):
                raise ValueError('invalid source SHA binding policy')
            if not isinstance(case['expected_json'], dict):
                raise ValueError('QA response must be an exact JSON object')
            if 'source_sha' in case['expected_json']:
                raise ValueError('source SHA is injected by the controller')
        else:
            if (case['content_type'] not in ('text/html', 'text/css', 'application/javascript')
                    or not isinstance(case['text_contains'], list)
                    or not 1 <= len(case['text_contains']) <= 8
                    or any(not isinstance(value, str) or not 1 <= len(value) <= 120
                           for value in case['text_contains'])):
                raise ValueError('invalid bounded text QA case')
    if any(case.get('bind_source_sha') is False for case in cases) and not any(
            'expected_json' in case and case.get('bind_source_sha', True) for case in cases):
        raise ValueError('unbound business JSON requires a source-bound health case')
    return data


def required_files(contract):
    return set(contract.get('required_files', contract['files']))


def validate_delivery_files(contract, names, baseline=()):
    """Optional new code may be absent; no baseline file or test may disappear."""
    names = set(names)
    required = required_files(contract) | (set(baseline) - {'contract.json'})
    if not required <= names <= set(contract['files']):
        raise ValueError('delivery file set violates contract')
    return sorted(names)


def load(path):
    source = Path(path)
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise ValueError('contract must be an absolute regular operator file')
    if source.stat().st_size > 65536:
        raise ValueError('contract too large')
    return validate(json.loads(source.read_text()))


def from_environment():
    selected = os.environ.get('DELIVERY_KIT_DELIVERY_CONTRACT')
    if not selected:
        raise ValueError('DELIVERY_KIT_DELIVERY_CONTRACT is required')
    return load(selected)
