"""Byte-bound complete read evidence over controller-owned ACP pages.

Pure verifier, not provenance or approval. Callers must load pages exclusively
from the bound controller stream, never assistant/native UI claims of reading.
"""
import hashlib
import json
import re
from artifact_read_evidence import coverage
from portable_contract import safe_path, MAX_FILE_BYTES


class ReadRejected(ValueError):
    def __init__(self,category,path,expected,observed=None):
        super().__init__('snapshot read evidence rejected')
        self.diagnostic=dict(category=category,path=path.removeprefix('/delivery/'),
            expected_sha256=expected,observed_sha256=observed or [])


def require(value):
    if not value:raise ValueError('complete snapshot-bound review reads required')


def inventory(files, manifest, paths):
    require(isinstance(files,dict) and 1<=len(files)<=256)
    for path,value in files.items():
        safe_path(path)
        require(not any(ord(c)<32 or ord(c)==127 for c in path)
            and isinstance(value,dict) and set(value)=={'sha256','bytes'}
            and re.fullmatch('[a-f0-9]{64}',str(value['sha256']))
            and type(value['bytes']) is int and 0<=value['bytes']<=MAX_FILE_BYTES)
    raw=json.dumps({'files':files},sort_keys=True,separators=(',',':')).encode()
    require(hashlib.sha256(raw).hexdigest()==manifest and isinstance(paths,list)
        and len(paths)==len(set(paths)) and set(paths)=={'/delivery/'+p for p in files})
    return files


def page(messages):
    require(isinstance(messages,list) and len(messages)==2)
    call,result=messages
    require(call.get('type')=='tool_use' and call.get('tool')=='read_file'
        and result.get('type')=='tool_result' and result.get('tool')=='read_file'
        and isinstance(call.get('call_id'),str) and 0<len(call['call_id'])<=240
        and result.get('call_id')==call['call_id'] and not result.get('output_truncated'))
    args=call.get('input') or {};path=args.get('path')
    require(isinstance(path,str) and path.startswith('/delivery/'))
    safe_path(path.removeprefix('/delivery/'))
    output=result.get('output');require(isinstance(output,str) and len(output.encode())<=131072)
    offset,limit=args.get('offset',1),args.get('limit',100)
    try:data=json.loads(output)
    except ValueError:
        pattern=(r'Read '+re.escape(path)+r'(?: \(from line (\d+)(?:, limit (\d+))?\))?'
            r' — (\d+) total lines\n\n(`{3,})[^\n]*\n(.*)\n\4')
        found=re.fullmatch(pattern,output,re.DOTALL);require(found is not None)
        start,count,total,_,body=found.groups()
        offset,limit=int(start or 1),int(count or 100)
        data=dict(total_lines=int(total),content=body)
    require(isinstance(data,dict) and not data.get('error') and data.get('success') is not False
        and not data.get('dedup') and data.get('content_returned') is not False
        and type(offset) is int and offset>=1 and type(limit) is int and 1<=limit<=100
        and isinstance(data.get('content'),str) and type(data.get('total_lines')) is int)
    empty=(offset==1 and data['total_lines']==0 and data['content'] in ('','1|')
        and not data.get('truncated') and not data.get('truncated_by'))
    normalized=[{**call,'input':dict(path=path,offset=offset,limit=limit)},
        {**result,'output':json.dumps(data)}]
    require(empty or bool(coverage(normalized)))
    return path,empty,normalized


def accept_page(messages):
    try:page(messages);return True
    except (ValueError,KeyError,TypeError,UnicodeError):return False


def observe(files,manifest,paths,messages,*,include_content=False,required_paths=None):
    inventory(files,manifest,paths)
    required=set(paths) if required_paths is None else set(required_paths)
    require(bool(required) and required<=set(paths) and
        (required_paths is None or isinstance(required_paths,list) and len(required)==len(required_paths)))
    require(isinstance(messages,list) and 0<len(messages)<=1024 and len(messages)%2==0)
    normalized=[];identifiers=set();empty_paths={};raw_hashes={}
    for index in range(0,len(messages),2):
        pair=messages[index:index+2];path,empty,parsed=page(pair)
        require(path in paths and parsed[0]['call_id'] not in identifiers)
        identifiers.add(parsed[0]['call_id'])
        raw_hashes.setdefault(path,[]).append(hashlib.sha256(pair[1]['output'].encode()).hexdigest())
        if empty:empty_paths[path]=dict(lines=0,total_lines=0,line_content={})
        else:normalized.extend(parsed)
    found=coverage(normalized,include_content=True)
    require(not set(found)&set(empty_paths))
    found.update(empty_paths)
    result={}
    for name,expected in files.items():
        path='/delivery/'+name;observed=found.get(path)
        if path not in required:continue
        if observed is None or observed['lines']!=observed['total_lines']:
            raise ReadRejected('file_read_incomplete',path,expected['sha256'])
        lines=observed['line_content']
        require(set(lines)==set(range(1,observed['total_lines']+1)))
        text=[lines[n] for n in sorted(lines)]
        variants=set()
        for separator in ('\n','\r\n'):
            body=separator.join(text).encode()
            variants.update((body,body+separator.encode()))
        actual=[raw for raw in variants if len(raw)==expected['bytes']
            and hashlib.sha256(raw).hexdigest()==expected['sha256']]
        if len(actual)!=1:
            raise ReadRejected('file_read_byte_mismatch',path,expected['sha256'],
                sorted(hashlib.sha256(raw).hexdigest() for raw in variants))
        receipt=dict(sha256=expected['sha256'],bytes=expected['bytes'],total_lines=observed['total_lines'],
            output_sha256=hashlib.sha256(json.dumps(raw_hashes[path],separators=(',',':')).encode()).hexdigest())
        if include_content:receipt['line_content']=lines
        result[path]=receipt
    return result
