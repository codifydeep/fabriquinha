"""One real Multica -> broker -> Hermes -> model evaluation task; no product work."""
import json
import argparse
import re
import subprocess
import time

from bootstrap_multica import API, AUTH, PRIVATE, request, private_json
from evalctl import process_env
from register_team import MODEL

OLD_INSTRUCTIONS = 'No model calls or product work. Prompts intentionally blocked.'
NEW_INSTRUCTIONS = ('Evaluation only: answer a bounded text prompt using the selected model. '
                    'Do not use tools or change files. This is not a software delivery.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chat-id')
    parser.add_argument('--expected', default='READY')
    parser.add_argument('--require-resume', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Z0-9]{1,16}', args.expected):
        raise ValueError('invalid static evaluation response')
    token = json.loads(AUTH.read_text())['token']
    registry = json.loads((PRIVATE / 'native.json').read_text())
    workspace = registry['workspace_id']
    daemon = json.loads(subprocess.check_output(
        ['docker', 'exec', 'delivery-kit-eval-runtime-1', 'multica', 'daemon', 'status', '--output', 'json'],
        text=True, env=process_env()))
    if daemon['active_task_count'] != 0:
        raise ValueError('native evaluation daemon is busy')
    agent = next(a for a in request('/api/agents/', token=token, workspace=workspace)
                 if a['id'] == registry['agent_id'])
    if agent['model'] != MODEL or agent['instructions'] not in (OLD_INSTRUCTIONS, NEW_INSTRUCTIONS):
        raise ValueError('probe identity/model/instructions drift')
    if agent['instructions'] == OLD_INSTRUCTIONS:
        import urllib.request
        call = urllib.request.Request(API + '/api/agents/' + agent['id'] + '/',
            data=json.dumps({'instructions': NEW_INSTRUCTIONS}).encode(),
            headers={'Authorization': 'Bearer ' + token, 'X-Workspace-ID': workspace,
                     'Content-Type': 'application/json'}, method='PUT')
        with urllib.request.urlopen(call, timeout=15) as response:
            updated = json.load(response)
        if updated.get('instructions') != NEW_INSTRUCTIONS:
            raise RuntimeError('evaluation instructions not confirmed')
    chat = {'id': args.chat_id} if args.chat_id else request('/api/chat/sessions/',
        {'agent_id': agent['id'], 'title': 'Bounded DeepSeek v4.1 native dispatch smoke'},
        token, workspace)
    sent = request('/api/chat/sessions/' + chat['id'] + '/messages',
                   {'content': 'Evaluation only. Reply with exactly ' + args.expected +
                               '. No tools. Do not change files.'},
                   token, workspace)
    task_id = sent['task_id']
    print(json.dumps({'task_id': task_id, 'chat_id': chat['id'], 'model': MODEL}), flush=True)
    for _ in range(75):
        tasks = request('/api/agents/' + agent['id'] + '/tasks', token=token, workspace=workspace)
        task = next(item for item in tasks if item['id'] == task_id)
        if task['status'] in ('completed', 'failed', 'cancelled', 'timed_out'):
            print(json.dumps({'task_status': task['status'],
                              'error': task.get('error'),
                              'session_id_present': bool(task.get('session_id'))}), flush=True)
            break
        time.sleep(2)
    else:
        raise TimeoutError('native model task did not settle')
    sql = '''import sqlite3,json,sys
c=sqlite3.connect('/broker-state/leases.sqlite')
rows=c.execute('SELECT l.status,e.method,e.success FROM native_bindings n JOIN leases l USING(request_id) LEFT JOIN acp_events e USING(request_id) WHERE n.task_id=?',(sys.argv[1],)).fetchall()
print(json.dumps(rows))
'''
    receipt = json.loads(subprocess.check_output(['docker', 'exec',
        'delivery-kit-eval-execution-broker-1', 'python', '-c', sql, task_id],
        text=True, env=process_env()))
    print(json.dumps({'broker_receipt': receipt}), flush=True)
    messages = request('/api/chat/sessions/' + chat['id'] + '/messages', token=token,
                       workspace=workspace)
    replies = [message for message in messages if message.get('task_id') == task_id
               and message.get('role') == 'assistant']
    exact_reply = len(replies) == 1 and replies[0].get('content', '').strip() == args.expected
    print(json.dumps({'assistant_reply_exact': exact_reply}), flush=True)
    if task['status'] != 'completed' or not any(method == 'session/prompt' and success == 1
                                                for _, method, success in receipt) or not exact_reply:
        raise RuntimeError('native model path not qualified')
    if args.require_resume and not any(method == 'session/resume' and success == 1
                                       for _, method, success in receipt):
        raise RuntimeError('native model session did not resume')


if __name__ == '__main__':
    main()
