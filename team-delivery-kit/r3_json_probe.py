"""Fixed no-model qualification of malformed R3 arguments feedback."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import decision_schema
import typed_decision_contract as typed
from structured_response_contract import StructuredResponseRejected


def run(note):
    body=typed.apply(decision_schema.apply({'messages':[{'role':'user','content':note}]}))
    raw=json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':None,
        'tool_calls':[{'id':'probe','type':'function','function':{'name':typed.R3_NAME,'arguments':'{broken'}}]}}]}).encode()
    try:typed.translate(body,raw,'application/json')
    except StructuredResponseRejected as error:
        assert error.category=='typed_arguments_invalid'
        shape=error.receipt['response_shape']
        assert shape['arguments_json_valid'] is False and shape['expected_tool'] is True
        assert typed.format_feedback_enabled(body)
        import deterministic_read_dispatch as dispatch
        original=dispatch.ledger
        con=sqlite3.connect(':memory:')
        @contextmanager
        def memory_ledger(_):
            with con:yield con
        dispatch.ledger=memory_ledger
        try:
            identifier='11111111-1111-4111-8111-111111111111'
            revised=typed.claim_format_feedback('',identifier,error,body,1)
            assert revised and revised['tools']==body['tools']
            assert '{broken' not in revised['messages'][-1]['content']
            assert typed.claim_format_feedback('',identifier,error,body,1) is None
        finally:
            dispatch.ledger=original;con.close()
    else:raise AssertionError('malformed arguments accepted')
    return dict(status='r3_json_transport_qualified',policy_sha256=hashlib.sha256(Path(typed.__file__).read_bytes()).hexdigest(),
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),execution_authorized=False,worker_tool_executed=False)
