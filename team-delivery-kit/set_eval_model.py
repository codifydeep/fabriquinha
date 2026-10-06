"""Migrate only registered idle evaluation agents to the selected model."""
import json
import subprocess
import urllib.error
import urllib.request

from bootstrap_multica import API, AUTH, PRIVATE, request
from evalctl import process_env
from register_team import MODEL

PREVIOUS = 'deepseek/deepseek-v4-flash-0731'


def planned_agents(agents, team, native):
    by_id = {agent['id']: agent for agent in agents}
    ids = set(team['agents'].values()) | {native['agent_id']}
    if len(ids) != 4 or any(agent_id not in by_id for agent_id in ids):
        raise ValueError('registered evaluation identities do not match API')
    selected = [by_id[agent_id] for agent_id in sorted(ids)]
    if any(not agent['name'].startswith('eval_') or agent.get('model', '') not in ('', PREVIOUS, MODEL)
           for agent in selected):
        raise ValueError('agent identity or model drift')
    return [agent for agent in selected if agent.get('model') != MODEL]


def main():
    token = json.loads(AUTH.read_text())['token']
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    team = json.loads((PRIVATE / 'team.json').read_text())
    native = json.loads((PRIVATE / 'native.json').read_text())
    daemon = json.loads(subprocess.check_output(
        ['docker', 'exec', 'delivery-kit-eval-runtime-1', 'multica', 'daemon', 'status', '--output', 'json'],
        env=process_env(), text=True))
    if daemon['status'] != 'running' or daemon['active_task_count'] != 0:
        raise ValueError('evaluation daemon must be idle for model migration')
    agents = request('/api/agents/', token=token, workspace=workspace)
    changes = planned_agents(agents, team, native)
    for agent in changes:
        path = '/api/agents/' + agent['id'] + '/'
        call = urllib.request.Request(API + path, data=json.dumps({'model': MODEL}).encode(),
            headers={'Authorization': 'Bearer ' + token, 'X-Workspace-ID': workspace,
                     'Content-Type': 'application/json'}, method='PUT')
        try:
            with urllib.request.urlopen(call, timeout=15) as response:
                updated = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'{path}: HTTP {error.code}') from None
        if updated.get('id') != agent['id'] or updated.get('model') != MODEL:
            raise RuntimeError('model update not confirmed; reconcile before retry')
    after = request('/api/agents/', token=token, workspace=workspace)
    if planned_agents(after, team, native):
        raise RuntimeError('some evaluation agents still have the prior model')
    print(json.dumps({'model': MODEL, 'evaluation_agents': 4, 'updated': len(changes),
                      'inference_dispatched': False}))


if __name__ == '__main__':
    main()
