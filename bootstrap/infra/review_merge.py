"""Reviewer-only merge entrypoint for cooperative Hermes workers.

GitHub enforces this SHA-bound status plus CI; the shared admin credential is
not an adversarial identity boundary. Never invoke this to approve one's work.
"""
import argparse
import json
import os
import re
import sqlite3
from pathlib import Path
from delivery_gate import run
from release_policy import active_release
from review_policy import validate_review

def reject_governance_files(files,changed_count):
    if not isinstance(files,list) or type(changed_count) is not int or len(files)!=changed_count:
        raise ValueError('complete PR file inventory required')
    for item in files:
        paths=[item.get('path',item.get('filename'))]
        if item.get('previous_filename'): paths.append(item['previous_filename'])
        for path in paths:
            if not isinstance(path,str) or path.startswith(('/', './')) or '..' in path.split('/'):
                raise ValueError('invalid PR path')
            if path.startswith(('scripts/ci/','.github/workflows/')):
                raise ValueError('governance-only review/integration required for '+path)

def validate_context(task, handoff, claim, profile, run_id):
    if task['status'] != 'running' or str(task['current_run_id']) != str(run_id):
        raise ValueError('approval requires the current live review run')
    if claim.get('source_status') != 'review':
        raise ValueError('only a run claimed from review can approve')
    error = validate_review(handoff.get('implementer'), profile)
    if error or task['assignee'] != profile or handoff.get('reviewer') != profile:
        raise ValueError(error or 'review identity differs from recorded handoff')


def current_context(db, task_id, profile, run_id):
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task:
            raise ValueError('unknown task')
        def event(kind, event_run=None):
            sql = 'SELECT payload FROM task_events WHERE task_id=? AND kind=?'
            params = [task_id, kind]
            if event_run is not None:
                sql += ' AND run_id=?'
                params.append(event_run)
            row = conn.execute(sql + ' ORDER BY id DESC LIMIT 1', params).fetchone()
            return json.loads(row['payload']) if row else {}
        handoff = event('review_requested')
        validate_context(task, handoff, event('claimed', task['current_run_id']), profile, run_id)
        result = {key: task[key] for key in ('status', 'current_run_id', 'assignee', 'workspace_path', 'branch_name')}
        result['handoff'] = handoff
    conn.close()
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', required=True)
    parser.add_argument('--pr', required=True, type=int)
    parser.add_argument('--sha', required=True)
    evidence_args = parser.add_mutually_exclusive_group(required=True)
    evidence_args.add_argument('--evidence', type=Path)
    evidence_args.add_argument('--evidence-text')
    args = parser.parse_args()
    profile = os.environ.get('HERMES_PROFILE')
    if os.environ.get('HERMES_KANBAN_TASK') != args.task:
        raise ValueError('must run inside the assigned Kanban reviewer worker')
    release = active_release()
    board = release.get('board', 'truco-online')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', board):
        raise ValueError('invalid release board')
    if release.get('attempt') and os.environ.get('HERMES_EXECUTION_ATTEMPT') != release['attempt']:
        raise ValueError('worker belongs to another execution attempt')
    db = Path('/opt/data/kanban/boards') / board / 'kanban.db'
    if db.with_name('MAINTENANCE').exists() or db.with_name('READ_ONLY').exists():
        raise ValueError('review merge disabled for maintenance or archived board')
    run_id = os.environ.get('HERMES_KANBAN_RUN_ID')
    task = current_context(db, args.task, profile, run_id)
    path, branch = task['workspace_path'], task['branch_name']
    evidence = (args.evidence.read_text() if args.evidence else args.evidence_text).strip()
    if len(evidence) < 100:
        raise ValueError('substantive independent review evidence required')
    if run(path, 'git', 'rev-parse', 'HEAD') != args.sha or run(path, 'git', 'status', '--porcelain'):
        raise ValueError('reviewed SHA must match clean local workspace')
    pr = json.loads(run(path, 'gh', 'pr', 'view', str(args.pr), '--repo', 'codifydeep/truco-online',
        '--json', 'headRefOid,headRefName,baseRefName,statusCheckRollup,state,files,changedFiles'))
    files=json.loads(run(path,'gh','api',f'repos/codifydeep/truco-online/pulls/{args.pr}/files?per_page=100'))
    reject_governance_files(files,pr['changedFiles'])
    if (pr['headRefOid'], pr['headRefName'], pr['baseRefName'], pr['state']) != (args.sha, branch, active_release()['branch'], 'OPEN'):
        raise ValueError('PR identity/base/SHA differs from reviewed task')
    if not any(c.get('name') == 'governance' and c.get('conclusion') == 'SUCCESS' for c in pr['statusCheckRollup']):
        raise ValueError('governance CI must pass before approval')
    body = f"Hermes independent review: {profile}; task {args.task}; run {os.environ['HERMES_KANBAN_RUN_ID']}; SHA {args.sha}\n\n{evidence}"
    run(path, 'gh', 'pr', 'comment', str(args.pr), '--repo', 'codifydeep/truco-online', '--body', body)
    if current_context(db, args.task, profile, run_id) != task or active_release() != release:
        raise ValueError('review context changed before approval')
    run(path, 'gh', 'api', '--method', 'POST', f'repos/codifydeep/truco-online/statuses/{args.sha}',
        '-f', 'state=success', '-f', 'context=hermes-independent-review', '-f', f'description={profile}: {args.task}; independent review')
    if current_context(db, args.task, profile, run_id) != task or active_release() != release:
        run(path, 'gh', 'api', '--method', 'POST', f'repos/codifydeep/truco-online/statuses/{args.sha}',
            '-f', 'state=failure', '-f', 'context=hermes-independent-review', '-f', 'description=Review run changed; new independent review required')
        raise ValueError('review context changed before merge')
    merged = json.loads(run(path, 'gh', 'api', '--method', 'PUT', f'repos/codifydeep/truco-online/pulls/{args.pr}/merge',
                           '-f', f'sha={args.sha}', '-f', 'merge_method=merge'))
    if not merged.get('merged'):
        raise ValueError('GitHub refused merge: ' + str(merged.get('message')))
    print('Merged verified PR', args.pr, 'at', merged['sha'])

if __name__ == '__main__':
    main()
