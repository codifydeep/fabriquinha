"""Synthetic image qualification only. No network/model/native delivery calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0,'/')
import calibration_response_contract as contract
import structured_rejection_receipts as receipts
from decision_schema import apply
from structured_response_contract import validate,StructuredResponseRejected

execution='11111111-1111-4111-8111-111111111111'
path='/evidence/candidate/tests/test_fixture.py'
context=contract.context('bundle',[path],'a'*64,engine='unittest_path_fixtures_v2')
body=dict(messages=[dict(role='user',content=contract.capsule(context)),
    dict(role='assistant',tool_calls=[dict(id='read',function=dict(name='read_file',arguments=json.dumps(
        dict(path=path,offset=1,limit=100))))]),
    dict(role='tool',tool_call_id='read',content=json.dumps(dict(content='1|fixture',total_lines=1)))],
    tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
body=apply(body)
artifact=dict(action='calibration_objection',reason='Synthetic fixture only',execution_authorized=False,delivery_approval=False)


def stream(trailer):
    frames=[dict(choices=[dict(index=0,delta=dict(content=json.dumps(artifact)),finish_reason='stop')]),
        dict(choices=[dict(index=0,delta=trailer,finish_reason='stop')])]
    return (''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()


validate(body,stream(dict(role='assistant',content='')),'text/event-stream')
try:validate(body,stream(dict(content='PRIVATE_SYNTHETIC_VALUE')),'text/event-stream')
except StructuredResponseRejected as error:diagnostic=error.diagnostic
else:raise AssertionError('new content after finish must be rejected')
assert diagnostic['version']=='calibration-constraint-v2' and diagnostic['failure_code']=='stream_after_finish'
assert 'PRIVATE_SYNTHETIC_VALUE' not in json.dumps(diagnostic)
event=dict(event='model_proxy_request',status=502,category='structured_decision_response_invalid',
    execution_id=execution,call_number=1,structured_rejection_category='calibration_response_invalid',
    structured_rejection_diagnostic=diagnostic)
readonly=sys.argv[1:]==['--read-only']
if sys.argv[1:] not in ([],['--read-only']):raise ValueError('fixed canary mode required')
if readonly:
    result=[receipts.from_event(event)]
else:
    with tempfile.TemporaryDirectory() as root:
        counter=str(Path(root)/'calls.json');Path(counter).write_text('{"calls":0}')
        receipts.record(counter,event);receipts.record(counter,event)
        result=receipts.read(counter,execution)
assert len(result)==1 and result[0]['diagnostic']==diagnostic
assert all(result[0][k] is False for k in ('worker_tool_executed','execution_authorized','delivery_approval'))
print(json.dumps(dict(operation='synthetic_calibration_transport_canary_v1',passed=True,model_calls=0,
    ledger_persistence_tested=not readonly,delivery_approval=False,sources={n:hashlib.sha256(Path(importlib.util.find_spec(n).origin).read_bytes()).hexdigest()
        for n in ('calibration_response_contract','calibration_rejection_diagnostics','structured_rejection_receipts')})))
