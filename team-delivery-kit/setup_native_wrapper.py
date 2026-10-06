"""Enroll one isolated native-dispatch probe; never enqueue automatically."""
import json
import subprocess
import time
from bootstrap_multica import AUTH, PRIVATE, request, private_json
from evalctl import ROOT, ENV_FILE, PROJECT, process_env
from register_team import MODEL


IMPLEMENTER_INSTRUCTIONS = (
    'Disposable TDD evaluation only. Work under /workspace on the provided '
    'calculator fixture. Follow the assigned issue: add a failing test, run it '
    'and observe Red, implement the smallest change, rerun Green and the full '
    'suite. Preserve every existing test unchanged. Report exact commands and '
    'results. Do not access any product repository, external network or secrets.'
)

REVIEWER_INSTRUCTIONS = (
    'Independent review of the frozen disposable TDD delivery mounted at '
    '/delivery. Read the code, tests and manifest; run the complete unittest '
    'suite. Do not edit any file or use a terminal to write. Check that the '
    'pre-existing tests remain intact and the issue behavior is tested. '
    'Report concrete findings and either APPROVE or REQUEST_CHANGES. '
    'Do not claim historical Red evidence from the snapshot alone.'
)


def main():
    owner = json.loads(AUTH.read_text())['token']
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    def api(path, body=None):
        return request(path, body, owner, workspace)
    path = '/api/workspaces/' + workspace + '/runtime-profiles'
    profiles = api(path)['runtime_profiles']
    profile = next((p for p in profiles if p['command_name'] == 'hermes-isolated'), None)
    if profile is None:
        profile = api(path, {'display_name': 'Hermes broker — offline qualification',
                            'protocol_family': 'hermes', 'command_name': 'hermes-isolated'})
    image = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}',
                                    'delivery-kit-eval-broker:20260928.18'], text=True).strip()
    subprocess.run(['docker', 'compose', '--project-name', PROJECT, '--env-file', str(ENV_FILE),
                    '-f', str(ROOT / 'compose.eval.yaml'), '-f', str(ROOT / 'compose.runtime.yaml'),
                    '-f', str(ROOT / 'compose.broker.yaml'), '--profile', 'runtime',
                    'up', '-d', '--no-deps', 'runtime', 'execution-broker'],
                   env={**process_env(), 'BROKER_WORKER_IMAGE': image}, check=True)
    key = subprocess.check_output(['docker', 'exec', PROJECT + '-execution-broker-1',
                                   'python', '-c', "from pathlib import Path; print(Path('/broker-state/token').read_text())"], text=True).strip()
    receiver = "import os,sys; p='/eval-state/broker-controller-token'; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600); os.write(fd,sys.stdin.buffer.read()); os.close(fd)"
    subprocess.run(['docker', 'exec', '-i', PROJECT + '-runtime-1', 'python', '-c', receiver],
                   input=key, text=True, check=True)
    runtime = None
    for _ in range(30):
        runtimes = api('/api/runtimes/')
        runtime = next((r for r in runtimes if r.get('profile_id') == profile['id'] and r['status'] == 'online'), None)
        if runtime:
            break
        time.sleep(1)
    if runtime is None:
        print(json.dumps({'profile_id': profile['id'], 'runtime_registered': False,
                          'runtime_fields': sorted(runtimes[0]) if runtimes else []}))
        raise RuntimeError('isolated custom runtime not online')
    agent = next((a for a in api('/api/agents/') if a['name'] == 'eval_native_boundary'), None)
    if agent is None:
        agent = api('/api/agents/', {'name': 'eval_native_boundary', 'runtime_id': runtime['id'],
                                    'description': 'Offline native identity/session qualification only.',
                                    'instructions': 'No model calls or product work. Prompts intentionally blocked.',
                                    'max_concurrent_tasks': 1, 'visibility': 'workspace'})
    if agent['runtime_id'] != runtime['id']:
        raise ValueError('probe agent runtime drift')
    implementer = next((a for a in api('/api/agents/') if a['name'] == 'eval_tdd_implementer'), None)
    if implementer is None:
        implementer = api('/api/agents/', {
            'name': 'eval_tdd_implementer', 'runtime_id': runtime['id'],
            'model': MODEL, 'description': 'Disposable Python TDD fixture only.',
            'instructions': IMPLEMENTER_INSTRUCTIONS,
            'max_concurrent_tasks': 1, 'visibility': 'workspace'})
    if implementer['runtime_id'] != runtime['id'] or implementer['model'] != MODEL or implementer['instructions'] != IMPLEMENTER_INSTRUCTIONS:
        raise ValueError('implementer identity/model/instructions drift')
    reviewer = next((a for a in api('/api/agents/') if a['name'] == 'eval_tdd_reviewer'), None)
    if reviewer is None:
        reviewer = api('/api/agents/', {
            'name': 'eval_tdd_reviewer', 'runtime_id': runtime['id'],
            'model': MODEL, 'description': 'Frozen disposable delivery review only.',
            'instructions': REVIEWER_INSTRUCTIONS,
            'max_concurrent_tasks': 1, 'visibility': 'workspace'})
    if reviewer['runtime_id'] != runtime['id'] or reviewer['model'] != MODEL or reviewer['instructions'] != REVIEWER_INSTRUCTIONS:
        raise ValueError('reviewer identity/model/instructions drift')
    settings = {'token': owner, 'workspace_id': workspace, 'runtime_id': runtime['id'],
                'agents': {agent['id']: 'review', implementer['id']: 'implementation',
                           reviewer['id']: 'review'},
                'review_requires_snapshot': [reviewer['id']]}
    seed = "import os,sys; fd=os.open('/broker-state/native.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600); os.write(fd,sys.stdin.buffer.read()); os.close(fd)"
    subprocess.run(['docker', 'exec', '-i', PROJECT + '-execution-broker-1', 'python', '-c', seed],
                   input=json.dumps(settings), text=True, check=True)
    registry = {'agent_id': agent['id'], 'runtime_id': runtime['id'], 'profile_id': profile['id'], 'workspace_id': workspace}
    target = PRIVATE / 'native.json'
    if not target.exists():
        private_json(target, registry)
    elif json.loads(target.read_text()) != registry:
        raise ValueError('native registry drift')
    impl_target = PRIVATE / 'implementer.json'
    impl_registry = {'agent_id': implementer['id'], 'workspace_id': workspace, 'runtime_id': runtime['id']}
    if not impl_target.exists():
        private_json(impl_target, impl_registry)
    elif json.loads(impl_target.read_text()) != impl_registry:
        raise ValueError('implementer registry drift')
    reviewer_target = PRIVATE / 'reviewer.json'
    reviewer_registry = {'agent_id': reviewer['id'], 'workspace_id': workspace,
                         'runtime_id': runtime['id']}
    if not reviewer_target.exists():
        private_json(reviewer_target, reviewer_registry)
    elif json.loads(reviewer_target.read_text()) != reviewer_registry:
        raise ValueError('reviewer registry drift')
    print(json.dumps({**registry, 'implementer_agent_id': implementer['id'],
                      'reviewer_agent_id': reviewer['id'],
                      'enqueued': False}))


if __name__ == '__main__':
    main()
