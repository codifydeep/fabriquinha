"""Fixed offline typed-remediation canary; no provider or worker tool executes."""
import copy
import hashlib
import json
from pathlib import Path
import remediation_plan_contract as contract
import typed_decision_contract as typed
from structured_response_contract import StructuredResponseRejected


def run():
    sha='a'*64;ids=['A01','A02']
    plan=dict(action='propose_remediation_plan',evidence_sha256=sha,reason='Evidence-bound plan.',
        execution_authorized=False,release_homologated=False,steps=[dict(id='R'+str(i),
            depends_on=[] if i==1 else ['R'+str(i-1)],edit_scope=scope,objective='Verified step',criteria=ids)
            for i,scope in enumerate(('new_tests_only','product_only','controller_only'),1)])
    review=dict(decision='approve_plan',evidence_sha256=sha,plan_sha256=sha,reason='Preserved coverage and gates.',
                execution_authorized=False,release_homologated=False)
    for kind,value in [('plan',plan),('review',review)]:
        note='DELIVERY_TYPED_REMEDIATION_V1:'+kind+':'+sha+'\nDELIVERY_REMEDIATION_'+kind.upper()+'_V1:'+sha+'\n'+''.join('DELIVERY_REMEDIATION_CRITERION:'+c+'\n' for c in ids)
        body=typed.apply(dict(messages=[dict(role='user',content=note)],response_format=dict(type='json_schema',
            json_schema=dict(name='delivery_decision_v1',strict=True,schema=contract.schema(kind,sha,ids)))))
        def wire(v):return json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(content=None,tool_calls=[
            dict(type='function',function=dict(name=typed.REMEDIATION_NAME,arguments=json.dumps(v)))]) )])).encode()
        output,_,receipt=typed.translate(body,wire(value),'application/json')
        actual=json.loads(json.loads(output)['choices'][0]['message']['content'])
        assert actual==value and receipt['worker_tool_executed'] is False and receipt['delivery_approval'] is False
        for mutation in ('execution','digest'):
            bad=copy.deepcopy(value)
            if mutation=='execution':bad['execution_authorized']=True
            else:bad['evidence_sha256']='b'*64
            try:typed.translate(body,wire(bad),'application/json')
            except StructuredResponseRejected:pass
            else:raise ValueError('negative control accepted')
    return dict(operation='typed_remediation_transport_canary_v1',model_calls=0,worker_tool_executed=False,
                delivery_approval=False,model_values_preserved=True,negative_controls_passed=True,
                source_sha256={Path(m.__file__).name:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
                               for m in (contract,typed)})


if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
