"""Enroll C1 backend author and independent Tech Lead reviewer for the pilot."""
import json
import subprocess

from bootstrap_multica import AUTH, PRIVATE, private_json, request
from evalctl import PROJECT
from model_policy import MODEL


AGENTS = {
    'backend_data': (
        'implementation', 'Implement only the assigned feedback-board backend '
        'card in /workspace. Write a new failing test first, observe Red, then '
        'Green and the exact complete suite. Preserve every pre-existing test '
        'and protected file byte-for-byte. Edit only contract-declared files. '
        'No GitHub, Docker, network, credentials or other projects. A textual '
        'claim is not evidence of tool execution.'),
    'frontend': (
        'implementation', 'Implement only the assigned feedback-board web card '
        'in /workspace. Add a failing static-route and UI contract test before '
        'code, observe Red, then Green and the exact complete suite. Preserve '
        'every pre-existing test and API behavior. Edit only contract-declared '
        'files. No GitHub, Docker, network, credentials or other projects. '
        'A textual claim is not evidence of tool execution.'),
    'techlead_reviewer': (
        'review', 'Independently review only the immutable /delivery snapshot. '
        'Never edit files or reproduce Red by overwriting code. Run the '
        'controller-approved complete suite, inspect acceptance and existing '
        'test preservation, then end with a standalone Decision: APPROVE or '
        'Decision: REQUEST_CHANGES;Reason: <specific finding>. No GitHub, '
        'Docker, credentials or other projects.'),
}


def main():
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('delivery identities restricted to isolated port2')
    owner = json.loads(AUTH.read_text())['token']
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    runtime = json.loads((PRIVATE / 'native.json').read_text())['runtime_id']
    existing = request('/api/agents/', token=owner, workspace=workspace)
    ids = {}
    for role, (_, instructions) in AGENTS.items():
        name = 'pilot_' + role
        matches = [agent for agent in existing if agent['name'] == name]
        if len(matches) > 1:
            raise ValueError('duplicate delivery profile')
        expected = {'runtime_id': runtime, 'model': MODEL, 'instructions': instructions,
                    'max_concurrent_tasks': 1, 'visibility': 'workspace'}
        agent = matches[0] if matches else request('/api/agents/', {
            'name': name, **expected,
            'description': 'Isolated feedback-board delivery qualification.'},
            owner, workspace)
        if any(agent.get(key) != value for key, value in expected.items()):
            raise ValueError('delivery profile drift: ' + role)
        ids[role] = agent['id']
    if len(set(ids.values())) != len(ids):
        raise ValueError('author and reviewer are not independent')
    patch = ('import json,os,sys,tempfile; p="/broker-state/native.json"; '
             's=json.load(open(p)); backend,frontend,reviewer=sys.argv[1:4]; '
             '[(None if s["agents"].get(i) in (None,m) else '
             '(_ for _ in ()).throw(ValueError("mode drift"))) '
             'for i,m in ((backend,"implementation"),(frontend,"implementation"),(reviewer,"review"))]; '
             's["agents"][backend]="implementation"; s["agents"][frontend]="implementation"; '
             's["agents"][reviewer]="review"; '
             's["review_requires_snapshot"]=sorted(set(s["review_requires_snapshot"])|{reviewer}); '
             'fd,t=tempfile.mkstemp(dir="/broker-state"); '
             'os.write(fd,json.dumps(s,sort_keys=True).encode()); os.fchmod(fd,0o600); '
             'os.close(fd); os.replace(t,p); print("delivery roles enrolled")')
    subprocess.run(['docker', 'exec', PROJECT + '-execution-broker-1', 'python3',
                    '-c', patch, ids['backend_data'], ids['frontend'],
                    ids['techlead_reviewer']], check=True)
    for role, filename in (('backend_data', 'pilot-backend-data.json'),
                           ('frontend', 'pilot-frontend.json'),
                           ('techlead_reviewer', 'pilot-techlead-reviewer.json')):
        target = PRIVATE / filename
        value = {'agent_id': ids[role], 'workspace_id': workspace, 'runtime_id': runtime}
        if target.exists() and json.loads(target.read_text()) != value:
            raise ValueError('delivery registry drift')
        if not target.exists():
            private_json(target, value)
    print(json.dumps({'roles': ids, 'enqueued': False}))


if __name__ == '__main__':
    main()
