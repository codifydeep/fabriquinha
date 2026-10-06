"""Reconcile immutable executed QA, then request an independent assessment.

This operator bridge is restart-safe, but is NOT yet an autonomous workflow
activity. It never reruns QA, deletes Docker resources or approves a release.
"""
import argparse
import hashlib
import json
from pathlib import Path

SHA = 'e45c26256d8d0d3fa20b5d7bd021234421bcc2c1'
ASSESSOR = '8c1926ec-ae14-4f36-b5ea-388d14c2d726'
CLEANUP_REASON = 'post-deploy browser QA  cleanup: browser QA cleanup timeout; absence unproven'
HTTP = ['/health', '/ready', '/', '/static/app.js', '/static/style.css']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def reconcile(state_bytes, proof_bytes, certificate, deployment, resources):
    state, proof = json.loads(state_bytes), json.loads(proof_bytes)
    request = state.get('request', {})
    result, identity = proof.get('result', {}), proof.get('identity', {})
    flags = ('historical_tdd_red', 'release_homologated',
             'product_admission_authorized', 'independent_agent_qa_approval', 'tests_reexecuted')
    if (state.get('stage') != 'blocked' or state.get('reason') != CLEANUP_REASON
            or request.get('source_sha') != SHA or request.get('assessor') != ASSESSOR
            or not request.get('task_id') or deployment.get('source_sha') != SHA
            or proof.get('status') != 'failed' or proof.get('cleanup') != 'failed'
            or proof.get('automated') is not True or result.get('status') != 'passed'
            or result.get('source_sha') != SHA or identity.get('source_sha') != SHA
            or identity.get('application_image') != deployment.get('image')
            or result.get('contexts') != 2 or len(result.get('checks', [])) != 40
            or result.get('checks') != deployment.get('browser_checks')
            or certificate.get('schema') != 'u3-independent-qa-cleanup-recovery-v1'
            or certificate.get('failed_execution_receipt_sha256') != hashlib.sha256(state_bytes).hexdigest()
            or certificate.get('failed_browser_receipt_sha256') != hashlib.sha256(proof_bytes).hexdigest()
            or certificate.get('request_task') != request['task_id']
            or certificate.get('source_sha') != SHA or certificate.get('image') != deployment['image']
            or certificate.get('browser_checks') != result['checks'] or certificate.get('contexts') != 2
            or certificate.get('screenshot_sha256') != proof.get('screenshot_sha256')
            or certificate.get('http_checks') != HTTP or not resources
            or certificate.get('resources_absent') != resources
            or certificate.get('assertions_passed') is not True
            or certificate.get('cleanup_recovered') is not True
            or any(certificate.get(key) is not False for key in flags)):
        raise ValueError('exact unchanged QA receipts and non-authorizing cleanup certificate required')
    return dict(schema='u3-reconciled-executed-qa-v1', stage='validation_evidence_reconciled',
        request_task=request['task_id'], source_sha=SHA, image=deployment['image'],
        failed_execution_receipt_sha256=certificate['failed_execution_receipt_sha256'],
        failed_browser_receipt_sha256=certificate['failed_browser_receipt_sha256'],
        cleanup_certificate_sha256=digest(certificate), browser_checks=result['checks'],
        contexts=2, http_checks=HTTP, screenshot_sha256=proof['screenshot_sha256'],
        original_status='blocked', cleanup='recovered_with_separate_certificate',
        tests_reexecuted=False, independent_agent_qa_approval=False,
        historical_tdd_red=False, release_homologated=False, product_admission_authorized=False)


def persist(packet):
    """Fixed controller ledger, transactionally bound to the actual native request."""
    import broker as b
    import native
    receipt = packet['receipt']; key = receipt['request_task']
    with b.LOCK:
        settings = json.loads((b.STATE/'native.json').read_text())
        task = native.task_record(settings, key, ASSESSOR)
        with b.db() as con:
            row = con.execute('SELECT config,state FROM u3_qa_executions WHERE evidence_sha256=?',
                              (packet['request']['evidence_sha256'],)).fetchone()
            if not row:
                raise ValueError('durable QA request missing')
            config, state = json.loads(row['config']), json.loads(row['state'])
            namespace = {'__name__': 'fixed_request_verifier'}
            exec(compile(packet['verifier_source'], 'fixed_request_verifier', 'exec'), namespace)
            verified = namespace['request_receipt'](config, state, task,
                                                    json.loads(task['result']['output']))
            supplied = dict(packet['request']); supplied.pop('request_id', None)
            if verified != supplied or state.get('request') != packet['request']:
                raise ValueError('native execution and supplied request drift')
            con.execute('CREATE TABLE IF NOT EXISTS u3_qa_reconciliations(task_id TEXT PRIMARY KEY,receipt TEXT)')
            old = con.execute('SELECT receipt FROM u3_qa_reconciliations WHERE task_id=?', (key,)).fetchone()
            if old and json.loads(old['receipt']) != receipt:
                raise ValueError('immutable QA reconciliation drift')
            con.execute('INSERT OR IGNORE INTO u3_qa_reconciliations VALUES(?,?)',
                        (key, json.dumps(receipt, sort_keys=True)))
    print(json.dumps(receipt))


