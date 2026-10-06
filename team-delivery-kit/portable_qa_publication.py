"""Publish a verified QA repair without rewriting the failed delivery as success."""
import re


def _put(cli, issue_id, key, value):
    existing = cli('metadata', 'list', issue_id)
    if not isinstance(existing, dict):
        raise ValueError('QA recovery metadata unavailable')
    if key in existing and existing[key] != value:
        raise ValueError('QA recovery metadata drift: ' + key)
    if key not in existing:
        cli('metadata', 'set', issue_id, '--key', key, '--value', value,
            '--type', 'string')


def publish(cli, incident, retry, child, *, recovery, cto=None):
    """Close diagnosis and supersede its failed parent after exact child QA.

    The parent is cancelled, never done: its original SHA failed deployed QA.
    All writes are restart-safe, and none wakes an agent.
    """
    if incident.get('phase') == 'browser':
        browser = child.get('browser_qa', {})
        if (browser.get('status') != 'passed' or browser.get('cleanup') != 'passed'
                or browser.get('automated') is not True
                or browser.get('identity', {}).get('source_sha') != child.get('merge_sha')
                or browser.get('result', {}).get('source_sha') != child.get('merge_sha')
                or browser.get('result', {}).get('status') != 'passed'):
            raise ValueError('browser recovery requires exact child real-browser proof')
    if (recovery.get('stage') != 'qa_recovered_by_child'
            or child.get('stage') != 'deployed_qa_passed'
            or child.get('base_sha') != incident['source_sha']
            or child.get('merge_sha') != recovery.get('merge_sha')
            or child.get('pr_url') != recovery.get('pr_url')
            or child.get('deployment', {}).get('url') != recovery.get('qa_url')
            or child.get('label') != recovery.get('label')
            or not re.fullmatch(r'[0-9a-f]{40}', recovery['merge_sha'])):
        raise ValueError('QA recovery publication requires exact child receipt')
    parent_id = incident['parent_issue_id']
    diagnosis_id = incident['child_issue_id']
    child_id = child['issue_id']
    if retry and retry.get('parent_issue_id') != diagnosis_id:
        raise ValueError('QA diagnosis retry parent drift')
    if cto and cto.get('parent_issue_id') != diagnosis_id:
        raise ValueError('QA CTO parent drift')
    if len({parent_id, diagnosis_id, child_id}) != 3:
        raise ValueError('QA recovery issue identity collision')
    parent = cli('get', parent_id)
    diagnosis = cli('get', diagnosis_id)
    repair = cli('get', child_id)
    skipped_techlead = (bool(cto) and diagnosis['status'] in ('blocked', 'cancelled')
                        and incident.get('dispatch') in ('not_started',
                                                         'budget_paused'))
    if (parent.get('id') != parent_id or parent['status'] not in ('blocked', 'cancelled')
            or diagnosis.get('parent_issue_id') != parent_id
            or (diagnosis['status'] not in ('todo', 'in_progress', 'done')
                and not skipped_techlead)
            or repair['status'] != 'done'):
        raise ValueError('QA recovery board hierarchy or state drift')
    if skipped_techlead and cli('runs', diagnosis_id):
        raise ValueError('skipped QA diagnosis unexpectedly has runs')
    if retry:
        retry_card = cli('get', retry['child_issue_id'])
        if (retry_card.get('parent_issue_id') != diagnosis_id
                or retry_card['status'] not in ('todo', 'in_progress', 'done')):
            raise ValueError('QA diagnosis retry board drift')
    if cto:
        cto_card = cli('get', cto['child_issue_id'])
        if (cto_card.get('parent_issue_id') != diagnosis_id
                or cto_card['status'] not in ('todo', 'in_progress', 'done')):
            raise ValueError('QA CTO board drift')
    fields = {'qa_failed_source_sha': incident['source_sha'],
              'qa_repair_issue_id': child_id,
              'qa_repair_pr_url': recovery['pr_url'],
              'qa_repair_merge_sha': recovery['merge_sha'],
              'qa_repair_qa_url': recovery['qa_url']}
    for key, value in fields.items():
        _put(cli, parent_id, key, value)
    diagnosis_cards = ([diagnosis_id]
                       + ([retry['child_issue_id']] if retry else [])
                       + ([cto['child_issue_id']] if cto else []))
    for issue_id in diagnosis_cards:
        _put(cli, issue_id, 'qa_repair_issue_id', child_id)
        _put(cli, issue_id, 'qa_repair_merge_sha', recovery['merge_sha'])
        target = 'cancelled' if skipped_techlead and issue_id == diagnosis_id else 'done'
        if cli('get', issue_id)['status'] != target:
            cli('status', issue_id, target, '--no-start')
    metadata = cli('metadata', 'list', parent_id)
    gate = metadata.get('execution_gate')
    if gate not in ('blocked_' + incident['phase'] + '_qa',
                    'qa_recovered_by_child'):
        raise ValueError('QA recovery parent gate drift')
    if gate != 'qa_recovered_by_child':
        cli('metadata', 'set', parent_id, '--key', 'execution_gate',
            '--value', 'qa_recovered_by_child', '--type', 'string')
    if cli('get', parent_id)['status'] != 'cancelled':
        cli('status', parent_id, 'cancelled', '--no-start')
    return {'parent_status': 'cancelled',
            'diagnosis_status': 'cancelled' if skipped_techlead else 'done',
            'repair_issue_id': child_id}
