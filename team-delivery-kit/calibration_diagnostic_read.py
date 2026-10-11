"""Fixed read-only snapshot operation for isolated diagnostics, not task proof."""
import hashlib
import json
from pathlib import Path
from calibration_response_contract import safe_path


def page(args, expected_manifest=None):
    if (set(args) != {'path','offset','limit'} or not safe_path(args['path'],'bundle')
            or type(args['offset']) is not int or args['offset'] < 1
            or type(args['limit']) is not int or not 1 <= args['limit'] <= 100):
        raise ValueError('bounded snapshot page required')
    parts=args['path'].split('/');root=Path('/evidence')/parts[2]
    relative='/'.join(parts[3:]);path=root/relative
    if path.suffix not in {'.py','.html','.js','.jsx','.ts','.tsx','.css'}:
        raise ValueError('only declared code or test files permitted')
    for item in [path,*path.parents]:
        if item==root.parent:break
        if item.is_symlink():raise ValueError('snapshot symlink forbidden')
    manifest_path=root/'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('regular snapshot manifest required')
    raw=manifest_path.read_bytes()
    if len(raw)>2097152:raise ValueError('bounded snapshot manifest required')
    manifest_hash=hashlib.sha256(raw).hexdigest()
    if expected_manifest is not None and manifest_hash!=expected_manifest:
        raise ValueError('snapshot manifest drift')
    files=json.loads(raw)['files'];declared=files.get(relative)
    if not declared or not path.is_file():raise ValueError('declared snapshot file required')
    content=path.read_bytes()
    if (len(content)>524288 or len(content)!=declared['bytes']
            or hashlib.sha256(content).hexdigest()!=declared['sha256']):
        raise ValueError('snapshot file drift or size limit')
    lines=content.decode('utf-8').splitlines()
    start=args['offset']-1
    if start>=len(lines):raise ValueError('existing snapshot page required')
    output=json.dumps({'total_lines':len(lines),'content':'\n'.join(
        str(i+1)+'|'+lines[i] for i in range(start,min(start+args['limit'],len(lines))))})
    if len(output.encode())>131072:raise ValueError('snapshot page too large')
    return {'output':output,'file_sha256':declared['sha256'],'manifest_sha256':manifest_hash}


def complete(path, expected_manifest):
    """Bounded local pagination; never calls a model or creates native receipts."""
    first=page({'path':path,'offset':1,'limit':100},expected_manifest)
    total=json.loads(first['output'])['total_lines']
    if total>3200:raise ValueError('dependency exceeds complete-read page budget')
    pages=[first]
    for offset in range(101,total+1,100):
        current=page({'path':path,'offset':offset,'limit':100},expected_manifest)
        if (current['file_sha256']!=first['file_sha256']
                or json.loads(current['output'])['total_lines']!=total):
            raise ValueError('dependency changed during complete read')
        pages.append(current)
    if sum(len(p['output'].encode()) for p in pages)>450000:
        raise ValueError('complete dependency exceeds context budget')
    return dict(path=path,total_lines=total,pages=pages,
        file_sha256=first['file_sha256'],manifest_sha256=first['manifest_sha256'],
        native_read_evidence=False,execution_authorized=False,delivery_approval=False)