def main():
    import assess_u3_deployment as assessment
    import deploy_u3_coverage as deploy
    import execute_u3_qa as execution
    import recover_u3_qa_cleanup as recovery
    from release_eval import save_receipt
    parser = argparse.ArgumentParser(); parser.add_argument('--dispatch', action='store_true')
    args = parser.parse_args()
    root = deploy.RECEIPT.parent
    state_path = root/'U3-COVERAGE-EXECUTED-QA.json'
    certificate_path = root/'U3-COVERAGE-EXECUTED-QA-CLEANUP-RECOVERY.json'
    for path in (state_path, certificate_path, deploy.RECEIPT):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError('bounded regular controller receipt required')
    state_bytes = state_path.read_bytes(); state = json.loads(state_bytes)
    certificate = json.loads(certificate_path.read_text())
    expected = deploy.pub.ROOT/'.local-port2/browser-acceptance/U3-INDEPENDENT-QA'
    path = Path(certificate['browser_receipt'])
    if path.is_symlink() or path.resolve().parent != expected.resolve() or path.stat().st_size > 65536:
        raise ValueError('exact preserved independent QA receipt required')
    proof_bytes = path.read_bytes(); proof = json.loads(proof_bytes)
    deployment = json.loads(deploy.RECEIPT.read_text())
    resources = recovery.validate(state, proof, deployment, path)
    resources = [list(item) for item in resources]
    receipt = reconcile(state_bytes, proof_bytes, certificate, deployment, resources)
    # Reobserve only: never repeat tests or an uncertain delete.
    deploy.identity(deploy.inspect(deploy.NAME), deployment['image'], SHA)
    if deploy.ready(SHA) != HTTP or any(deploy.inspect(name, kind) is not None for kind, name in resources):
        raise ValueError('live deployment and exact cleanup absence required')
    packet = dict(receipt=receipt, request=state['request'],
                  verifier_source=Path(execution.__file__).read_text())
    source = Path(__file__).read_text()
    script = 'ns={"__name__":"operator_reconciliation"};exec(compile('+repr(source)+',"operator_reconciliation","exec"),ns);ns["persist"]('+repr(packet)+')'
    deploy.pub.run('docker', 'exec', '-i', '-e', 'PYTHONPATH=/',
                   deploy.pub.PROJECT+'-execution-broker-1', 'python', '-', data=script.encode())
    target = root/'U3-COVERAGE-EXECUTED-QA-RECONCILIATION.json'
    if target.exists() and json.loads(target.read_text()) != receipt:
        raise ValueError('immutable local QA reconciliation drift')
    if not target.exists(): save_receipt(target, receipt)
    dossier = dict(receipt, original_issue=state['identifier'],
        execution_scope='Live HTTP plus isolated exact-image browser fixture; not live-browser QA.',
        rollback_scope=deployment['rollback_scope'], operator_invoked=True,
        original_u3_historical_red_hold=True, u4_dependency_released=False)
    config = dict(assessor=assessment.ASSESSOR, author=assessment.AUTHOR,
        source_task=assessment.SOURCE, parent=assessment.PARENT, dossier=dossier,
        evidence_sha256=assessment.digest(dossier), typed_contract=True)
    packet = dict(config=config, action='dispatch' if args.dispatch else 'observe')
    script = 'ns={"__name__":"operator_executed_assessment"};exec(compile('+repr(Path(assessment.__file__).read_text())+',"operator_executed_assessment","exec"),ns);ns["controller"]('+repr(packet)+')'
    value = json.loads(deploy.pub.run('docker', 'exec', '-i', '-e', 'PYTHONPATH=/',
        deploy.pub.PROJECT+'-execution-broker-1', 'python', '-', data=script.encode()))
    save_receipt(root/'U3-COVERAGE-EXECUTED-QA-ASSESSMENT.json', dict(config=config, state=value, operator_invoked=True))
    print(json.dumps(value))


if __name__ == '__main__': main()
