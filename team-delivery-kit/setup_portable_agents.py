"""Register isolated non-calculator agents; no task is dispatched here."""
import json
import subprocess

from bootstrap_multica import AUTH, PRIVATE, request, private_json
from evalctl import PROJECT
from register_team import MODEL


IMPLEMENTER = (
    'Disposable text-slug project only. Work in /workspace. Preserve all '
    'pre-existing tests and protected files. Implement the assigned issue with '
    'Red-Green-Refactor. Add a new test file before code, show the failing test, '
    'then run the complete suite. Do not access GitHub, Docker, network, keys or '
    'other projects. A textual claim is not a tool execution.'
)
REVIEWER = (
    'Independent immutable review only. Inspect /delivery, never /workspace. '
    'Do not edit files. Check every acceptance case, especially word-boundary '
    'truncation. Run cd /delivery && PYTHONDONTWRITEBYTECODE=1 python3 -m '
    'unittest discover -s slug_tests -q 2>&1. End with one standalone line '
    'Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>, '
    'then concise evidence. '
    'No GitHub, Docker, network, keys or other projects.'
)
IMPLEMENTER_V2 = (
    'Disposable portable TDD delivery only. Work exclusively in /workspace. '
    'Preserve every existing test byte-for-byte. Follow the issue acceptance '
    'criteria. Write the new test before implementation and observe Red, Green, '
    'then the full suite. For each test phase use exactly this approved command '
    'as one terminal call, without probes, pipes, extra commands or rewrites: '
    'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover '
    '-s slug_tests -q 2>&1. Edit only contract-declared files with normal edit '
    'tools. Do not use GitHub, Docker, network, keys or another project. '
    'If the exact command is denied, stop and report that denial.'
)
REVIEWER_V2 = (
    'Independent immutable review only. Inspect /delivery, never /workspace. '
    'Do not edit. Verify each acceptance case and unchanged baseline tests. '
    'Run the complete suite at /delivery. End with one standalone line '
    'Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>, '
    'then concise evidence. No GitHub, Docker, keys or other projects.'
)


def main():
    owner = json.loads(AUTH.read_text())['token']
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    runtime = json.loads((PRIVATE / 'native.json').read_text())['runtime_id']
    def api(path, body=None):
        return request(path, body, owner, workspace)
    existing = api('/api/agents/')
    mapping = {}
    for name, instructions in (('portable_tdd_implementer', IMPLEMENTER),
                               ('portable_tdd_reviewer', REVIEWER),
                               ('portable_tdd_implementer_v2', IMPLEMENTER_V2),
                               ('portable_tdd_reviewer_v2', REVIEWER_V2)):
        agent = next((item for item in existing if item['name'] == name), None)
        if agent is None:
            agent = api('/api/agents/', {'name': name, 'runtime_id': runtime,
                         'model': MODEL, 'description': 'Portable text-slug qualification only.',
                         'instructions': instructions, 'max_concurrent_tasks': 1,
                         'visibility': 'workspace'})
        if agent['runtime_id'] != runtime or agent['model'] != MODEL or agent['instructions'] != instructions:
            raise ValueError('portable agent identity drift')
        mapping[name] = agent['id']
    patch = ('import json,os,sys,tempfile; p="/broker-state/native.json"; '
             's=json.load(open(p)); i,r,i2,r2=sys.argv[1:5]; '
             's["agents"][i]="implementation"; s["agents"][r]="review"; '
             's["agents"][i2]="implementation"; s["agents"][r2]="review"; '
             's["review_requires_snapshot"]=sorted(set(s["review_requires_snapshot"])|{r,r2}); '
             'fd,t=tempfile.mkstemp(dir="/broker-state"); '
             'os.write(fd,json.dumps(s,sort_keys=True).encode()); os.fchmod(fd,0o600); '
             'os.close(fd); os.replace(t,p); print("portable identities registered")')
    subprocess.run(['docker', 'exec', PROJECT + '-execution-broker-1', 'python3', '-c',
                    patch, mapping['portable_tdd_implementer'],
                    mapping['portable_tdd_reviewer'],
                    mapping['portable_tdd_implementer_v2'],
                    mapping['portable_tdd_reviewer_v2']], check=True)
    for role, name in (('portable-implementer', 'portable_tdd_implementer'),
                       ('portable-reviewer', 'portable_tdd_reviewer'),
                       ('portable-implementer-v2', 'portable_tdd_implementer_v2'),
                       ('portable-reviewer-v2', 'portable_tdd_reviewer_v2')):
        data = {'agent_id': mapping[name], 'workspace_id': workspace, 'runtime_id': runtime}
        path = PRIVATE / (role + '.json')
        if path.exists() and json.loads(path.read_text()) != data:
            raise ValueError('portable identity registry drift')
        if not path.exists():
            private_json(path, data)
    print(json.dumps({'implementer': mapping['portable_tdd_implementer'],
                      'reviewer': mapping['portable_tdd_reviewer'],
                      'implementer_v2': mapping['portable_tdd_implementer_v2'],
                      'reviewer_v2': mapping['portable_tdd_reviewer_v2'],
                      'enqueued': False}))


if __name__ == '__main__':
    main()
