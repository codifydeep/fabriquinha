"""Bounded tool responses; private full drafts and snapshots remain unchanged."""
import hashlib

def compact(files):
    visible={};budget=6000
    for name,value in files.items():
        if len(value.encode())<=budget:
            visible[name]=value;budget-=len(value.encode())
    return dict(files=visible,file_manifest={n:dict(bytes=len(v.encode()),sha256=hashlib.sha256(v.encode()).hexdigest(),inline=n in visible) for n,v in files.items()},
        read_instruction='Use product_read_file(path,offset,revision) for omitted content. Offset counts characters; use next_offset until null. Empty revision for author draft; exact revision for reviewer snapshot. No filesystem/terminal tool is needed.')

def page(files,path,offset):
    if path not in files:raise PermissionError('file outside assigned delivery')
    if type(offset) is not int or offset<0 or offset>len(files[path]):raise ValueError('invalid character offset')
    value=files[path];end=min(len(value),offset+2000)
    return dict(path=path,offset=offset,next_offset=end if end<len(value) else None,content=value[offset:end],sha256=hashlib.sha256(value.encode()).hexdigest())
