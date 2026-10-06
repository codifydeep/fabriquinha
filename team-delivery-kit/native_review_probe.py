"""Ask the independent evaluation reviewer to inspect one frozen snapshot."""
import json
import subprocess
import time

from bootstrap_multica import AUTH, PRIVATE, request
from evalctl import process_env


def main():
    token = json.loads(AUTH.read_text())['token']
    registry = json.loads((PRIVATE / 'reviewer.json').read_text())
    workspace, agent_id = registry['workspace_id'], registry['agent_id']
    daemon = json.loads(subprocess.check_output(
        ['docker', 'exec', 'delivery-kit-eval-runtime-1', 'multica',
         'daemon', 'status', '--output', 'json'], text=True, env=process_env()))
    if daemon['active_task_count']:
        raise ValueError('evaluation runtime is busy')
    chat = request('/api/chat/sessions/',
                   {'agent_id': agent_id, 'title': 'Independent review — frozen TDD snapshot'},
                   token, workspace)
    sent = request('/api/chat/sessions/' + chat['id'] + '/messages',
                   {'content': 'Review the frozen delivery mounted at /delivery. '
                               'Read calc.py, test_calc.py and manifest.json. Run the '
                               'full Python unittest suite from /delivery. Check both '
                               'preexisting addition assertions and new multiply test. '
                               'Do not edit files. Report findings and a clear '
                               'APPROVE or REQUEST_CHANGES decision. The historical Red '
                               'result is tracked separately by the controller; do not '
                               'claim it is proven by the snapshot alone.'},
                   token, workspace)
    task_id = sent['task_id']
    print(json.dumps({'chat_id': chat['id'], 'task_id': task_id}), flush=True)
    for _ in range(120):
        task = next(t for t in request('/api/agents/' + agent_id + '/tasks',
                       token=token, workspace=workspace) if t['id'] == task_id)
        if task['status'] in ('completed', 'failed', 'cancelled', 'timed_out'):
            break
        time.sleep(2)
    else:
        raise TimeoutError('native review did not settle')
    messages = request('/api/chat/sessions/' + chat['id'] + '/messages',
                       token=token, workspace=workspace)
    replies = [m.get('content', '') for m in messages if m.get('task_id') == task_id
               and m.get('role') == 'assistant']
    print(json.dumps({'status': task['status'], 'error': task.get('error'),
                      'assistant_text': replies, 'review_qualified': False}), flush=True)


if __name__ == '__main__':
    main()
