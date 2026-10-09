"""Validate actual decision bytes; schema requests alone are not evidence."""
import json
import hashlib
from jsonschema import Draft202012Validator


class StructuredResponseRejected(ValueError):
    def __init__(self,category,diagnostic=None):
        self.category=category
        self.diagnostic=diagnostic
        super().__init__('structured decision response invalid')


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON key')
        result[key]=value
    return result


def validate(body,data,media_type):
    fmt=body.get('response_format',{})
    if fmt.get('type')!='json_schema':return
    choice=body.get('tool_choice')
    if isinstance(choice,dict):return  # forced inspection has its own tool gate
    schema=fmt.get('json_schema',{}).get('schema')
    try:
        if not isinstance(schema,dict):raise ValueError('schema missing')
        Draft202012Validator.check_schema(schema)
        if media_type.startswith('text/event-stream'):
            parts=[];finished=False;done=False;terminal_trailer=False
            for line in data.decode().splitlines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':
                    if done or not finished:raise ValueError('incomplete stream')
                    done=True;continue
                if done:raise ValueError('data after terminal')
                frame=json.loads(raw,object_pairs_hook=_unique)
                if frame.get('error'):raise ValueError('provider stream error')
                choices=frame.get('choices',[])
                if not choices:continue  # usage-only frame
                if len(choices)!=1 or choices[0].get('index',0)!=0:raise ValueError('multiple choices')
                entry=choices[0];delta=entry.get('delta',{})
                if delta.get('tool_calls') or delta.get('function_call'):raise ValueError('unexpected tool call')
                content=delta.get('content')
                if finished:
                    # OpenRouter can repeat stop in a final empty usage trailer.
                    # Permit exactly one empty terminal choice; never accept new
                    # text, role changes/tools, a different finish or another trailer.
                    if (terminal_trailer or entry.get('finish_reason')!='stop'
                            or set(delta)-{'content','role'} or content not in (None,'')
                            or ('role' in delta and delta['role']!='assistant')):
                        raise ValueError('data after decision terminal')
                    terminal_trailer=True
                    continue
                if content is not None:
                    if not isinstance(content,str):raise ValueError('invalid content')
                    parts.append(content)
                finish=entry.get('finish_reason')
                if finish is not None:
                    if finished or finish!='stop':raise ValueError('nonterminal decision')
                    finished=True
            if not done or not finished:raise ValueError('incomplete stream')
            text=''.join(parts)
        else:
            response=json.loads(data,object_pairs_hook=_unique)
            choices=response.get('choices',[])
            if response.get('error') or len(choices)!=1 or choices[0].get('finish_reason')!='stop':
                raise ValueError('nonterminal decision')
            message=choices[0]['message']
            if message.get('tool_calls') or message.get('function_call'):raise ValueError('unexpected tool call')
            text=message.get('content')
        if not isinstance(text,str) or not 1<=len(text)<=65536:raise ValueError('invalid content')
        decision=json.loads(text,object_pairs_hook=_unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if not isinstance(decision,dict):raise ValueError('decision object required')
        errors=list(Draft202012Validator(schema).iter_errors(decision))
        if errors:
            # Never expose instance paths, rejected values or exception messages.
            # Only fixed JSON Schema keywords and a digest leave the validator.
            allowed={'type','enum','const','required','additionalProperties','minLength',
                     'maxLength','minItems','maxItems','uniqueItems','pattern',
                     'minimum','maximum','anyOf','oneOf','allOf','not'}
            constraints=sorted({e.validator if e.validator in allowed else 'other'
                                for e in errors})
            raise StructuredResponseRejected('schema_violation',{
                'version':'structured-constraint-v1','constraints':constraints,
                'upstream_sha256':hashlib.sha256(data).hexdigest()})
    except StructuredResponseRejected:raise
    except Exception:
        # No upstream text, JSON values or validation exception in public output.
        raise StructuredResponseRejected('nonterminal_or_non_json_response') from None
