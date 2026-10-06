"""Independent read-only review of an exact disposable bootstrap PR revision."""
import hashlib
import json
from pathlib import Path
import subprocess

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from planning_intake import NAME, completed_output
from release_eval import save_receipt
from start_eval import cli


REPO = 'codifydeep/descartavel2'
PR = 16
CHECKOUT = Path(__file__).resolve().parent / 'sandbox-github2'


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def parse_review(text):
    if not isinstance(text, str) or not 0 < len(text) <= 2400:
        raise ValueError('invalid review output size')
    result = json.loads(text.strip())
    if not isinstance(result, dict) or set(result) != {'role', 'decision', 'findings', 'rationale'}:
        raise ValueError('invalid review schema')
    if result['role'] != 'quality_security' or result['decision'] not in ('APPROVE', 'REQUEST_CHANGES'):
        raise ValueError('invalid reviewer identity or decision')
    findings = result['findings']
    if not isinstance(findings, list) or len(findings) > 8 or any(
            not isinstance(item, str) or not 5 <= len(item) <= 350 for item in findings):
        raise ValueError('invalid findings')
    if result['decision'] == 'REQUEST_CHANGES' and not findings:
        raise ValueError('change request lacks findings')
    if not isinstance(result['rationale'], str) or not 10 <= len(result['rationale']) <= 600:
        raise ValueError('invalid rationale')
    return result


def verified_pr():
    pr = json.loads(command('gh', 'pr', 'view', str(PR), '-R', REPO,
                            '--json', 'headRefOid,baseRefName,state,url'))
    if pr['state'] != 'OPEN' or pr['baseRefName'] != 'main':
        raise ValueError('bootstrap PR state changed')
    sha = pr['headRefOid']
    if command('git', '-C', str(CHECKOUT), 'rev-parse', 'HEAD') != sha:
        raise ValueError('local bootstrap head differs from PR')
    checks = json.loads(command('gh', 'api', f'repos/{REPO}/commits/{sha}/check-runs'))
    if not any(run.get('name') == 'ci' and run.get('conclusion') == 'success'
               and run.get('head_sha') == sha for run in checks.get('check_runs', [])):
        raise ValueError('exact PR SHA lacks green CI')
    diff = command('git', '-C', str(CHECKOUT), 'diff', 'main...' + sha, '--',
                   '.github/workflows/ci.yml', 'Dockerfile.feedback-bootstrap',
                   'app/server.py', 'tests/__init__.py', 'tests/test_bootstrap_health.py')
    if not 100 < len(diff) <= 6000:
        raise ValueError('bounded bootstrap diff required')
    return pr, diff


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('bootstrap review restricted to isolated port2')
    pr, diff = verified_pr()
    reviewer = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']['quality_security']
    title = NAME + ' — independent review PR-16'
    description = (
        'YOU ARE QUALITY_SECURITY, independent of the bootstrap author. Review '
        'this frozen diff for test-preservation, scope, unsafe behavior and '
        'credible CI evidence. You have no repository or write tools. The '
        'controller verified GitHub CI=success and local Python 32 / Node 36 '
        'tests at PR head ' + pr['headRefOid'] + '. Do not claim to rerun them. '
        'Return ONLY JSON: {"role":"quality_security","decision":"APPROVE" '
        'or "REQUEST_CHANGES","findings":[],"rationale":"..."}. '
        'If approving, findings may be empty.\n\nFROZEN DIFF:\n' + diff)
    if len(description) > 8000:
        raise ValueError('review issue context too large')
    path = PRIVATE / 'bootstrap-reviews' / 'PILOT-FEEDBACK-BOARD.json'
    expected = {'pr': PR, 'head_sha': pr['headRefOid'],
                'diff_sha256': hashlib.sha256(diff.encode()).hexdigest()}
    receipt = json.loads(path.read_text()) if path.exists() else {**expected, 'stage': 'planned'}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError('review target changed; old approval is obsolete')
    if (receipt['stage'] == 'blocked'
            and receipt.get('category', '').startswith('JSONDecodeError:')
            and not receipt.get('reasoning_limit_retry')):
        receipt.update(stage='retrying', reasoning_limit_retry=1,
                       previous_issue_id=receipt['issue_id'],
                       previous_category=receipt['category'])
        save_receipt(path, receipt)
    if receipt['stage'] in ('reviewed', 'blocked'):
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt['stage'] == 'reviewed' else 1
    if receipt.get('reasoning_limit_retry'):
        title += ' retry1'
        description = ('RETRY AFTER VERIFIED OUTPUT-LIMIT FAILURE. Output budget is '
                       'now 4096 tokens. Give the final JSON decision directly; '
                       'do not spend the budget on a long analysis.\n\n' + description)
    matches = [item for item in cli('list')['issues'] if item['title'] == title]
    if len(matches) > 1:
        raise ValueError('duplicate bootstrap review issue')
    issue = matches[0] if matches else cli('create', '--title', title,
                                           '--description', description, '--status', 'todo')
    if issue['description'] != description or issue.get('assignee_id') not in (None, reviewer):
        raise ValueError('bootstrap review issue drift')
    receipt.update(stage='working', issue_id=issue['id'], reviewer_id=reviewer)
    save_receipt(path, receipt)
    if issue.get('assignee_id') is None:
        cli('assign', issue['id'], '--to-id', reviewer)
    try:
        task_id, answer = completed_output(issue['id'], reviewer)
        review = parse_review(answer)
        receipt.update(stage='reviewed', task_id=task_id, review=review,
                       output_sha256=hashlib.sha256(answer.encode()).hexdigest())
    except Exception as error:
        receipt.update(stage='blocked', category=(type(error).__name__ + ':' + str(error))[:160],
                       owner='quality_security')
    save_receipt(path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt['stage'] == 'reviewed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
