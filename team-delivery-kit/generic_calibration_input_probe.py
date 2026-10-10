"""Read/hash/AST-only input proof; never import or execute submitted tests."""
import ast
import json
from pathlib import Path
import sys

from generic_harness_calibration import validate_policy,require
from r3_snapshot_probe import probe


def methods(root,path):
    tree=ast.parse((Path(root)/path).read_text())
    classes={}
    for node in tree.body:
        if isinstance(node,ast.ClassDef):
            names=[n.name for n in node.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
                and n.name.startswith('test_')]
            if names:
                require(node.name not in classes and len(set(names))==len(names))
                classes[node.name]=sorted(names)
    require(bool(classes))
    return classes


def run(candidate,previous,controls,policy,expected,previous_manifest):
    p=validate_policy(policy,expected)
    roots=[(Path(candidate),p['candidate_manifest_sha256']),(Path(previous),previous_manifest),
        (Path(controls),p['controls_manifest_sha256'])]
    for root,sha in roots:probe(root,sha)
    current=json.loads((roots[0][0]/'manifest.json').read_text())['files']
    prior=json.loads((roots[1][0]/'manifest.json').read_text())['files']
    fixtures=json.loads((roots[2][0]/'manifest.json').read_text())['files']
    expected_fixtures={m['positive_fixture'] for m in p['modules']}|{n['fixture'] for n in p['negatives']}
    require(set(fixtures)==expected_fixtures)
    candidate_methods={};previous_methods={};previous_tests={};products={}
    for m in p['modules']:
        path=m['path'];require(path in prior and path in current and m['product_path'] in current)
        require(current[path]['sha256']==p['test_sha256'][path])
        candidate_methods[path]=methods(candidate,path);previous_methods[path]=methods(previous,path)
        normalized=lambda classes:{k:sorted(v) for k,v in classes.items()}
        require(candidate_methods[path]==normalized(m['classes'])
            and previous_methods[path]==normalized(p['previous_methods'][path]))
        previous_tests[path]=prior[path]['sha256'];products[m['product_path']]=current[m['product_path']]['sha256']
    for root,sha in roots:probe(root,sha)
    return dict(operation='generic_calibration_inputs_v1',policy_sha256=expected,
        candidate_manifest_sha256=p['candidate_manifest_sha256'],previous_manifest_sha256=previous_manifest,
        controls_manifest_sha256=p['controls_manifest_sha256'],candidate_test_sha256=p['test_sha256'],
        # AST equality above is order-independent; retain the exact approved
        # ordering so downstream hash-bound context does not acquire new bytes.
        previous_test_sha256=previous_tests,candidate_methods=candidate_methods,previous_methods=p['previous_methods'],
        product_sha256=products,control_sha256={name:record['sha256'] for name,record in fixtures.items()},
        tests_executed=False,execution_authorized=False,delivery_approval=False)


if __name__=='__main__':
    try:
        require(len(sys.argv)==7)
        policy=Path(sys.argv[4]);require(not policy.is_symlink() and policy.stat().st_size<=524288)
        print(json.dumps(run(sys.argv[1],sys.argv[2],sys.argv[3],json.loads(policy.read_text()),
            sys.argv[5],sys.argv[6]),sort_keys=True))
    except Exception as error:
        print(json.dumps(dict(status='rejected',category=type(error).__name__,tests_executed=False,
            execution_authorized=False,delivery_approval=False)));sys.exit(1)
