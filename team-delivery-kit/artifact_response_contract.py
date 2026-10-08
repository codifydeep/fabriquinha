"""Verify a forced artifact tool response before forwarding it to Hermes."""
import json
import ast
import re
import hashlib
from test_artifact_schema import additive_phase
from surgical_test_edit import marker_config,validate_envelope,validate_typed


class ArtifactResponseRejected(ValueError):
    def __init__(self, category, diagnostic=None):
        self.category = category
        self.diagnostic = diagnostic or {}
        super().__init__('artifact tool response invalid')


def transport_structure(content):
    return dict(schema='python-artifact-structure-v1',content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        utf8_bytes=len(content.encode()),physical_newlines=content.count('\n'),
        escaped_newlines=content.count('\\n'),comment_lines=sum(line.lstrip().startswith('#') for line in content.splitlines()))

def python_structure(content,tree):
    nodes=list(ast.walk(tree))
    methods=sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_') for n in nodes)
    string_only=(len(tree.body)==1 and isinstance(tree.body[0],ast.Expr)
        and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str))
    embedded=0
    if string_only:
        try:
            embedded=sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')
                         for n in ast.walk(ast.parse(tree.body[0].value.value)))
        except (SyntaxError,ValueError):pass
    return dict(transport_structure(content),classes=sum(isinstance(n,ast.ClassDef) for n in nodes),
        functions=sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) for n in nodes),
        test_methods=methods,top_level_string_only=string_only,embedded_test_methods=embedded)


def metrics(body):
    marked = False
    for message in body.get('messages', []):
        if message.get('role') != 'user':
            continue
        content = message.get('content', '')
        if isinstance(content, list):
            content = '\n'.join(p.get('text', '') for p in content if isinstance(p, dict))
        if isinstance(content, str) and re.search(r'^DELIVERY_TEST_ARTIFACT_V1:', content, re.M):
            marked = True
    choice = body.get('tool_choice')
    name = choice.get('function', {}).get('name') if isinstance(choice, dict) else None
    return {'artifact_contract_present': marked,
            'artifact_selected_tool': name if marked and name in ('read_file','write_file','surgical_test_edit','patch') else None}


