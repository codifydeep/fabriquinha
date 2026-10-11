"""One explicitly authorized model call with qualified complete context.

Never executes requested tools, retries a request or modifies native workflows.
Requires a fresh controller export on stdin; raw replies stay private.
"""
import base64
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calibration_diagnostic_probe import build,attach_dependencies,summarize_reply,claim_prepared_submission
from calibration_diagnostic_runner import command,save,TRANSPORT,PROXY


def main():
    prior=sys.argv[1]
    if str(uuid.UUID(prior))!=prior:raise ValueError('exact preparation identity required')
    source=json.load(sys.stdin)
    base=Path(__file__).resolve().parents[1]/'.local-port2'/'diagnostic-probes'
    preparation=base/prior
    receipt=json.loads((preparation/'prepared-context-receipt.json').read_text())
    body=json.loads((preparation/'prepared-request.json').read_text())
    dependencies=json.loads((preparation/'complete-dependencies.json').read_text())
    current,parent=build(source['note'],source['reads'],'anthropic/claude-haiku-5.5',
        receipt['experiment_id'],source['source_task'])
    if (receipt['source_sha256']!=parent['source_sha256']
            or receipt['source_task']!=parent['source_task']
            or receipt['parent_input_sha256']!=parent['input_sha256']
            or hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()!=receipt['input_sha256']
            or body!=attach_dependencies(current,dependencies)):
        raise ValueError('prepared request or current source drift')
    for dependency in dependencies:
        if (dependency['path'].startswith('/evidence/candidate/')
                and dependency['manifest_sha256']!=source['candidate_manifest_sha256']):
            raise ValueError('prepared candidate manifest drift')
    experiment=str(uuid.uuid4());root=base/experiment
    claim_prepared_submission(base,prior,experiment,receipt['input_sha256'])
    root.mkdir(mode=0o700)
    identity={**receipt,'experiment_id':experiment,'prepared_from':prior,'max_model_calls':1}
    save(root,'identity.json',identity);save(root,'request.json',body)
    wire=command(['docker','exec','-i','-w','/',PROXY,'python','-c',TRANSPORT],
        {'experiment':experiment,'body':body},160)
    save(root,'transport.json',wire)
    if wire['calls_after']-wire['calls_before']!=1:
        raise ValueError('unexpected call count; no automatic replay')
    result=dict(experiment_id=experiment,prepared_from=prior,http_status=wire['status'],
        call_number=wire['calls_after'],model_calls=1,local_read_pages=0,
        execution_authorized=False,delivery_approval=False,workflow_transition=False)
    if wire['status']==200:
        result.update(summarize_reply(body,base64.b64decode(wire['data'])))
    save(root,'result.json',result)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps({'diagnostic_failed':True,'automatic_replay':False,
            'workflow_transition':False}))
        sys.exit(1)
