"""Discoverable Hermes tool; the handler fence remains the authority."""
import json
import os
from tools.registry import registry
from surgical_test_edit import typed_schema


def available():
    try:
        config=json.loads(os.environ.get('DELIVERY_SURGICAL_TEST_JSON','{}'))
        return (os.environ.get('DELIVERY_EXECUTION_MODE')=='implementation'
                and config.get('protocol') in ('typed_v2','typed_driver_v3','typed_driver_lines_v4','typed_template_v5','typed_template_lines_v6'))
    except (ValueError,TypeError):return False


def schema_override():
    return typed_schema(json.loads(os.environ['DELIVERY_SURGICAL_TEST_JSON'])) if available() else {}


def handle(args,**kwargs):
    # A direct call to the module handler must also be fenced.
    from review_tool_policy import controlled
    result=controlled('surgical_test_edit',args)
    return result if result is not None else json.dumps({'error':'surgical_operation_unavailable'})


registry.register(name='surgical_test_edit',toolset='file',
    schema=typed_schema({'path':'/workspace/test_unavailable.py','expected_sha256':'0'*64}),
    handler=handle,check_fn=available,dynamic_schema_overrides=schema_override)
