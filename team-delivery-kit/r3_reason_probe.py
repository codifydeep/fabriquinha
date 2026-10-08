"""Fixed model-free canary for R3 reason-only feedback, never a decision."""
import copy
import hashlib
import json
from pathlib import Path
import decision_schema
import typed_decision_contract as typed
from structured_response_contract import StructuredResponseRejected


def wire(value):
    return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':None,
        'tool_calls':[{'id':'probe','type':'function','function':{'name':typed.R3_NAME,
        'arguments':json.dumps(value)}}]}}]}).encode()


def run(notes):
    if len(notes)!=2:raise ValueError('two real independent failed notes required')
    for note in notes:
        body=typed.apply(decision_schema.apply({'messages':[{'role':'user','content':note}]}))
        schema=body['tools'][0]['function']['parameters'];props=schema['properties']
        decision={key:(False if prop['type']=='boolean' else prop['items']['enum']
                       if prop['type']=='array' else prop['enum'][0] if 'enum' in prop else 'Inspect exact delivery.')
                  for key,prop in props.items()}
        bad=copy.deepcopy(decision);bad['reason']='x'*700
        try:typed.translate(body,wire(bad),'application/json')
        except StructuredResponseRejected as error:
            assert error.category=='typed_schema_maxLength'
            feedback=error.length_feedback
        else:raise AssertionError('overlong reason was accepted')
        assert typed.length_feedback_enabled(body)
        revised=copy.deepcopy(body);revised['messages'].extend(feedback)
        output,_,receipt=typed.translate(revised,wire(decision),'application/json')
        assert json.loads(json.loads(output)['choices'][0]['message']['content'])==decision
        assert receipt['execution_authorized'] is False and receipt['worker_tool_executed'] is False
        drift=copy.deepcopy(decision);drift['fact_ids']=list(reversed(decision['fact_ids']))
        try:typed.translate(revised,wire(drift),'application/json')
        except StructuredResponseRejected as error:assert error.category=='typed_r3_feedback_identity_drift'
        else:raise AssertionError('fact identity drift accepted')
    return dict(status='r3_reason_transport_qualified',cases=2,
        policy_sha256=hashlib.sha256(Path(typed.__file__).read_bytes()).hexdigest(),
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        worker_tool_executed=False,execution_authorized=False)
