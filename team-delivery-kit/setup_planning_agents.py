"""Enroll read-only pilot planners/reviewer without dispatching or granting tools."""
import json
import subprocess
import urllib.request

from bootstrap_multica import API, AUTH, PRIVATE, private_json, request
from evalctl import PROJECT
from model_policy import MODEL
from release_eval import save_receipt


LEGACY_CTO_INSTRUCTIONS = (
    'Choose an entirely local, free architecture for the supplied brief and '
    'Product output. Answer only with one JSON object: {"role":"cto",'
    '"stack":"...","components":["..."],"security":["..."],'
    '"technical_decisions":["..."],"risks":["..."]}. Choose from '
    'Node standard library or Python standard library unless a dependency '
    'is justified and locally available. Resolve technical questions yourself. '
    'Do not ask the CEO for architecture decisions or claim execution.')
CTO_INSTRUCTIONS = (LEGACY_CTO_INSTRUCTIONS +
    ' Exception: for an issue whose title begins QA-CTO-, follow that issue’s '
    'exact JSON diagnosis schema instead of the architecture JSON schema. '
    'Analyze only the failed QA evidence and operator-owned code/test scope. '
    'Do not alter files, weaken QA, expand scope or ask the CEO to decide a '
    'technical matter. A recommendation is not an executed fix.')

MEMORY_REVIEW_EXCEPTION = (
    ' Exception: when the issue description begins DELIVERY_PLANNING_SCHEMA_V1:memory_review, '
    'independently curate the exact historical nomination, not an implementation plan. '
    'Return only role=techlead, decision=approve or reject, entry_sha256 and reason. '
    'Follow the issue schema. This decision grants no tools, merge or release approval.')

ROLES = {
    'product': (
        'Clarify user behavior and acceptance for the supplied CEO brief. '
        'Answer only with one JSON object: {"role":"product","stories":[{"title":"...",'
        '"acceptance":["..."]}],"business_questions":[]}. Use at most five stories. '
        'Ask a business question only when the brief cannot determine user behavior. '
        'Do not choose architecture or claim to have edited the board.'),
    'cto': CTO_INSTRUCTIONS,
    'techlead': (
        'Plan the implementation from the CEO brief, Product stories and CTO '
        'architecture. Answer only with one JSON object: {"role":"techlead",'
        '"cards":[{"id":"C1","title":"...","owner":"backend_data",'
        '"depends_on":[],"acceptance":["..."],"files":["..."],'
        '"test_command":["node","--test"]}],"integration_order":["C1"]}. '
        'At most five cards; allowed owners are backend_data, frontend, devops, '
        'quality_security. Put TDD and regression in acceptance. Make dependencies '
        'explicit. Do not claim cards were created or tests executed.' + MEMORY_REVIEW_EXCEPTION),
    'quality_security': (
        'Independently review one controller-frozen pull-request diff and the '
        'controller-supplied CI/test receipts. Do not edit files, approve GitHub '
        'directly, or claim to have run tests yourself. Return only one JSON '
        'object: {"role":"quality_security","decision":"APPROVE" or '
        '"REQUEST_CHANGES","findings":["..."],"rationale":"..."}. '
        'Request changes if pre-existing tests are weakened, the scope is '
        'broader than stated, or evidence is insufficient.'),
}


def main():
    owner = json.loads(AUTH.read_text())['token']
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    runtime = json.loads((PRIVATE / 'native.json').read_text())['runtime_id']
    def api(path, body=None):
        return request(path, body, owner, workspace)
    existing = api('/api/agents/')
    agents = {}
    for role, instructions in ROLES.items():
        name = 'pilot_' + role
        matches = [agent for agent in existing if agent['name'] == name]
        if len(matches) > 1:
            raise ValueError('duplicate planning agent')
        expected = {'runtime_id': runtime, 'model': MODEL,
                    'instructions': instructions, 'max_concurrent_tasks': 1,
                    'visibility': 'workspace'}
        if matches:
            agent = matches[0]
            old_instructions = (LEGACY_CTO_INSTRUCTIONS if role=='cto' else
                                ROLES['techlead'].removesuffix(MEMORY_REVIEW_EXCEPTION) if role=='techlead' else None)
            if (old_instructions is not None and agent.get('instructions') == old_instructions
                    and all(agent.get(key) == value for key, value in expected.items()
                            if key != 'instructions')):
                path = '/api/agents/' + agent['id'] + '/'
                call = urllib.request.Request(
                    API + path, data=json.dumps({'instructions': instructions}).encode(),
                    headers={'Authorization': 'Bearer ' + owner,
                             'X-Workspace-ID': workspace,
                             'Content-Type': 'application/json'}, method='PUT')
                with urllib.request.urlopen(call, timeout=15) as response:
                    agent = json.load(response)
            if any(agent.get(key) != value for key, value in expected.items()):
                raise ValueError('planning agent drift: ' + role)
        else:
            agent = api('/api/agents/', {'name': name, **expected,
                        'description': 'Read-only brief planning qualification.'})
        agents[role] = agent['id']
    patch = ('import json,os,sys,tempfile; p="/broker-state/native.json"; '
             's=json.load(open(p)); ids=sys.argv[1:]; '
             '[(s["agents"].__setitem__(i,"planning")) for i in ids]; '
             'fd,t=tempfile.mkstemp(dir="/broker-state"); '
             'os.write(fd,json.dumps(s,sort_keys=True).encode()); os.fchmod(fd,0o600); '
             'os.close(fd); os.replace(t,p); print("planning identities enrolled")')
    subprocess.run(['docker', 'exec', PROJECT + '-execution-broker-1', 'python3',
                    '-c', patch, *agents.values()], check=True)
    target = PRIVATE / 'planning-agents.json'
    registry = {'workspace_id': workspace, 'runtime_id': runtime, 'agents': agents}
    if target.exists():
        previous = json.loads(target.read_text())
        if (previous.get('workspace_id') != workspace or previous.get('runtime_id') != runtime
                or any(agents.get(role) != agent_id for role, agent_id in
                       previous.get('agents', {}).items())):
            raise ValueError('planning registry drift')
        if previous != registry:
            save_receipt(target, registry)
    else:
        private_json(target, registry)
    print(json.dumps({'roles': sorted(agents), 'enqueued': False}))


if __name__ == '__main__':
    main()
