"""Check Git-index content, not private working-tree files. Never print secret values."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'provider/github token': re.compile(
        rb'(?<![A-Za-z0-9])(?:sk-or-v1-[a-fA-F0-9]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{40,})'),
    'telegram token': re.compile(rb'(?<![0-9])[0-9]{8,12}:[A-Za-z0-9_-]{30,}'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'jwt': re.compile(rb'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{20,}'),
    'literal credential': re.compile(
        rb'''(?im)^\s*["']?(?:OPENROUTER_API_KEY|GH_TOKEN|GITHUB_TOKEN|TELEGRAM_BOT_TOKEN|EVAL_JWT_SECRET)["']?\s*[:=]\s*["']?([A-Za-z0-9_-]{32,})'''),
}
PRIVATE_COMPONENTS = {'node_modules', '__pycache__', '.venv', '.git',
                      'backups', 'snapshots', 'sessions', 'artifacts'}


def findings(path, content, *, mode='100644'):
    p = PurePosixPath(path)
    errors = []
    public_evidence = {
        'team-delivery-kit/evaluation/sources.lock.json',
        'team-delivery-kit/evaluation/SURGICAL-DRIVER-V3-QUALIFICATION-2026-10-04.json',
        'team-delivery-kit/evaluation/TEMPLATE-LINES-V6-SOURCE-CANARY-2026-10-07.json',
    }
    if (path.startswith('team-delivery-kit/evaluation/') and p.suffix in {'.md', '.json'}
            and path not in public_evidence):
        errors.append('operational history is not part of the public source export')
    if mode not in {'100644', '100755'}:
        errors.append('symlink or nested repository is not a public source file')
    if (any(x.startswith('.local') or x in PRIVATE_COMPONENTS for x in p.parts)
            or p.name in {'operator.json', '.DS_Store'}
            or (p.name.startswith('.env') and p.name != '.env.example')
            or p.suffix in {'.db', '.sqlite', '.sqlite3', '.pem', '.key', '.log'}):
        errors.append('private/runtime path')
    if len(content) > 5 * 1024 * 1024:
        errors.append('file exceeds public source size limit')
    for name, pattern in PATTERNS.items():
        if pattern.search(content):
            errors.append(name)
    return errors


class PublicationTests(unittest.TestCase):
    def test_private_state_and_nested_git_are_rejected(self):
        for path in ['team-delivery-kit/.local-port2/operator.json', 'x/.env', 'x/keys.pem']:
            self.assertTrue(findings(path, b''))
        self.assertTrue(findings('nested', b'', mode='160000'))
        self.assertTrue(findings('team-delivery-kit/evaluation/internal.json', b'{}'))

    def test_secret_values_are_rejected(self):
        # Assemble synthetic values so the fixture itself has no token-shaped literal.
        for value in [b'sk-or-v1-' + b'a'*64, b'ghp_' + b'A'*36,
                      b'123456789:' + b'A'*35,
                      b'-----BEGIN ' + b'PRIVATE KEY-----']:
            self.assertTrue(findings('module.py', value))

    def test_templates_and_public_code_are_allowed(self):
        self.assertFalse(findings('config/.env.example', b'OPENROUTER_API_KEY=\n'))
        self.assertFalse(findings('README.md', b'Use ${GH_TOKEN}; no actual credential.'))


def check():
    entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).split(b'\0')
    count, errors = 0, []
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b'\t', 1)
        mode, oid, stage = metadata.decode().split()
        path = raw_path.decode()
        if stage != '0':
            errors.append((path, 'unresolved Git conflict'))
            continue
        content = subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=ROOT) if mode != '160000' else b''
        errors.extend((path, reason) for reason in findings(path, content, mode=mode))
        count += 1
    if not count:
        errors.append(('.', 'empty Git index; nothing has been checked'))
    for path, reason in errors:
        print(f'{path}: {reason}', file=sys.stderr)
    print(f'Publication check: {count} indexed files; {len(errors)} findings. Values never displayed.')
    return bool(errors)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(PublicationTests))
        raise SystemExit(not result.wasSuccessful())
    raise SystemExit(check())
