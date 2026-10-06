"""Recover cleanup only; preserve the failed browser/QA receipts, never rerun QA."""
import hashlib
import json
from pathlib import Path
import deploy_u3_coverage as deploy
import execute_u3_qa as qa
from release_eval import save_receipt


def validate(state,proof,deployment,path):
    if (state.get('stage')!='blocked' or
            state.get('reason')!='post-deploy browser QA  cleanup: browser QA cleanup timeout; absence unproven'
            or state.get('request',{}).get('source_sha')!=qa.SHA
            or proof.get('result',{}).get('contexts')!=2
            or proof.get('result',{}).get('checks')!=deployment.get('browser_checks')
            or len(proof.get('result',{}).get('checks',[]))!=40):
        raise ValueError('exact cleanup-only independent QA incident required')
    return deploy.cleanup_evidence(proof,deployment,path)


def main():
    pub=deploy.integration.publication
    state_path=deploy.RECEIPT.with_name('U3-COVERAGE-EXECUTED-QA.json')
    state=json.loads(state_path.read_text());deployment=json.loads(deploy.RECEIPT.read_text())
    folder=pub.ROOT/'.local-port2/browser-acceptance/U3-INDEPENDENT-QA'
    paths=list(folder.glob('*.json'))
    if len(paths)!=1 or paths[0].is_symlink():raise ValueError('unique preserved browser receipt required')
    path=paths[0];proof=json.loads(path.read_text());resources=validate(state,proof,deployment,path)
    deploy.identity(deploy.inspect(deploy.NAME),deployment['image'],qa.SHA)
    http=deploy.ready(qa.SHA)
    for kind,name in reversed(resources):deploy.remove_owned(kind,name,proof['owner'])
    if any(deploy.inspect(name,kind) is not None for kind,name in resources):
        raise ValueError('all exact owned resources must be absent')
    certificate=dict(schema='u3-independent-qa-cleanup-recovery-v1',
        failed_browser_receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        failed_execution_receipt_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
        request_task=state['request']['task_id'],source_sha=qa.SHA,image=deployment['image'],
        browser_receipt=str(path),browser_checks=proof['result']['checks'],contexts=2,
        http_checks=http,screenshot_sha256=proof['screenshot_sha256'],resources_absent=resources,
        assertions_passed=True,cleanup_recovered=True,tests_reexecuted=False,
        independent_agent_qa_approval=False,release_homologated=False,historical_tdd_red=False,
        product_admission_authorized=False,operator_invoked=True,model_calls=0)
    target=state_path.with_name('U3-COVERAGE-EXECUTED-QA-CLEANUP-RECOVERY.json')
    if target.exists():
        if json.loads(target.read_text())!=certificate:raise ValueError('immutable cleanup certificate drift')
    else:save_receipt(target,certificate)
    print(json.dumps(certificate))


if __name__=='__main__':main()
