"""Bounded, independent two-part review of the same frozen bootstrap SHA."""
import hashlib
import json

from bootstrap_multica import BACKEND_PORT, PRIVATE
from bootstrap_review import CHECKOUT, PR, REPO, command, verified_pr
from evalctl import PROJECT
from planning_intake import NAME, completed_output
from release_eval import save_receipt
from start_eval import cli


PARTS = {
    'tests_ci': ('.github/workflows/ci.yml', 'tests/__init__.py',
                 'tests/test_bootstrap_health.py'),
    'runtime': ('Dockerfile.feedback-bootstrap', 'app/server.py'),
}


def parse_chunk(text, allowed_paths=()):
    if not isinstance(text, str) or not 0 < len(text) <= 1200:
        raise ValueError('invalid chunk review size')
    value = json.loads(text.strip())
    if not isinstance(value, dict) or set(value) != {'role', 'decision', 'finding'}:
        raise ValueError('invalid chunk review schema')
    if value['role'] != 'quality_security' or value['decision'] not in ('APPROVE', 'REQUEST_CHANGES'):
        raise ValueError('invalid chunk reviewer or decision')
    if not isinstance(value['finding'], str) or not 20 <= len(value['finding']) <= 600:
        raise ValueError('invalid chunk finding')
    if allowed_paths and not any(path in value['finding'] for path in allowed_paths):
        raise ValueError('review lacks file-specific evidence')
    return value


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('split review restricted to isolated port2')
    pr, _ = verified_pr()
    reviewer = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']['quality_security']
    frozen = {part: command('git', '-C', str(CHECKOUT), 'diff',
                            'main...' + pr['headRefOid'], '--', *paths)
              for part, paths in PARTS.items()}
    if any(not 100 < len(diff) <= 3500 for diff in frozen.values()):
        raise ValueError('split diff outside bounds')
    identity = {'pr': PR, 'head_sha': pr['headRefOid'],
                'part_hashes': {part: hashlib.sha256(diff.encode()).hexdigest()
                                for part, diff in frozen.items()}}
    path = PRIVATE / 'bootstrap-reviews' / (NAME + '-split.json')
    receipt = json.loads(path.read_text()) if path.exists() else {**identity, 'stage': 'planned', 'parts': {}}
    if any(receipt.get(key) != value for key, value in identity.items()):
        raise ValueError('split review target changed')
    if (receipt['stage'] == 'reviewed' and receipt.get('decision') == 'APPROVE'
            and not receipt.get('evidence_round')
            and all(p['review']['finding'] == 'none' for p in receipt['parts'].values())):
        receipt['previous_parts'] = receipt['parts']
        receipt['parts'] = {}
        receipt['stage'] = 'evidence_required'
        receipt['evidence_round'] = 1
        save_receipt(path, receipt)
    if receipt['stage'] in ('reviewed', 'blocked'):
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt['stage'] == 'reviewed' else 1
    for part, diff in frozen.items():
        if part in receipt['parts']:
            continue
        title = NAME + ' — independent bootstrap PR-16 review ' + part
        if receipt.get('evidence_round'):
            title += ' evidence1'
        description = (
            'YOU ARE QUALITY_SECURITY. Independently review ONLY this frozen '
            'PR diff section at SHA ' + pr['headRefOid'] + '. The controller '
            'verified exact-SHA CI success and full local Python (32) / Node '
            '(36) suites; do not claim you ran them. Check for test weakening, '
            'scope creep and unsafe code. Do not edit or approve on GitHub. '
            'Return ONLY one compact JSON object under 350 characters: '
            '{"role":"quality_security","decision":"APPROVE" or '
            '"REQUEST_CHANGES","finding":"one concrete observation naming '
            'an exact file in this diff and what it proves or fails"}. '
            'APPROVE with finding=none is invalid. '
            'No Markdown or additional keys.\n\nFROZEN DIFF:\n' + diff)
        matches = [item for item in cli('list')['issues'] if item['title'] == title]
        if len(matches) > 1:
            raise ValueError('duplicate split review issue')
        issue = matches[0] if matches else cli('create', '--title', title,
                                               '--description', description, '--status', 'todo')
        if issue['description'] != description or issue.get('assignee_id') not in (None, reviewer):
            raise ValueError('split review issue drift')
        receipt.update(stage='working', active=part, **{'issue_' + part: issue['id']})
        save_receipt(path, receipt)
        if issue.get('assignee_id') is None:
            cli('assign', issue['id'], '--to-id', reviewer)
        try:
            task_id, answer = completed_output(issue['id'], reviewer)
            result = parse_chunk(answer, PARTS[part])
        except Exception as error:
            receipt.update(stage='blocked', owner='quality_security',
                           category=(type(error).__name__ + ':' + str(error))[:160])
            save_receipt(path, receipt)
            print(json.dumps(receipt, sort_keys=True))
            return 1
        receipt['parts'][part] = {'issue_id': issue['id'], 'task_id': task_id,
                                  'review': result,
                                  'output_sha256': hashlib.sha256(answer.encode()).hexdigest()}
        save_receipt(path, receipt)
    receipt['stage'] = 'reviewed'
    receipt['decision'] = ('APPROVE' if all(p['review']['decision'] == 'APPROVE'
                                      for p in receipt['parts'].values()) else 'REQUEST_CHANGES')
    receipt.pop('active', None)
    save_receipt(path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
