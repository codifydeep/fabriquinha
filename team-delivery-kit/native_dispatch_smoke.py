"""Native task qualification: actual dispatch, intentionally blocked inference."""
import json
import subprocess
import time
import sys
from bootstrap_multica import AUTH, PRIVATE, request, private_json


def main():
    registry = json.loads((PRIVATE / 'native.json').read_text())
    owner = json.loads(AUTH.read_text())['token']
    def api(path, body=None):
        return request(path, body, owner, registry['workspace_id'])
    chat_file = PRIVATE / 'native-chat.json'
    if chat_file.exists():
        chat = json.loads(chat_file.read_text())
    else:
        created = api('/api/chat/sessions/', {'agent_id': registry['agent_id'], 'title': 'Offline native boundary qualification'})
        chat = {'id': created['id']}
        private_json(chat_file, chat)
    sent = api('/api/chat/sessions/' + chat['id'] + '/messages',
               {'content': 'Offline boundary probe. Do not call a model. The execution policy intentionally rejects session/prompt. This is not product work or a delivery success.'})
    task_id = sent['task_id']
    print(json.dumps({'native_task_id': task_id, 'chat_id': chat['id'], 'expected': 'prompt_policy_rejection'}), flush=True)
    for _ in range(45):
        tasks = api('/api/agents/' + registry['agent_id'] + '/tasks')
        task = next(t for t in tasks if t['id'] == task_id)
        if task['status'] in ('failed', 'completed', 'cancelled', 'timed_out'):
            print(json.dumps({k: task.get(k) for k in ('id', 'status', 'error', 'failure_reason', 'session_id', 'prior_session_id')}), flush=True)
            break
        time.sleep(2)
    else:
        raise TimeoutError('native task did not settle within qualification window')
    query = """import sqlite3,json,sys
c=sqlite3.connect('/broker-state/leases.sqlite')
c.row_factory=sqlite3.Row
rows=c.execute('SELECT n.task_id,n.scope,l.status FROM native_bindings n LEFT JOIN leases l USING(request_id) WHERE n.task_id=?',(sys.argv[1],)).fetchall()
print(json.dumps([dict(r) for r in rows]))
"""
    evidence = json.loads(subprocess.check_output(['docker', 'exec', 'delivery-kit-eval-execution-broker-1',
                       'python', '-c', query, task_id], text=True))
    print(json.dumps({'broker_evidence': evidence, 'model_called': False}))
    assert evidence, 'native task never reached authorized broker execution'
    assert task['status'] == 'failed', 'policy rejection must not be a completed delivery'
    assert 'prompts disabled' in (task.get('error') or ''), 'failure occurred before the intended policy gate'
    events_query = "import sqlite3,json,sys; c=sqlite3.connect('/broker-state/leases.sqlite'); print(json.dumps(c.execute('SELECT e.method,e.session_id,e.success FROM acp_events e JOIN native_bindings n USING(request_id) WHERE n.task_id=?',(sys.argv[1],)).fetchall()))"
    events = json.loads(subprocess.check_output(['docker', 'exec', 'delivery-kit-eval-execution-broker-1',
                                               'python', '-c', events_query, task_id], text=True))
    print(json.dumps({'acp_events': events}))
    if '--require-resume' in sys.argv:
        assert any(method == 'session/resume' and success == 1 for method, _, success in events), 'no proven session resume'


if __name__ == '__main__':
    main()
