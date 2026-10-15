"""Fixed synthetic transport qualification; no provider calls or product code."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import calibration_response_contract as contract
import diagnostic_control_transport as adapter
from structured_response_contract import validate,StructuredResponseRejected

SOURCES=('diagnostic_control_transport','diagnostic_control_transport_probe','model_proxy',
    'calibration_response_contract','structured_response_contract','artifact_read_evidence')
CHECKS={'canonical_unchanged','mandatory_reads_retained','real_extra_read_preserved','carrier_required',
    'schema_and_authority_preserved','bad_json_and_envelopes_refused','literal_arguments_preserved',
    'no_worker_tool_execution','source_bound_opt_in','proxy_projection_installed'}


def source_hashes():return {name:hashlib.sha256(Path(importlib.util.find_spec(name).origin).read_bytes()).hexdigest() for name in SOURCES}


def run():
    import model_proxy
    assert model_proxy.MODEL=='anthropic/claude-haiku-5.5'
    path='/evidence/candidate/tests/test_synthetic.py'
    raw=dict(model='anthropic/claude-haiku-5.5',messages=[dict(role='user',content=contract.capsule(
        contract.context('bundle',[path],'a'*64,engine='unittest_path_fixtures_v2'))+adapter.MARKER+':'+'a'*64+'\n')],
        tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
    incomplete=contract.apply(copy.deepcopy(raw));assert adapter.project(incomplete) is None
    raw['messages'] += [dict(role='assistant',tool_calls=[dict(id='read',type='function',function=dict(name='read_file',
        arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),dict(role='tool',tool_call_id='read',
        content=json.dumps(dict(content='1|synthetic',total_lines=1)))]
    body=contract.apply(raw);before=copy.deepcopy(body);wire=adapter.project(body)
    assert body==before and wire['tool_choice']=='required' and wire['parallel_tool_calls'] is False
    assert model_proxy.provider_request(body)==wire
    assert [t['function']['name'] for t in wire['tools']]==['read_file',adapter.NAME]
    assert 'anyOf' not in json.dumps(wire['tools'][-1])
    def response(arguments,name=adapter.NAME,finish='tool_calls'):
        return json.dumps(dict(choices=[dict(index=0,finish_reason=finish,message=dict(content=None,tool_calls=[
            dict(id='carrier',type='function',function=dict(name=name,arguments=arguments))]))])).encode()
    objection=dict(action='calibration_objection',reason='Synthetic seam only',execution_authorized=False,delivery_approval=False)
    bundle=dict(action='propose_calibration_bundle',engine='unittest_path_fixtures_v2',
        modules=[dict(path='tests/test_synthetic.py',fixtures=[dict(attribute='PAGE',product_path='app/page.html',
            positive_fixture='positive.html')],classes={'SyntheticTests':['test_one']})],
        negatives=[dict(id='N01',module='tests/test_synthetic.py',class_name='SyntheticTests',method='test_one',
            replacements=[dict(attribute='PAGE',fixture='negative.html')],criteria=['A01'])],
        previous_methods={'tests/test_synthetic.py':{'SyntheticTests':['test_one']}},
        controls={'positive.html':'<main>ok</main>','negative.html':'<main>defect</main>'},execution_authorized=False,delivery_approval=False)
    for value in (objection,bundle):
        arguments='  '+json.dumps(value)+'  ';out,media,receipt=adapter.translate(body,response(arguments),'application/json')
        validate(body,out,media);assert json.loads(out)['choices'][0]['message']['content']==arguments
        assert receipt['worker_tool_executed'] is False and receipt['delivery_approval'] is False
    for arguments in ('NOT_JSON',json.dumps({**objection,'delivery_approval':True}),json.dumps({**bundle,'modules':[]})):
        try:adapter.translate(body,response(arguments),'application/json')
        except StructuredResponseRejected:pass
        else:raise AssertionError('invalid data accepted')
    for data in (response(json.dumps(objection),finish='length'),response(json.dumps(objection),name='terminal')):
        try:adapter.translate(body,data,'application/json')
        except StructuredResponseRejected:pass
        else:raise AssertionError('invalid envelope accepted')
    extra=response(json.dumps(dict(path='/evidence/candidate/app/page.html',offset=1,limit=100)),name='read_file')
    out,media,receipt=adapter.translate(body,extra,'application/json');assert out==extra and receipt is None;validate(body,out,media)
    forged=copy.deepcopy(body);forged['messages'][0]['content']=forged['messages'][0]['content'].replace(adapter.MARKER+':'+'a'*64,adapter.MARKER+':'+'b'*64)
    try:adapter.project(forged)
    except ValueError:pass
    else:raise AssertionError('foreign marker accepted')
    return dict(operation='fixed_diagnostic_control_transport_v1',protocol='diagnostic_control_data_carrier_v1',passed=True,
        sources=source_hashes(),checks={name:True for name in sorted(CHECKS)},model_calls=0,product_tests_executed=False,
        historical_cause_proven=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False)


if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
