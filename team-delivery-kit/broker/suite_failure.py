"""Structured failed-suite evidence; never send arbitrary test output to agents."""
import hashlib
import re
import ast


def safe_assertion_details(output):
    """Expose numeric witnesses, never arbitrary assertion strings/user data."""
    details = []
    for line in output.splitlines():
        if not line.startswith('AssertionError: ') or ' != ' not in line:
            continue
        left, right = line.removeprefix('AssertionError: ').split(' != ', 1)
        try:
            observed, expected = ast.literal_eval(left), ast.literal_eval(right)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        def numeric(value):
            return (type(value) is int and abs(value) < 1000000000 or
                    isinstance(value, str) and re.fullmatch(r'-?\d{1,9}', value) is not None)
        def safe(value):
            return numeric(value) or (isinstance(value, dict) and bool(value)
                and set(value) <= {'total', 'open', 'completed'}
                and all(numeric(item) for item in value.values()))
        if safe(observed) and safe(expected):
            details.append({'observed': observed, 'expected': expected})
        if len(details) >= 16:
            break
    return details


def evidence(exit_code, output, source_task, volume):
    if type(exit_code) is not int or exit_code == 0 or not isinstance(output, str):
        raise ValueError('failed suite evidence required')
    tests = re.search(r'(?m)^Ran (\d+) tests?\b', output)
    failures = re.findall(r'(?m)^(FAIL|ERROR): (test_[A-Za-z0-9_]+) \(([A-Za-z0-9_.]+)\)', output)
    # Distinguish runner failure from an executed assertion; neither is approval.
    category = 'executed_test_failure' if tests and failures else 'runner_failure_unclassified'
    return {'category': category, 'phase': 'frozen_green',
            'source_task': source_task, 'volume': volume, 'exit_code': exit_code,
            'tests_executed': int(tests.group(1)) if tests else None,
            'failures': [{'kind': kind, 'test': name, 'qualified_name': qualified}
                         for kind, name, qualified in failures[:32]],
            'exception_types': sorted(set(re.findall(
                r'(?m)^([A-Za-z][A-Za-z0-9_]*(?:Error|Exception)):', output)))[:16],
            'numeric_assertion_details': safe_assertion_details(output),
            'missing_metadata_keys': sorted(set(re.findall(
                r"(?m)^KeyError: '(filename|sha256|executed)'$", output))),
            'output_sha256': hashlib.sha256(output.encode()).hexdigest()}


class FrozenSuiteFailure(ValueError):
    def __init__(self, receipt):
        self.validation_failure = receipt
        super().__init__('portable frozen suite failed')


def failing_source_files(receipt, manifest_files):
    """Resolve qualified failures only to source files in the frozen manifest."""
    result = set()
    for failure in receipt.get('failures', []):
        name = failure.get('qualified_name', '')
        matches = [path for path in manifest_files if path.endswith('.py')
                   and name.startswith(path[:-3].replace('/', '.') + '.')]
        if matches:
            result.add(max(matches, key=len))
    return sorted(result)
