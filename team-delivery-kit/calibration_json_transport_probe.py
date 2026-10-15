"""Fixed synthetic JSON-mode qualification; never model or product execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import calibration_response_contract as contract
import provider_tool_routing
from structured_response_contract import validate,StructuredResponseRejected

SOURCES=('calibration_response_contract','calibration_rejection_diagnostics','structured_rejection_receipts',
    'structured_response_contract','artifact_read_evidence','provider_tool_routing','calibration_json_transport_probe')
CHECKS={'json_mode_requested','canonical_request_unchanged','mandatory_reads_unchanged','extra_reads_unchanged',
    'invalid_json_rejected','forged_authority_rejected','valid_objection_accepted','valid_bundle_accepted','invalid_schema_rejected'}


def source_hashes():
    return {name:hashlib.sha256(Path(importlib.util.find_spec(name).origin).read_bytes()).hexdigest() for name in SOURCES}


def run():
    path='/evidence/candidate/tests/test_synthetic.py'
    initial=dict(model='anthropic/claude-haiku-5.5',messages=[dict(role='user',content=contract.capsule(
        contract.context('bundle',[path],'a'*64,engine='unittest_path_fixtures_v2')))],
        tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
    read=contract.apply(copy.deepcopy(initial));wire=provider_tool_routing.wire(read)
    assert wire['tool_choice']['function']['name']=='read_file' and 'response_format' not in wire
    initial['messages'] += [dict(role='assistant',tool_calls=[dict(id='r',type='function',function=dict(
        name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),
        dict(role='tool',tool_call_id='r',content=json.dumps(dict(content='1|synthetic',total_lines=1)))]
    body=contract.apply(initial);before=copy.deepcopy(body);wire=provider_tool_routing.wire(body)
    assert wire['response_format']=={'type':'json_object'} and wire['provider']['require_parameters'] is True
    assert body==before and {k:v for k,v in wire.items() if k!='response_format'}==before
    def reply(text):return json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content=text))])).encode()
    valid=dict(action='calibration_objection',reason='Synthetic unsupported seam',execution_authorized=False,delivery_approval=False)
    validate(body,reply(json.dumps(valid)),'application/json')
    bundle=dict(action='propose_calibration_bundle',engine='unittest_path_fixtures_v2',
        modules=[dict(path='tests/test_synthetic.py',fixtures=[dict(attribute='PAGE',product_path='app/page.html',
            positive_fixture='positive.html')],classes={'SyntheticTests':['test_one']})],
        negatives=[dict(id='N01',module='tests/test_synthetic.py',class_name='SyntheticTests',method='test_one',
            replacements=[dict(attribute='PAGE',fixture='negative.html')],criteria=['A01'])],
        previous_methods={'tests/test_synthetic.py':{'SyntheticTests':['test_one']}},
        controls={'positive.html':'<main>ok</main>','negative.html':'<main>defect</main>'},
        execution_authorized=False,delivery_approval=False)
    validate(body,reply(json.dumps(bundle)),'application/json')
    for text in ('Not JSON',json.dumps({**valid,'delivery_approval':True}),json.dumps({**bundle,'modules':[]})):
        try:validate(body,reply(text),'application/json')
        except StructuredResponseRejected:pass
        else:raise AssertionError('invalid proposal accepted')
    extra=json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(tool_calls=[dict(function=dict(
        name='read_file',arguments=json.dumps(dict(path='/evidence/candidate/app/fixture.txt',offset=1,limit=100))))]))])).encode()
    validate(body,extra,'application/json')
    return dict(operation='fixed_json_object_transport_probe_v1',passed=True,sources=source_hashes(),
        checks={name:True for name in sorted(CHECKS)},model_calls=0,product_tests_executed=False,
        historical_cause_proven=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False)


if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
