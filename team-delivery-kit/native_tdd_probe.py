"""Run one native implementation task against a disposable Python fixture."""
import argparse
import json
import subprocess
import time

from bootstrap_multica import AUTH, PRIVATE, request
from evalctl import process_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chat-id')
    parser.add_argument('--continue-work', action='store_true')
    args = parser.parse_args()
    token = json.loads(AUTH.read_text())['token']
    registry = json.loads((PRIVATE / 'implementer.json').read_text())
    workspace, agent_id = registry['workspace_id'], registry['agent_id']
    daemon = json.loads(subprocess.check_output(
        ['docker', 'exec', 'delivery-kit-eval-runtime-1', 'multica',
         'daemon', 'status', '--output', 'json'], text=True, env=process_env()))
    if daemon['active_task_count']:
        raise ValueError('evaluation runtime is busy')
    if args.continue_work != bool(args.chat_id):
        raise ValueError('continuation requires an existing chat id')
    chat = {'id': args.chat_id} if args.chat_id else request(
        '/api/chat/sessions/',
        {'agent_id': agent_id, 'title': 'Disposable TDD implementation — multiply'},
        token, workspace)
    prompt = ('The previous turn stopped before delivery. Continue from the '
              'actual files under /workspace. Do not repeat a completed Red step. '
              'Implement the code, run Green and the complete suite, then report '
              'literal commands and results. Do not mark complete on a promise.'
              if args.continue_work else
              'In /workspace, implement multiply(left, right) in calc.py. '
              'First add a failing unittest for it and run that test to '
              'observe Red. Then implement the smallest change, rerun '
              'that test for Green, and run the full suite. Preserve '
              'both existing addition tests. Report the exact commands '
              'and observed results, not promises.')
    sent = request('/api/chat/sessions/' + chat['id'] + '/messages',
                   {'content': prompt}, token, workspace)
    task_id = sent['task_id']
    print(json.dumps({'chat_id': chat['id'], 'task_id': task_id}), flush=True)
    for _ in range(150):
        task = next(t for t in request('/api/agents/' + agent_id + '/tasks',
                       token=token, workspace=workspace) if t['id'] == task_id)
        if task['status'] in ('completed', 'failed', 'cancelled', 'timed_out'):
            break
        time.sleep(2)
    else:
        raise TimeoutError('native implementation task did not settle')
    messages = request('/api/chat/sessions/' + chat['id'] + '/messages',
                       token=token, workspace=workspace)
    replies = [m for m in messages if m.get('task_id') == task_id and m.get('role') == 'assistant']
    sql = ("import sqlite3,json,sys; c=sqlite3.connect('/broker-state/leases.sqlite'); "
           "print(json.dumps(c.execute('SELECT n.request_id, t.tool_count FROM native_bindings n "
           "LEFT JOIN tool_events t USING(request_id) WHERE n.task_id=?',"
           "(sys.argv[1],)).fetchall()))")
    receipt = json.loads(subprocess.check_output(
        ['docker', 'exec', 'delivery-kit-eval-execution-broker-1',
         'python', '-c', sql, task_id], text=True, env=process_env()))
    print(json.dumps({'status': task['status'], 'error': task.get('error'),
                      'assistant_text': [m.get('content', '') for m in replies],
                      'broker_receipt': receipt, 'delivery_qualified': False}), flush=True)
    if task['status'] != 'completed' or not receipt or not any((row[1] or 0) > 0 for row in receipt):
        raise RuntimeError('native implementation task did not prove tool execution')


if __name__ == '__main__':
    main()
