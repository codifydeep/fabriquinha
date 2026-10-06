"""Require valid write arguments; never infer a path or broaden file authority."""
import copy


def apply(body):
    tools = body.get('tools')
    if not isinstance(tools, list):
        return body
    found = False
    result = copy.deepcopy(body)
    for tool in result['tools']:
        function = tool.get('function', {}) if isinstance(tool, dict) else {}
        if function.get('name') != 'write_file':
            continue
        parameters = function.get('parameters', {})
        properties = parameters.get('properties', {})
        if (parameters.get('type') != 'object' or set(properties) != {'path', 'content'}
                or any(properties[key].get('type') != 'string' for key in ('path', 'content'))):
            raise ValueError('unrecognized write_file signature')
        function['strict'] = True
        parameters['required'] = ['path', 'content']
        parameters['additionalProperties'] = False
        properties['path']['minLength'] = 1
        found = True
    if found:
        provider = result.setdefault('provider', {})
        provider['require_parameters'] = True
        return result
    return body
