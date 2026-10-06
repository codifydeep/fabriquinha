"""Isolated, budgeted live trigger test: two bad Tech Lead runs -> CTO.

No product PR or code change. The deliberately false QA MIME expectation is
proved against an exact-SHA disposable deployment. The faulty Tech Lead agent
is an explicit test double; this qualifies the controller handoff, not model
judgment.
"""
import argparse
import json
import os
import subprocess

from bootstrap_multica import AUTH, PRIVATE, request
from evalctl import BACKEND_PORT, PROJECT
from model_policy import MODEL
from portable_contract import validate as validate_contract
from portable_qa_incident import record as record_incident
from portable_qualification import verify_docker_deployment
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_cto_trial import parent_contract
from qa_postmerge_trial import digest, write_once
from release_eval import save_receipt
from start_eval import check_model_budget, cli, issue


LABEL = 'QATRIG-1'
ERROR = 'post-deploy content type mismatch: /static/style.css'
FOLDER = PRIVATE / 'qa-cto-trigger-trial'
BAD_TECHLEAD = (
    'Controlled QA handoff fault agent. For every assigned issue, return only '
    'the plain text NOT_JSON. Do not call tools or claim a diagnosis. Your '
    'invalid response must be rejected by the controller.')


def selected():
    project = current()
    if (PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081'
            or project['repository'] != 'codifydeep/descartavel2'):
        raise ValueError('QA trigger trial restricted to port2 descartavel2')
    return project, verified_main()


def contract_and_spec(project, sha):
    contract, spec = parent_contract(project, sha)
    cases = [dict(case) for case in contract['qa_cases']]
    css = [case for case in cases if case['path'] == '/static/style.css']
    if len(css) != 1 or css[0]['content_type'] != 'text/css':
        raise ValueError('CSS QA baseline changed')
    css[0]['content_type'] = 'text/html'  # allowed schema value, deliberately false
    contract = {**contract, 'qa_cases': cases}
    validate_contract(contract)
    spec = {**spec, 'label': LABEL,
            'title': 'QATRIG-1 — synthetic Tech Lead-to-CTO trigger qualification',
            'description': ('Operator-owned synthetic QA expectation, deliberately '
                            'false. Its purpose is only to exercise two rejected '
                            'Tech Lead diagnosis runs and automatic CTO handoff. '
                            'Do not modify or merge product code.'),
            'qa_host_port': 19432}
    validate_spec(spec, contract)
    return contract, spec


def agents():
    owner = json.loads(AUTH.read_text())['token']
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    runtime = json.loads((PRIVATE / 'native.json').read_text())['runtime_id']
    existing = request('/api/agents/', token=owner, workspace=workspace)
    result = {}
    for name, instruction in (('eval_qa_bad_techlead', BAD_TECHLEAD),):
        matches = [agent for agent in existing if agent['name'] == name]
        if len(matches) > 1:
            raise ValueError('duplicate QA trigger agent')
        expected = {'runtime_id': runtime, 'model': MODEL,
                    'instructions': instruction, 'max_concurrent_tasks': 1,
                    'visibility': 'workspace'}
        agent = matches[0] if matches else request('/api/agents/', {
            'name': name, **expected,
            'description': 'Isolated, intentionally faulty QA handoff test double.'},
            owner, workspace)
        if any(agent.get(key) != value for key, value in expected.items()):
            raise ValueError('QA trigger agent configuration drift: ' + name)
        result[name] = agent['id']
    # The runtime wrapper needs the planning-mode identity. This atomic update
    # does not give either test agent implementation or review capabilities.
    code = ('import json,os,sys,tempfile; p="/broker-state/native.json"; '
            's=json.load(open(p)); ids=sys.argv[1:]; '
            '[(s["agents"].__setitem__(i,"planning")) for i in ids]; '
            'fd,t=tempfile.mkstemp(dir="/broker-state"); '
            'os.write(fd,json.dumps(s,sort_keys=True).encode()); '
            'os.fchmod(fd,0o600); os.close(fd); os.replace(t,p)')
    subprocess.run(['docker', 'exec', PROJECT + '-execution-broker-1',
                    'python3', '-c', code, *result.values()], check=True)
    return result


def seed(project, sha, contract, spec):
    check_model_budget()
    previous = json.loads((PRIVATE / 'release-receipts' / 'QA198A2E86-1.json').read_text())
    deployment = previous['deployment']
    if previous['merge_sha'] != sha or deployment['source_sha'] != sha:
        raise ValueError('QA trigger requires current exact-SHA deployment')
    try:
        verify_docker_deployment(deployment['container'], deployment['url'], sha, contract)
    except ValueError as error:
        if str(error) != ERROR:
            raise
    else:
        raise ValueError('synthetic CSS QA expectation unexpectedly passed')
    identities = agents()
    contract_path = FOLDER / 'parent.contract.json'
    spec_path = FOLDER / 'parent.run.json'
    write_once(contract_path, contract)
    write_once(spec_path, spec)
    parent = issue(spec['title'], spec['description'])
    context = {'label': LABEL, 'issue_id': parent['id'], 'base_sha': sha,
               'contract_sha256': digest(contract), 'run_spec_sha256': digest(spec)}
    write_once(PRIVATE / ('portable-context-' + LABEL + '.json'), context)
    incident = record_incident(
        PRIVATE, cli, context=context, label=LABEL, phase='deployed',
        source_sha=sha, error=ValueError(ERROR),
        techlead_id=identities['eval_qa_bad_techlead'], budget_ready=True,
        parent_contract=contract)
    receipt = {'label': LABEL, 'source_sha': sha,
               'parent_issue_id': parent['id'],
               'incident_issue_id': incident['child_issue_id'],
               'incident_key': incident['key'],
               'techlead_id': identities['eval_qa_bad_techlead']}
    write_once(FOLDER / 'seed.json', receipt)
    return receipt


def run(project, sha, contract, spec):
    from portable_delivery import drive_qa_repair
    from portable_qa_incident import find
    seed_receipt = json.loads((FOLDER / 'seed.json').read_text())
    if seed_receipt['source_sha'] != sha:
        raise ValueError('QA trigger source SHA moved')
    os.environ['DELIVERY_KIT_RUN_SPEC'] = str(FOLDER / 'parent.run.json')
    os.environ['DELIVERY_KIT_DELIVERY_CONTRACT'] = str(FOLDER / 'parent.contract.json')
    import portable_delivery
    portable_delivery.configure_run(contract)
    receipt_path = portable_delivery.RECEIPT
    if not receipt_path.exists():
        save_receipt(receipt_path, {'label': LABEL, 'base_sha': sha,
                     'stage': 'synthetic_qa_blocked', 'contract_sha256': digest(contract)})
    incident = find(PRIVATE, seed_receipt['parent_issue_id'], LABEL)
    if not incident or incident['key'] != seed_receipt['incident_key']:
        raise ValueError('QA trigger incident drift')
    result = drive_qa_repair(incident, contract, stop_after_cto_dispatch=True)
    write_once(FOLDER / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('seed', 'run'))
    args = parser.parse_args()
    project, sha = selected()
    contract, spec = contract_and_spec(project, sha)
    result = seed(project, sha, contract, spec) if args.action == 'seed' else run(
        project, sha, contract, spec)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
