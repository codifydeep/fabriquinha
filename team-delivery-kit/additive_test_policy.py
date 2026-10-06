"""One new unittest file only; no edits to approved source or existing tests."""
import ast,fcntl,hashlib,json,os
from pathlib import Path

METHODS={'C01':'test_c01_query_clearing_control','C02':'test_c02_stale_status_control'}

def validate(content,criterion):
    if criterion not in METHODS or not isinstance(content,str) or not 1<=len(content.encode())<=6144:
        raise ValueError('bounded new test required')
    tree=ast.parse(content);classes=[]
    for node in tree.body:
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            names=[n.name for n in node.names] if isinstance(node,ast.Import) else [node.module]
            if any(n not in ('unittest','json','subprocess','shutil','pathlib','tests.test_incremental_u3') for n in names):
                raise ValueError('only existing unittest harness imports allowed')
        elif isinstance(node,ast.ClassDef):classes.append(node)
        elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):pass
        else:raise ValueError('new file must contain imports and a TestCase only')
    if len(classes)!=1 or classes[0].decorator_list or len(classes[0].bases)!=1 or ast.unparse(classes[0].bases[0])!='unittest.TestCase':
        raise ValueError('one independent unittest.TestCase required')
    methods=[n for n in classes[0].body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
    if len(methods)!=1 or methods[0].name!=METHODS[criterion] or methods[0].decorator_list:
        raise ValueError('one exact criterion test required')
    if len(methods[0].args.args)!=1 or methods[0].args.args[0].arg!='self':raise ValueError('test signature required')
    for node in ast.walk(tree):
        if isinstance(node,ast.Attribute) and ('skip' in node.attr.lower() or node.attr in ('expectedFailure','setattr','exec','eval')):
            raise ValueError('test weakening forbidden')
        if isinstance(node,ast.Name) and node.id in ('exec','eval','__import__','setattr','globals','locals'):
            raise ValueError('dynamic test replacement forbidden')
    if not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.startswith('assert') for n in ast.walk(methods[0])):
        raise ValueError('observable assertion required')
    return content.encode()

def write(config,args,read_pages):
    if set(args)!={'path','content'} or args.get('path')!=config['path']:raise ValueError('only one new test file permitted')
    for path,item in config['sources'].items():
        raw=Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256'] or not set(range(1,len(raw.splitlines())+1))<=read_pages.get(path,set()):
            raise ValueError('fresh complete approved source reads required')
    raw=validate(args['content'],config['criterion']);p=Path(config['path'])
    p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX);os.write(fd,raw);os.fsync(fd)
    finally:os.close(fd)
    if p.read_bytes()!=raw:raise ValueError('new artifact write incomplete')
    return {'success':True,'verified':True,'path':str(p),'bytes_written':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
        'created':True,'existing_files_unchanged':True,'delivery_approval':False}
