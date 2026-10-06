"""Bounded native read-only tool probe in the disposable Multica workspace."""
import json
import subprocess
import time
import urllib.request

from bootstrap_multica import API, AUTH, PRIVATE, request
from evalctl import process_env
from register_team import MODEL


INSTRUCTIONS = (
    'Evaluation only. For a request to inspect /delivery/artifact.txt, use a '
    'read-only tool and report the exact verification marker. Do not modify files, '
    'run arbitrary commands, or claim a tool was used if it was not. This is '
    'not a software delivery.'
)


def main():
    token = json.loads(AUTH.read_text())['token']
    registry = json.loads((PRIVATE / 'native.json').read_text())
    workspace, agent_id = registry['workspace_id'], registry['agent_id']
    daemon = json.loads(subprocess.check_output(
        ['docker', 'exec', 'delivery-kit-eval-runtime-1', 'multica',
         'daemon', 'status', '--output', 'json'], text=True, env=process_env()))
    if daemon['active_task_count']:
        raise ValueError('evaluation runtime is busy')
    agent = next(a for a in request('/api/agents/', token=token, workspace=workspace)
                 if a['id'] == agent_id)
    if agent['model'] != MODEL or agent['name'] != 'eval_native_boundary':
        raise ValueError('probe identity/model drift')
    if agent['instructions'] != INSTRUCTIONS:
        call = urllib.request.Request(API + '/api/agents/' + agent_id + '/',
            data=json.dumps({'instructions': INSTRUCTIONS}).encode(),
            headers={'Authorization': 'Bearer ' + token, 'X-Workspace-ID': workspace,
                     'Content-Type': 'application/json'}, method='PUT')
        with urllib.request.urlopen(call, timeout=15) as response:
            updated = json.load(response)
        if updated.get('instructions') != INSTRUCTIONS:
            raise RuntimeError('probe instructions not confirmed')
    chat = request('/api/chat/sessions/',
                   {'agent_id': agent_id, 'title': 'Read-only tool execution probe'},
                   token, workspace)
    sent = request('/api/chat/sessions/' + chat['id'] + '/messages',
                   {'content': 'Use a tool to read /delivery/artifact.txt. Reply with its '
                               'exact verification marker. Do not infer from the filename. '
                               'If a read tool is unavailable, say so explicitly.'},
                   token, workspace)
    task_id = sent['task_id']
    print(json.dumps({'chat_id': chat['id'], 'task_id': task_id}), flush=True)
    for _ in range(90):
        task = next(t for t in request('/api/agents/' + agent_id + '/tasks',
                       token=token, workspace=workspace) if t['id'] == task_id)
        if task['status'] in ('completed', 'failed', 'cancelled', 'timed_out'):
            break
        time.sleep(2)
    else:
        raise TimeoutError('read-only probe did not settle')
    messages = request('/api/chat/sessions/' + chat['id'] + '/messages',
                       token=token, workspace=workspace)
    replies = [m for m in messages if m.get('task_id') == task_id and m.get('role') == 'assistant']
    sql = ("import sqlite3,json,sys; c=sqlite3.connect('/broker-state/leases.sqlite'); "
           "print(json.dumps(c.execute('SELECT t.tool_count FROM tool_events t JOIN "
           "native_bindings n USING(request_id) WHERE n.task_id=?',(sys.argv[1],)).fetchall()))")
    receipt = json.loads(subprocess.check_output(
        ['docker', 'exec', 'delivery-kit-eval-execution-broker-1',
         'python', '-c', sql, task_id], text=True, env=process_env()))
    tool_count = sum(row[0] for row in receipt)
    exact_marker = 'PILOT-6F8C2A19' in '\n'.join(m.get('content', '') for m in replies)
    print(json.dumps({'status': task['status'], 'error': task.get('error'),
                      'assistant_text': [m.get('content', '') for m in replies],
                      'tool_call_count': tool_count, 'exact_marker': exact_marker}), flush=True)
    if task['status'] != 'completed' or tool_count < 1 or not exact_marker:
        raise RuntimeError('native read-only tool execution not qualified')


if __name__ == '__main__':
    main()
