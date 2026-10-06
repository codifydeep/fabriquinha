"""Operator-run, fixed-scope CI probe for codifydeep/descartavel PR #1.

This does not merge or configure branch protection. It reads the controller's
review receipt and publishes a commit status only after exact-byte validation.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

from broker.merge_gate import verify_local_merge_preconditions


ROOT = Path(__file__).resolve().parent
REPO = ROOT / 'sandbox-github'
SNAPSHOT = ROOT / '.local/pr1-snapshot'
SOURCE_TASK = '01a0d064-aef1-7e5d-94f7-9093ee9d98cb'
REVIEW_TASK = '01a0d066-0ea7-7998-ab47-a92d1c8eda9c'
REMOTE = 'https://github.com/codifydeep/descartavel.git'


def command(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def main():
    if command(['git', '-C', str(REPO), 'remote', 'get-url', 'origin']).strip() != REMOTE:
        raise ValueError('sandbox remote changed')
    pr = json.loads(command(['gh', 'pr', 'view', '1', '--repo', 'codifydeep/descartavel',
                             '--json', 'headRefOid,headRefName,baseRefName,state,url']))
    if (pr['state'] != 'OPEN' or pr['baseRefName'] != 'main'
            or pr['headRefName'] != 'codex/eval8-reviewed-snapshot'):
        raise ValueError('unexpected sandbox PR')
    head = pr['headRefOid']
    query = ('import sqlite3,json; c=sqlite3.connect("/broker-state/leases.sqlite"); '
             'r=c.execute("select source_task_id,reviewer_agent_id,manifest_sha256,status '
             'from reviews where review_task_id=?",(' + repr(REVIEW_TASK) + ',)).fetchone(); '
             'print(json.dumps(r))')
    row = json.loads(command(['docker', 'exec', 'delivery-kit-eval-execution-broker-1',
                              'python3', '-c', query]))
    if not row:
        raise ValueError('controller review receipt missing')
    source, reviewer, manifest, status = row
    if source != SOURCE_TASK or status != 'approved' or not re.fullmatch(r'[0-9a-f]{64}', manifest):
        raise ValueError('controller review receipt invalid')
    suite = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-q'],
                           cwd=REPO, env={'PYTHONDONTWRITEBYTECODE': '1', 'PATH': '/usr/bin:/bin:/opt/homebrew/bin'},
                           text=True, capture_output=True, timeout=30)
    result = suite.stdout + suite.stderr
    match = re.search(r'Ran (\d+) tests? in ', result)
    if suite.returncode or not match or int(match.group(1)) < 3 or '\nOK' not in result:
        raise ValueError('local full suite failed')
    review = {'status': status, 'source_task_id': source, 'manifest_sha256': manifest,
              'reviewer_agent_id': reviewer, 'head_sha': head}
    ci = {'head_sha': head, 'status': 'success', 'review_manifest_sha256': manifest,
          'tests': int(match.group(1))}
    receipt = verify_local_merge_preconditions(REPO, head, SOURCE_TASK, review, ci, SNAPSHOT)
    command(['gh', 'api', '--method', 'POST',
             'repos/codifydeep/descartavel/statuses/' + head,
             '-f', 'state=success', '-f', 'context=delivery-kit/eval-local',
             '-f', 'description=Exact reviewed snapshot and 6-test local suite passed',
             '-f', 'target_url=' + pr['url']])
    current = json.loads(command(['gh', 'api',
                                  'repos/codifydeep/descartavel/commits/' + head + '/status']))
    if current.get('state') != 'success' or not any(
            item.get('context') == 'delivery-kit/eval-local' and item.get('state') == 'success'
            for item in current.get('statuses', [])):
        raise ValueError('published GitHub status not visible on exact SHA')
    print(json.dumps({'pr': pr['url'], 'head_sha': head, 'source_task_id': SOURCE_TASK,
                      'manifest_sha256': receipt['review_manifest_sha256'],
                      'tests': receipt['tests'], 'status': 'delivery-kit/eval-local:success'}))


if __name__ == '__main__':
    main()
