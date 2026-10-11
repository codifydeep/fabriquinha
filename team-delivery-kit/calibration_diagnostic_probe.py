"""Isolated format experiments from preserved reads, never native task proof.

The caller must obtain controller-bound durable read pairs. This module neither
dispatches tasks nor grants delivery authority; the original workflow stays put.
"""
import copy
import hashlib
import json
import uuid
from artifact_read_evidence import observations
from calibration_response_contract import request


def build(note, durable, model, experiment_id, source_task):
    for identifier in (experiment_id, source_task):
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError('canonical diagnostic identity required')
    if experiment_id == source_task:
        raise ValueError('experiment must not impersonate native task')
    context = request({'messages': [{'role': 'user', 'content': note}]})
    if context is None or context['phase'] != 'bundle':
        raise ValueError('current data-phase contract required')
    if len(durable) > 256 or len(durable) % 2:
        raise ValueError('bounded complete read pairs required')
    seen = set()
    messages = [{'role': 'system', 'content':
        'ISOLATED FORMAT DIAGNOSTIC. Preserved reads below are inputs from an '
        'earlier task, not new native inspection. No tools will be executed by '
        'this experiment. Return the requested JSON or request another read. '
        'No execution authorization, approval or workflow transition.'},
        {'role': 'user', 'content': note}]
    for index in range(0, len(durable), 2):
        use, result = durable[index:index + 2]
        identifier = use.get('call_id')
        if (use.get('type') != 'tool_use' or use.get('tool') != 'read_file'
                or result.get('type') != 'tool_result' or result.get('tool') != 'read_file'
                or not identifier or result.get('call_id') != identifier or identifier in seen):
            raise ValueError('distinct preserved read pair required')
        seen.add(identifier)
        if not isinstance(result.get('output'), str) or not observations([use, result]):
            # Individual partial pages may be needed to reconstruct a full file.
            from artifact_read_evidence import coverage
            if not coverage([use, result]):
                raise ValueError('observed bounded read result required')
        messages.extend([
            {'role': 'assistant', 'tool_calls': [{'id': identifier, 'type': 'function',
                'function': {'name': 'read_file', 'arguments': json.dumps(use['input'])}}]},
            {'role': 'tool', 'tool_call_id': identifier, 'content': result['output']}])
    body = dict(model=model, messages=messages, stream=False, tools=[
        {'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object'}}}])
    if not set(context['required_paths']) <= set(observations(messages, wire=True)):
        raise ValueError('complete preserved mandatory reads required')
    receipt = dict(kind='isolated_calibration_format_probe_v1', experiment_id=experiment_id,
        source_task=source_task, source_sha256=context['source_sha256'],
        input_sha256=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
        native_read_evidence=False, execution_authorized=False, delivery_approval=False,
        workflow_transition=False, tool_execution_allowed=False)
    return copy.deepcopy(body), receipt
