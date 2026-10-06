"""Fixed, hash-bound Python formatting. No model-generated transform or command."""
import ast
import hashlib
import json
import os
from pathlib import Path
from portable_contract import validate,safe_path


def normalize(base,workspace,archive,selection):
    base,workspace,archive=map(Path,(base,workspace,archive))
    if set(selection)!={'path','sha256'}:raise ValueError('exact normalization selection required')
    name=selection['path'];safe_path(name)
    contract=validate(json.loads((base/'contract.json').read_text()))
    manifest=json.loads((base/'manifest.json').read_text())
    baseline=set(manifest['files'])-{'contract.json'}
    if (name in baseline or not name.endswith('.py') or name not in contract['test_files']
            or name not in contract['editable_files']):raise ValueError('only declared NEW Python test may normalize')
    target=workspace/name
    if target.is_symlink() or any(p.is_symlink() for p in list(target.parents)[:len(Path(name).parts)-1]):
        raise ValueError('unsafe normalization path')
    for file in baseline:
        current=workspace/file
        if current.is_symlink() or not current.is_file() or hashlib.sha256(current.read_bytes()).hexdigest()!=manifest['files'][file]:
            raise ValueError('baseline changed before normalization')
    archive.mkdir(exist_ok=True)
    original=archive/'original.py';record=archive/'format.json'
    if original.exists():
        data=original.read_bytes()
        if original.is_symlink():raise ValueError('unsafe normalization archive')
    else:data=target.read_bytes()
    if not 32768<len(data)<=65536 or hashlib.sha256(data).hexdigest()!=selection['sha256']:
        raise ValueError('normalization source drift or not oversized')
    tree=ast.parse(data);formatted=(ast.unparse(tree)+'\n').encode()
    if (len(formatted)>32768 or ast.dump(tree,include_attributes=False)!=ast.dump(ast.parse(formatted),include_attributes=False)):
        raise ValueError('formatting does not meet exact AST and byte gate')
    if target.read_bytes() not in (data,formatted):raise ValueError('normalization workspace drift')
    receipt={'operation':'python_ast_preserving_format','path':name,'original_bytes':len(data),
             'original_sha256':selection['sha256'],'formatted_bytes':len(formatted),
             'formatted_sha256':hashlib.sha256(formatted).hexdigest(),'identical_ast':True}
    # Preserve the exact pre-format artifact before any workspace write. A crash
    # resumes against these bytes, never accepts an arbitrary replacement.
    if not original.exists():
        with original.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        original.chmod(0o400)
    if record.exists():
        if record.is_symlink() or json.loads(record.read_text())!=receipt:raise ValueError('normalization receipt drift')
    else:
        with record.open('x') as stream:json.dump(receipt,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        record.chmod(0o400)
    if target.read_bytes()==data:
        with target.open('wb') as stream:stream.write(formatted);stream.flush();os.fsync(stream.fileno())
    if target.read_bytes()!=formatted:raise ValueError('normalized write verification failed')
    return receipt


if __name__=='__main__':
    print(json.dumps(normalize('/base','/workspace','/snapshot',json.loads(os.environ['NORMALIZE_SELECTION'])),sort_keys=True))
