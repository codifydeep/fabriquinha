"""Register idle pilot identities via the native API. Never enqueue work."""
import json

from bootstrap_multica import AUTH, PRIVATE, private_json, request

from model_policy import MODEL
from evalctl import PROJECT
ROLES = {
    'techlead': 'Own delivery, decompose work, resolve blockers or escalate technical decisions to CTO. Do not ask the CEO to route routine technical work.',
    'backend_data': 'Implement only in the assigned workspace using Red-Green-Refactor. Preserve pre-existing tests and return evidence for independent review.',
    'quality_security': 'Review the submitted artifact without editing it. Request changes from its author or approve the exact tested revision. Never approve your own work.',
}


def validate_existing(agent, runtime_id):
    expected = {'runtime_id': runtime_id, 'model': MODEL,
                'max_concurrent_tasks': 1, 'visibility': 'workspace'}
    if any(agent.get(key) != value for key, value in expected.items()):
        raise ValueError('existing pilot configuration drift; refusing silent reuse')


def main():
    account = json.loads(AUTH.read_text())
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    def api(path, payload=None):
        return request(path, payload, account['token'], workspace)
    runtimes = [r for r in api('/api/runtimes/') if r['provider'] == 'hermes'
                and not r.get('profile_id') and r['status'] == 'online' and PROJECT in r['device_info']]
    if len(runtimes) != 1:
        raise ValueError('expected exactly one online isolated Hermes runtime')
    runtime = runtimes[0]
    agents = api('/api/agents/')
    if not isinstance(agents, list):
        raise ValueError('unexpected agent list format')
    result = {}
    for role, responsibility in ROLES.items():
        name = 'eval_' + role
        existing = [a for a in agents if a['name'] == name]
        if len(existing) > 1:
            raise ValueError('duplicate pilot identity')
        if existing:
            agent = existing[0]
            validate_existing(agent, runtime['id'])
        else:
            agent = api('/api/agents/', {
                'name': name, 'description': 'Isolated pilot; delivery qualification pending.',
                'instructions': responsibility + '\nUse English. This installation is NOT qualified. No production repositories, deployment access or credentials. Text is not proof of a tool action. Record blockers and evidence; never claim release acceptance without all checks.',
                'runtime_id': runtime['id'], 'model': MODEL, 'max_concurrent_tasks': 1,
                'visibility': 'workspace',
            })
        result[role] = agent['id']
    target = PRIVATE / 'team.json'
    if not target.exists():
        private_json(target, {'runtime_id': runtime['id'], 'agents': result})
    elif json.loads(target.read_text()) != {'runtime_id': runtime['id'], 'agents': result}:
        raise ValueError('team identity drift; refusing to overwrite registry')
    print(json.dumps({'runtime': runtime['id'], 'agents': result, 'enqueued': 0,
                      'model': MODEL, 'dispatch_performed': False}))


if __name__ == '__main__':
    main()
