"""Validate the actual proxy image's V6 request and response contracts offline."""
import hashlib,json
from pathlib import Path
from model_proxy import validate_request,MODEL
from artifact_response_contract import validate,ArtifactResponseRejected
from surgical_test_edit import typed_schema

target='/workspace/test_template.py'
cfg=dict(path=target,expected_sha256='a'*64,protocol='typed_template_lines_v6')
body=dict(model=MODEL,messages=[dict(role='user',content='DELIVERY_TEST_ARTIFACT_V1:'+target+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_SURGICAL_TEST_V6:'+target+':'+cfg['expected_sha256']+'\n')],
 tools=[dict(type='function',function=typed_schema(cfg)),
        dict(type='function',function=dict(name='read_file',parameters={})),
        dict(type='function',function=dict(name='write_file',parameters=dict(type='object',properties=dict(path=dict(type='string'),content=dict(type='string')))))])
for i,path in enumerate(['/workspace/app.py',target]):
 body['messages'] += [dict(role='assistant',tool_calls=[dict(id=str(i),function=dict(name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),
                      dict(role='tool',tool_call_id=str(i),content=json.dumps(dict(content='1|source',total_lines=1)))]
selected=validate_request(body)
assert selected['tool_choice']['function']['name']=='surgical_test_edit'
assert 'CURRENT HARNESS-ONLY LINE CORRECTION' in selected['messages'][-1]['content']
args=dict(path=target,expected_sha256=cfg['expected_sha256'],edits=[dict(start_line=7,end_line=7,new=' const after_ok = {text: "terminal"};\n')])
def response(arguments):return json.dumps(dict(choices=[dict(message=dict(tool_calls=[dict(function=dict(name='surgical_test_edit',arguments=json.dumps(arguments)))]),finish_reason='tool_calls')])).encode()
validate(selected,response(args),'application/json')
for bad in ({**args,'template_name':'OTHER'},{**args,'edits':[dict(old='before',new='terminal')]},
            {**args,'expected_sha256':'b'*64},{**args,'path':'/workspace/app.py'}):
 try:validate(selected,response(bad),'application/json')
 except ArtifactResponseRejected:pass
 else:raise AssertionError('ungranted V6 payload accepted')
mixed={**body,'messages':[dict(role='user',content=body['messages'][0]['content']+'DELIVERY_SURGICAL_TEST_V5:'+target+':'+cfg['expected_sha256']+'\n')]+body['messages'][1:]}
try:validate_request(mixed)
except (ValueError,ArtifactResponseRejected):pass
else:raise AssertionError('mixed protocols accepted')
sources={name:hashlib.sha256(Path('/'+name).read_bytes()).hexdigest() for name in ('surgical_test_edit.py','test_artifact_schema.py')}
print(json.dumps(dict(schema='template-line-proxy-image-probe-v6',status='passed',source_sha256=sources,
 actual_proxy_request_validation=True,actual_response_validation=True,legacy_payload_denied=True,
 mixed_protocol_denied=True,path_and_hash_mismatch_denied=True,model_calls=0,delivery_approval=False)))
