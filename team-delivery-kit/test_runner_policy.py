"""Small, shell-free set of test runners shared by operator and broker."""
import re


ROOT = re.compile(r'[A-Za-z0-9_/-]{1,160}\Z')


def safe_root(root):
    return (root == '.' or (isinstance(root, str) and ROOT.fullmatch(root) is not None
            and all(part not in ('', '.', '..') for part in root.split('/'))))


def validate_argv(argv, roots):
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        raise ValueError('test runner argv invalid')
    if len(roots) != 1 or not safe_root(roots[0]):
        raise ValueError('one safe test root required')
    root = roots[0]
    allowed = (
        ['python3', '-m', 'unittest', 'discover', '-s', root, '-q'],
        ['node', '--test'],
    )
    if argv not in allowed:
        raise ValueError('test runner not qualified')
    return argv


def workspace_command(argv, roots):
    validate_argv(argv, roots)
    prefix = ('cd /workspace && PYTHONDONTWRITEBYTECODE=1 '
              if argv[0] == 'python3' else 'cd /workspace && ')
    return prefix + ' '.join(argv) + ' 2>&1'


def validate_workspace_command(command):
    if not isinstance(command, str) or len(command) > 300:
        raise ValueError('invalid registered test command')
    for pattern, builder in (
        (r'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s (\.|[A-Za-z0-9_/-]+) -q 2>&1',
         lambda root: ['python3', '-m', 'unittest', 'discover', '-s', root, '-q']),
    ):
        match = re.fullmatch(pattern, command)
        if match and safe_root(match.group(1)):
            argv = builder(match.group(1))
            if workspace_command(argv, [match.group(1)]) == command:
                return argv
    if command == 'cd /workspace && node --test 2>&1':
        return ['node', '--test']
    raise ValueError('test command outside qualified policy')


def unacceptable_output(output):
    if not isinstance(output, str):
        return True
    return bool(re.search(r'\b(?:skipped=\d+|\d+\s+skipped|expected failures?=|'
                          r'unexpected successes?)', output, re.IGNORECASE)
                or re.search(r'(?:^|\n)\s*(?:#|ℹ)\s*(?:skipped|todo|cancelled)\s+[1-9][0-9]*\b',
                             output, re.IGNORECASE))
