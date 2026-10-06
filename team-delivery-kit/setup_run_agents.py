"""Enroll two independent, run-scoped agents without dispatching work."""
import json
import subprocess

from bootstrap_multica import AUTH, PRIVATE, private_json, request
from evalctl import PROJECT
from model_policy import MODEL
from portable_contract import from_environment
from portable_run_spec import load as load_run_spec
from test_runner_policy import workspace_command


def main():
    contract = from_environment()
    spec = load_run_spec(contract)
    if not spec:
        raise ValueError('a run spec is required for run-scoped agents')
    owner = json.loads(AUTH.read_text())['token']
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    runtime = json.loads((PRIVATE / 'native.json').read_text())['runtime_id']
    def api(path, body=None):
        return request(path, body, owner, workspace)
    existing = api('/api/agents/')
    command = workspace_command(contract['test_command'], contract['test_roots'])
    tag = spec['label'].lower().replace('-', '')
    instructions = {
        'implementation': (
            'Run-scoped TDD implementation in /workspace only. Preserve every '
            'pre-existing test and protected file byte-for-byte. Add a new test '
            'before code, observe Red, then Green, then run the complete suite. '
            'Use this exact full-suite command as one terminal call for each phase: '
            + command + '. Edit only contract-declared files. Do not access '
            'GitHub, Docker, network, credentials or other projects. If the '
            'command is denied, report the denial rather than simulating it.'),
        'review': (
            'Independent immutable review of /delivery only. Never edit files '
            'or review your own work. Verify the acceptance criteria, new tests, '
            'pre-existing test integrity and complete suite with the controlled '
            'review validation tool. Do not rerun Red. ' + spec['review_instruction']),
    }
    identities = {}
    for role in ('implementation', 'review'):
        name = 'delivery_' + role + '_' + tag
        matches = [agent for agent in existing if agent['name'] == name]
        if len(matches) > 1:
            raise ValueError('duplicate run agent identity')
        if matches:
            agent = matches[0]
            if any(agent.get(key) != value for key, value in {
                'runtime_id': runtime, 'model': MODEL,
                'instructions': instructions[role], 'max_concurrent_tasks': 1,
                'visibility': 'workspace'}.items()):
                raise ValueError('run agent configuration drift')
        else:
            agent = api('/api/agents/', {'name': name, 'runtime_id': runtime,
                        'model': MODEL, 'description': 'Isolated portable delivery pilot.',
                        'instructions': instructions[role],
                        'max_concurrent_tasks': 1, 'visibility': 'workspace'})
        identities[role] = agent['id']
    patch = ('import json,os,sys,tempfile; p="/broker-state/native.json"; '
             's=json.load(open(p)); i,r=sys.argv[1:3]; '
             's["agents"][i]="implementation"; s["agents"][r]="review"; '
             's["review_requires_snapshot"]=sorted(set(s["review_requires_snapshot"])|{r}); '
             'fd,t=tempfile.mkstemp(dir="/broker-state"); '
             'os.write(fd,json.dumps(s,sort_keys=True).encode()); os.fchmod(fd,0o600); '
             'os.close(fd); os.replace(t,p); print("run identities enrolled")')
    subprocess.run(['docker', 'exec', PROJECT + '-execution-broker-1', 'python3', '-c',
                    patch, identities['implementation'], identities['review']], check=True)
    for role, filename in (('implementation', spec['implementer_registry']),
                           ('review', spec['reviewer_registry'])):
        data = {'agent_id': identities[role], 'workspace_id': workspace,
                'runtime_id': runtime}
        path = PRIVATE / filename
        if path.exists() and json.loads(path.read_text()) != data:
            raise ValueError('run agent registry drift')
        if not path.exists():
            private_json(path, data)
    print(json.dumps({'label': spec['label'], 'enqueued': False,
                      'agents': identities}))


if __name__ == '__main__':
    main()
