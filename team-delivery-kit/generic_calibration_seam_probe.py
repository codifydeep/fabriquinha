"""Read/hash/AST-only evidence of multiple existing snapshot Path globals.

Recognizes bounded conventional test-root expressions; unsupported roots remain
a technical hold. This is capability evidence, never a cause for a lost response,
execution authorization, TDD receipt or delivery approval.
"""
import ast
import json
from pathlib import Path
import re
import sys
from generic_harness_calibration import require,relative
from r3_snapshot_probe import probe

BASES={ast.dump(ast.parse(text,mode='eval').body,include_attributes=False) for text in (
    'Path(__file__).parents[1]','Path(__file__).resolve().parent.parent','Path(__file__).parent.parent')}


def path_expression(node,root_known):
    if ast.dump(node,include_attributes=False) in BASES:return ''
    if isinstance(node,ast.Name) and node.id=='ROOT' and root_known:return ''
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):
        left=path_expression(node.left,root_known)
        if left is not None and isinstance(node.right,ast.Constant) and isinstance(node.right.value,str):
            part=relative(node.right.value)
            return relative(left+'/'+part if left else part)
    return None


def run(candidate,manifest_sha256,test_sha256):
    require(isinstance(test_sha256,dict) and 1<=len(test_sha256)<=32)
    candidate=Path(candidate);probe(candidate,manifest_sha256)
    files=json.loads((candidate/'manifest.json').read_text())['files']
    paths={};products={};total=0
    for name,sha in test_sha256.items():
        relative(name);require(name.endswith('.py') and files.get(name,{}).get('sha256')==sha)
        require(files[name]['bytes']<=524288);total+=files[name]['bytes'];require(total<=2097152)
        tree=ast.parse((candidate/name).read_text())
        assigned={}
        for node in tree.body:
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                assigned.setdefault(node.targets[0].id,[]).append(node.value)
        root_known=(len(assigned.get('ROOT',[]))==1
            and ast.dump(assigned['ROOT'][0],include_attributes=False) in BASES)
        used={node.id for cls in tree.body if isinstance(cls,ast.ClassDef)
            for node in ast.walk(cls) if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load)}
        targets={}
        for attribute,values in assigned.items():
            if attribute=='ROOT' or attribute not in used or not re.fullmatch('[A-Z][A-Z0-9_]{0,119}',attribute):continue
            resolved=[path_expression(value,root_known) for value in values]
            if any(value is not None for value in resolved):
                require(len(values)==1 and bool(resolved[0]))
                target=resolved[0];require(target in files and target not in test_sha256)
                targets[attribute]=target;products[target]=files[target]['sha256']
        require(len(targets)<=16)
        paths[name]=targets
    require(any(len(targets)>=2 and len(set(targets.values()))==len(targets) for targets in paths.values()))
    probe(candidate,manifest_sha256)
    return dict(operation='generic_calibration_multipath_seam_v1',candidate_manifest_sha256=manifest_sha256,
        test_sha256=test_sha256,paths=paths,product_sha256=products,
        tests_executed=False,execution_authorized=False,delivery_approval=False)


if __name__=='__main__':
    try:
        require(len(sys.argv)==4)
        tests=json.loads(sys.argv[3]);require(len(sys.argv[3])<=8192)
        print(json.dumps(run(sys.argv[1],sys.argv[2],tests),sort_keys=True))
    except Exception as error:
        print(json.dumps(dict(status='rejected',category=type(error).__name__,tests_executed=False,
            execution_authorized=False,delivery_approval=False)));sys.exit(1)
