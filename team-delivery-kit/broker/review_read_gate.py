"""Actual handler-result coverage before a registered review may run its suite."""
import json
import os
from pathlib import PurePosixPath
from artifact_read_evidence import coverage

READS=[]


def paths():
    raw=os.environ.get('DELIVERY_REVIEW_READ_PATHS_JSON')
    if not raw:return ()
    value=json.loads(raw)
    if (not isinstance(value,list) or not 0<len(value)<=32 or len(set(value))!=len(value)
            or any(not isinstance(p,str) or not p.startswith('/delivery/')
                or str(PurePosixPath(p))!=p or '..' in PurePosixPath(p).parts for p in value)):
        raise ValueError('invalid controller review read contract')
    return tuple(value)


def request(args):
    required=paths()
    if not required:return None
    if (type(args.get('offset')) is not int or args['offset']<1
            or type(args.get('limit')) is not int or not 1<=args['limit']<=100):
        return json.dumps(dict(error='bounded_review_page_required',offset=1,limit=100,
            instruction='Read consecutive pages with explicit offset and limit <=100; use returned total_lines.'))
    return None


def observe(args,result):
    if not paths() or args.get('path') not in paths():return
    if not isinstance(result,str) or len(result.encode())>131072:return
    identifier=str(len(READS)//2)
    pair=[dict(type='tool_use',tool='read_file',call_id=identifier,input=dict(args)),
          dict(type='tool_result',tool='read_file',call_id=identifier,output=result)]
    if not coverage(pair):return
    if len(READS)>=256:raise ValueError('review read observation limit')
    READS.extend(pair)


def pending():
    observed=coverage(READS)
    missing=[]
    for path in paths():
        value=observed.get(path,{})
        if not value or value.get('lines')!=value.get('total_lines'):
            missing.append(dict(path=path,next_offset=value.get('next_offset',1),limit=100))
    return missing
