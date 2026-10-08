"""Structured proposal output only; never grants tool or delivery authority."""
import json
import re

MARKER = 'DELIVERY_PLANNING_SCHEMA_V1'


def apply(body):
    roles = set()
    for message in body['messages']:
        if message.get('role') != 'user':
            continue
        content = message.get('content', '')
        if isinstance(content, list):
            content = '\n'.join(p.get('text', '') for p in content if isinstance(p, dict))
        if isinstance(content, str):
            # native_task_prompt prefixes the first issue-description line.
            # Match that verified wrapper as well as standalone marker lines.
            roles.update(re.findall(r'^(?:Description: )?' + MARKER + r':(product|cto|techlead|contract_resolution)$', content, re.MULTILINE))
    if not roles:
        return None
    if len(roles) != 1:
        raise ValueError('conflicting planning role contracts')
    role = roles.pop()

    def string(limit=300):
        return {'type': 'string', 'minLength': 1, 'maxLength': limit}

    def array(item, minimum=0, maximum=8):
        return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': maximum}

    def obj(properties):
        return {'type': 'object', 'properties': properties,
                'required': list(properties), 'additionalProperties': False}

    properties = {'role': {'type': 'string', 'enum': ['cto' if role == 'contract_resolution' else role]}}
    if role == 'contract_resolution':
        properties.update(parameter={'type': 'string', 'enum': ['status']},
            absent={'type': 'string', 'enum': ['all']},
            empty={'type': 'string', 'enum': ['all', '400']},
            explicit_all={'type': 'string', 'enum': ['all', '400']},
            unknown={'type': 'string', 'enum': ['400']}, reason=string())
    elif role == 'product':
        properties.update(stories=array(obj({'title': string(400),
                          'acceptance': array(string(), 1)}), 1, 5),
                          business_questions=array(string(), 0, 3))
    elif role == 'cto':
        properties.update(stack=string(), components=array(string(), 1),
                          security=array(string(), 1), technical_decisions=array(string(), 1),
                          risks=array(string()))
    else:
        card = obj({'id': {'type': 'string', 'enum': ['C1', 'C2', 'C3', 'C4', 'C5']},
                    'title': string(180),
                    'owner': {'type': 'string', 'enum': ['backend_data', 'frontend', 'devops', 'quality_security']},
                    'depends_on': array({'type': 'string', 'enum': ['C1', 'C2', 'C3', 'C4', 'C5']}, 0, 4),
                    'acceptance': array(string(), 1), 'files': array(string(240), 1, 12),
                    'test_command': array(string(40), 2, 7)})
        properties.update(cards=array(card, 1, 5),
                          integration_order=array({'type': 'string', 'enum': ['C1', 'C2', 'C3', 'C4', 'C5']}, 1, 5))
    body['response_format'] = {'type': 'json_schema', 'json_schema': {
        'name': 'planning_' + role + '_v1', 'strict': True, 'schema': obj(properties)}}
    body['provider'] = {**(body.get('provider') or {}), 'require_parameters': True}
    # Planning has no tool authority. Keeping the worker's full registry in
    # the request despite tool_choice=none is unnecessary and ambiguous.
    body['tools'] = []
    body['tool_choice'] = 'none'
    body['stream'] = False
    body['messages'].append({'role': 'system', 'content':
        'PLANNING OUTPUT PHASE. Role=' + role + '. Return only the exact compact '
        'JSON proposal, under 6000 characters. No extra prose, tools, invented '
        'execution or role suffixes. Product defines user acceptance, not '
        'architecture; CTO decides technical choices; Tech Lead defines the '
        'dependency graph. A proposal is not an approval or an executed delivery.'})
    # Some providers enforce object shape but not length/cardinality constraints.
    # Show the unchanged contract to the model too; never trim its answer or
    # relax validation to make an invalid proposal pass.
    body['messages'].append({'role':'system','content':
        'Respect every minItems/maxItems and minLength/maxLength below. '
        'Use concise acceptance criteria and combine related criteria rather '
        'than exceeding the limits. Exact output schema: '+
        json.dumps(obj(properties),sort_keys=True,separators=(',',':'))})
    return body


def caller_response(body, data, media_type, requested_stream):
    """Restore native SSE only AFTER the proxy validates the exact proposal.

    Content is forwarded byte-for-byte inside JSON, never repaired, stripped
    of prose or turned into executed actions. Non-planning routes are untouched.
    """
    spec = (body.get('response_format') or {}).get('json_schema') or {}
    if (not requested_stream or media_type != 'application/json'
            or spec.get('name') not in ('planning_product_v1', 'planning_cto_v1',
                                      'planning_techlead_v1', 'planning_contract_resolution_v1')):
        return data, media_type
    record = json.loads(data)
    choices = record.get('choices') or []
    if len(choices) != 1 or choices[0].get('finish_reason') != 'stop':
        raise ValueError('complete validated planning response required')
    message = choices[0]['message']
    if (not isinstance(message.get('content'), str)
            or message.get('tool_calls') or message.get('function_call')):
        raise ValueError('text-only validated planning response required')
    common = {key: record[key] for key in ('id', 'created', 'model', 'system_fingerprint') if key in record}
    common['object'] = 'chat.completion.chunk'
    frames = [{**common, 'choices': [{'index': 0, 'delta': {
        'role': 'assistant', 'content': message['content']}, 'finish_reason': None}]},
        {**common, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}]
    if 'usage' in record:
        frames.append({**common, 'choices': [], 'usage': record['usage']})
    return (''.join('data: ' + json.dumps(frame) + '\n\n' for frame in frames)
            + 'data: [DONE]\n\n').encode(), 'text/event-stream'
