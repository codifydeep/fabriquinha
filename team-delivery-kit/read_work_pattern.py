"""Read-only work-pattern metadata. No source bytes or tool arguments emitted."""
import hashlib
import json
from artifact_read_evidence import coverage


def summarize(messages):
    reads=[];first_edit=None
    for index,message in enumerate(messages):
        if message.get('role')!='assistant':continue
        for call in message.get('tool_calls') or []:
            fn=call.get('function') or {}
            if fn.get('name') in ('patch','write_file') and first_edit is None:first_edit=index
            if fn.get('name')!='read_file':continue
            try:args=json.loads(fn.get('arguments','{}'))
            except (ValueError,TypeError):continue
            if not isinstance(args,dict) or not isinstance(args.get('path'),str):continue
            offset,limit=args.get('offset',1),args.get('limit')
            if type(offset) is not int or limit is not None and type(limit) is not int:continue
            reads.append((index,args['path'],offset,limit))
    prefix=messages[:first_edit] if first_edit is not None else messages
    evidence=coverage(prefix,wire=True)
    files=[]
    for path in sorted({r[1] for r in reads}):
        pages=[(r[2],r[3]) for r in reads if r[1]==path]
        receipt=evidence.get(path,{})
        files.append(dict(path_sha256=hashlib.sha256(path.encode()).hexdigest(),
            calls=len(pages),unique_pages=len(set(pages)),
            calls_before_first_edit=sum(r[0]<(first_edit if first_edit is not None else len(messages))
                for r in reads if r[1]==path),
            observed_total_lines=receipt.get('total_lines'),observed_lines=receipt.get('lines'),
            complete_before_first_edit=bool(receipt) and receipt.get('lines')==receipt.get('total_lines')))
    return dict(operation='read_work_pattern_v1',read_calls=len(reads),files=files,
        duplicate_pages=sum(f['calls']-f['unique_pages'] for f in files),
        model_calls=0,delivery_approval=False)
