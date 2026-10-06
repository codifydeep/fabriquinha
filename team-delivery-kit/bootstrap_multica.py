"""Onboard one synthetic local operator through supported HTTP APIs; no DB edits."""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from evalctl import ROOT, PRIVATE, PROJECT, BACKEND_PORT, compose, process_env, check_private

API = 'http://127.0.0.1:' + BACKEND_PORT
EMAIL = 'operator@delivery-kit.invalid'
AUTH = PRIVATE / 'operator.json'


def private_json(path, value):
    if path.is_symlink():
        raise ValueError('refusing symlink')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)


def request(path, payload=None, token=None, workspace=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if workspace:
        headers['X-Workspace-ID'] = workspace
    req = urllib.request.Request(API + path, headers=headers,
                                 data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Never dump API responses: creation responses may contain credentials.
        raise RuntimeError(f'{path}: HTTP {error.code}') from None


def wait_health():
    for _ in range(30):
        try:
            request('/health')
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError('local API did not become healthy')


def main():
    check_private()
    if AUTH.exists():
        if AUTH.is_symlink() or AUTH.stat().st_mode & 0o077:
            raise ValueError('unsafe private operator file')
        account = json.loads(AUTH.read_text())
    else:
        try:
            compose(['-f', str(ROOT / 'compose.onboarding.yaml'), 'up', '-d', 'backend'])
            wait_health()
            request('/auth/send-code', {'email': EMAIL})
            logs = subprocess.check_output(['docker', 'logs', '--since', '2m',
                                            PROJECT + '-backend-1'],
                                           env=process_env(), stderr=subprocess.STDOUT).decode()
            codes = re.findall(r'Verification code for ' + re.escape(EMAIL) + r': (\d+)', logs)
            if not codes:
                raise RuntimeError('local verification code not found; no bypass attempted')
            login = request('/auth/verify-code', {'email': EMAIL, 'code': codes[-1]})
            pat = request('/api/tokens/', {'name': 'delivery-kit-local-pilot', 'expires_in_days': 7}, login['token'])
            account = {'token': pat['token'], 'token_id': pat['id'], 'user_id': login['user']['id']}
            private_json(AUTH, account)
        finally:
            compose(['up', '-d', 'backend'])
            wait_health()
    workspaces = request('/api/workspaces/', token=account['token'])
    workspace = next((w for w in workspaces if w['slug'] == PROJECT), None)
    if workspace is None:
        workspace = request('/api/workspaces/', {
            'name': 'Team Delivery — isolated evaluation ' + PROJECT, 'slug': PROJECT,
            'issue_prefix': 'EVAL', 'description': 'No production repositories or model credentials.',
        }, account['token'])
    state = PRIVATE / 'workspace.json'
    if not state.exists():
        private_json(state, {'id': workspace['id'], 'slug': workspace['slug']})
    elif json.loads(state.read_text())['id'] != workspace['id']:
        raise ValueError('workspace identity changed; reconciliation required')
    print(json.dumps({'workspace_id': workspace['id'], 'signup_restored_disabled': True,
                      'operator_credentials': 'private-file-only', 'agents_dispatched': 0}))


if __name__ == '__main__':
    main()
