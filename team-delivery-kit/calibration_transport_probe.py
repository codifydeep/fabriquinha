"""Fixed synthetic transport experiment. Never imports product code or calls a model."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import calibration_response_contract as contract
import structured_rejection_receipts as receipts
from structured_response_contract import validate,StructuredResponseRejected

SOURCES=('calibration_response_contract','calibration_rejection_diagnostics','structured_rejection_receipts','structured_response_contract')


def source_hashes():
    return {n:hashlib.sha256(Path(importlib.util.find_spec(n).origin).read_bytes()).hexdigest() for n in SOURCES}


def run(*,readonly=False):
    path='/evidence/candidate/tests/test_fixture.py';execution='11111111-1111-4111-8111-111111111111'
    context=contract.context('bundle',[path],'a'*64,engine='unittest_path_fixtures_v2')
    body=dict(messages=[dict(role='user',content=contract.capsule(context)),
        dict(role='assistant',tool_calls=[dict(id='read',function=dict(name='read_file',arguments=json.dumps(
            dict(path=path,offset=1,limit=100))))]),
        dict(role='tool',tool_call_id='read',content=json.dumps(dict(content='1|fixture',total_lines=1)))],
        tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
    body=contract.apply(body)
    artifact=dict(action='calibration_objection',reason='Synthetic fixture only',execution_authorized=False,delivery_approval=False)
    def stream(trailer,duplicate=False):
        frames=[dict(choices=[dict(index=0,delta=dict(content=json.dumps(artifact)),finish_reason='stop')]),
            dict(choices=[dict(index=0,delta=trailer,finish_reason='stop')])]
        if duplicate:frames.append(frames[-1])
        return (''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
    validate(body,stream(dict(role='assistant',content='')),'text/event-stream')
    diagnostics=[]
    for raw in (stream(dict(content='PRIVATE_SYNTHETIC_VALUE')),stream({},True)):
        try:validate(body,raw,'text/event-stream')
        except StructuredResponseRejected as error:diagnostics.append(error.diagnostic)
        else:raise ValueError('invalid terminal accepted')
    assert all(d['version']=='calibration-constraint-v2' and d['failure_code']=='stream_after_finish' for d in diagnostics)
    assert 'PRIVATE_SYNTHETIC_VALUE' not in json.dumps(diagnostics)
    event=dict(event='model_proxy_request',status=502,category='structured_decision_response_invalid',
        execution_id=execution,call_number=2,structured_rejection_category='calibration_response_invalid',
        structured_rejection_diagnostic=diagnostics[0])
    legacy={**event,'call_number':1,'structured_rejection_diagnostic':dict(
        version='calibration-constraint-v1',category='invalid_transport_or_tool',constraints=[],fields=[],missing_fields=[],upstream_sha256='a'*64)}
    if readonly:result=[receipts.from_event(legacy),receipts.from_event(event)]
    else:
        with tempfile.TemporaryDirectory() as root:
            counter=str(Path(root)/'calls.json');Path(counter).write_text('{"calls":0}')
            receipts.record(counter,legacy);receipts.record(counter,event);receipts.record(counter,event)
            result=receipts.read(counter,execution)
    assert len(result)==2 and result[0]==receipts.from_event(legacy) and result[1]['diagnostic']==diagnostics[0]
    assert all(r[k] is False for r in result for k in ('worker_tool_executed','execution_authorized','delivery_approval'))
    return dict(operation='fixed_calibration_transport_probe_v1',passed=True,sources=source_hashes(),
        checks=dict(empty_terminal_accepted=True,extra_terminal_rejected=True,duplicate_terminal_rejected=True,
            ledger_idempotent=not readonly,legacy_receipt_preserved=True),
        model_calls=0,product_tests_executed=False,historical_cause_proven=False,
        author_retry_authorized=False,execution_authorized=False,delivery_approval=False)


if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