def validate(body, data, media_type):
    additive=additive_phase(body)
    diagnostic={}
    selected = metrics(body)['artifact_selected_tool']
    # Structured inspection phases use the same exact read-argument boundary.
    # Do not apply this to unforced tools or decision JSON (tool_choice=none).
    if not selected:
        choice=body.get('tool_choice')
        decision_read=isinstance(choice,dict) and choice.get('function',{}).get('name')=='read_file'
        for message in body.get('messages',[]):
            content=message.get('content','')
            if isinstance(content,list):content='\n'.join(p.get('text','') for p in content if isinstance(p,dict))
            if (decision_read and message.get('role')=='user' and isinstance(content,str)
                    and re.search(r'^DELIVERY_STRUCTURED_DECISION_V1:',content,re.M)):
                selected='read_file';break
    if not selected:
        return
    streaming = media_type == 'text/event-stream'
    records = []
    done = not streaming
    decode_phase = 'response'
    try:
        if streaming:
            for line in data.decode().splitlines():
                if not line.startswith('data:'):
                    continue
                value = line[5:].strip()
                if value == '[DONE]':
                    done = True
                elif value:
                    records.append(json.loads(value))
        else:
            records = [json.loads(data)]
        calls = {}
        finish = None
        for record in records:
            if record.get('error'):
                raise ValueError('upstream stream error')
            for choice in record.get('choices') or []:
                if choice.get('index', 0) != 0:
                    raise ValueError('multiple choices')
                if choice.get('finish_reason') is not None:
                    finish = choice['finish_reason']
                delta = choice.get('delta') if streaming else choice.get('message')
                for order, call in enumerate((delta or {}).get('tool_calls') or []):
                    index = call.get('index', order)
                    value = calls.setdefault(index, {'name':'','arguments':''})
                    function = call.get('function') or {}
                    value['name'] += function.get('name') or ''
                    value['arguments'] += function.get('arguments') or ''
        if not done or finish != 'tool_calls' or len(calls) != 1:
            diagnostic=dict(schema='forced-tool-shape-v1',
                response_sha256=hashlib.sha256(data).hexdigest(),
                streaming=streaming,stream_complete=done,
                finish_reason=finish if finish in ('stop','length','tool_calls','content_filter') else 'other',
                tool_calls=len(calls),all_selected_tools=bool(calls) and
                all(value['name']==selected for value in calls.values()))
            raise ValueError('incomplete forced tool response')
        call = next(iter(calls.values()))
        if call['name'] != selected:
            raise ValueError('wrong selected tool')
        decode_phase = 'arguments'
        args = json.loads(call['arguments'])
        schema = next(t['function']['parameters'] for t in body['tools']
                      if t.get('function', {}).get('name') == selected)
        props = schema['properties']
        if selected=='surgical_test_edit':
            validate_typed(args,marker_config(body))
        if not isinstance(args,dict) or set(args) != set(schema['required']):
            raise ValueError('wrong forced arguments')
        for key, value in args.items():
            specification = props[key]
            if ('enum' in specification and value not in specification['enum']
                    or specification.get('type') == 'integer' and type(value) is not int
                    or specification.get('type') == 'string' and (not isinstance(value,str)
                        or len(value) < specification.get('minLength', 0)
                        or len(value) > specification.get('maxLength', 2**31))):
                if additive or selected in ('patch','read_file'):
                    diagnostic={'field':key if key in ('path','content','offset','limit','old_string','new_string') else 'other',
                        'constraint':('enum' if 'enum' in specification and value not in specification['enum']
                            else 'length' if isinstance(value,str) else 'type')}
                    if not additive:diagnostic['schema']='forced-argument-constraint-v1'
                    if isinstance(value,str):diagnostic.update(characters=len(value),utf8_bytes=len(value.encode()))
                raise ValueError('invalid forced argument')
        if additive and selected=='write_file' and len(args['content'].encode())>6144:
            diagnostic={'field':'content','constraint':'utf8_length','utf8_bytes':len(args['content'].encode())}
            raise ValueError('invalid forced content size')
        if selected == 'write_file' and not 0 < len(args['content'].encode()) <= 32768:
            raise ValueError('invalid forced content size')
        if selected == 'patch':
            if args['old_string'] == args['new_string']:
                diagnostic=dict(schema='forced-argument-constraint-v1',field='new_string',constraint='no_change')
                raise ValueError('invalid forced argument')
            for key in ('old_string','new_string'):
                if len(args[key].encode()) > 4096:
                    diagnostic=dict(schema='forced-argument-constraint-v1',field=key,constraint='utf8_length',
                        characters=len(args[key]),utf8_bytes=len(args[key].encode()))
                    raise ValueError('invalid forced argument')
        surgical=marker_config(body)
        if selected=='write_file' and surgical:
            if args['path']!=surgical['path']:raise ValueError('invalid surgical response')
            try:validate_envelope(json.loads(args['content']),surgical['expected_sha256'])
            except (ValueError,TypeError,KeyError):raise ValueError('invalid surgical response') from None
        elif selected == 'write_file' and args['path'].endswith('.py'):
            # This gate precedes the worker write. Schema-valid helper text must
            # not overwrite the last artifact; it is not an executable test.
            # AST shape is not proof of coverage, Red or review approval.
            try:
                tree=ast.parse(args['content'])
            except SyntaxError:
                diagnostic=transport_structure(args['content'])
                raise ValueError('artifact test syntax invalid') from None
            if not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
                       and n.name.startswith('test_') for n in ast.walk(tree)):
                diagnostic=python_structure(args['content'],tree)
                raise ValueError('artifact test methods missing')
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, StopIteration) as error:
        # Never expose upstream text or model-generated arguments in errors.
        allowed = {'upstream stream error', 'multiple choices', 'incomplete forced tool response',
                   'wrong selected tool', 'wrong forced arguments', 'invalid forced argument',
                   'invalid forced content size', 'artifact test syntax invalid',
                   'invalid surgical response',
                   'surgical argument shape mismatch','surgical path mismatch',
                   'surgical hash mismatch','surgical edits invalid',
                   'artifact test methods missing'}
        category = ('invalid_tool_argument_json' if isinstance(error,json.JSONDecodeError) and decode_phase=='arguments'
                    else 'invalid_response_encoding' if isinstance(error,json.JSONDecodeError)
                    else str(error).replace(' ', '_') if str(error) in allowed else 'invalid_response_encoding')
        raise ArtifactResponseRejected(category,diagnostic) from None
