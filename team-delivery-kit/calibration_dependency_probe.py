"""Static frozen Path-global discovery and stronger read-contract experiment.

Never imports or executes delivered tests/product code. This proves only which
literal repository paths can be resolved statically and that adding them to the
existing mandatory-read capsule forces pagination before producer choice.
"""
import ast
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import sys

import calibration_response_contract as contract
from generic_harness_calibration import require,relative
from r3_snapshot_probe import probe


def resolve(node,values,test_path):
    if isinstance(node,ast.Name):return values.get(node.id)
    if isinstance(node,ast.Constant) and isinstance(node.value,str):return node.value
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='Path':
        require(len(node.args)==1 and not node.keywords)
        if isinstance(node.args[0],ast.Name) and node.args[0].id=='__file__':return tuple(PurePosixPath(test_path).parts)
        return None # No cwd, filesystem, imports or arbitrary Python evaluation.
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='resolve':
        require(not node.args and not node.keywords);return resolve(node.func.value,values,test_path)
    if isinstance(node,ast.Attribute) and node.attr=='parent':
        value=resolve(node.value,values,test_path)
        require(isinstance(value,tuple) and value);return value[:-1]
    if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Attribute) and node.value.attr=='parents':
        value=resolve(node.value.value,values,test_path);index=node.slice
        require(isinstance(value,tuple) and isinstance(index,ast.Constant) and type(index.value) is int
            and 0<=index.value<len(value));return value[:len(value)-index.value-1]
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):
        left,right=resolve(node.left,values,test_path),resolve(node.right,values,test_path)
        if not isinstance(left,tuple):return None
        require(isinstance(right,str));relative(right)
        return left+tuple(PurePosixPath(right).parts)
    return None


def discover(raw,path,files):
    require(isinstance(raw,bytes) and 0<len(raw)<=32768);relative(path)
    values={};result=[]
    for node in ast.parse(raw.decode(),filename=path).body:
        if not isinstance(node,ast.Assign) or len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name):continue
        name=node.targets[0].id
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,119}',name):continue
        value=resolve(node.value,values,path)
        referenced={n.id for n in ast.walk(node.value) if isinstance(n,ast.Name)}
        if value is None:
            require('Path' not in referenced and not any(isinstance(values.get(n),tuple) for n in referenced))
            continue
        values[name]=value
        if not isinstance(value,tuple) or not value:continue
        target='/'.join(value);relative(target)
        if target not in files:
            require(any(p.startswith(target+'/') for p in files));continue # A repository directory, not a fixture file.
        require(target!=path)
        result.append(dict(module=path,attribute=name,path=target,sha256=files[target]['sha256']))
    require(1<=len(result)<=16)
    return result


def read_contract_experiment():
    path='/evidence/candidate/tests/test_synthetic.py';dep='/evidence/candidate/app/fixture.js'
    context=contract.context('bundle',[path,dep],'a'*64,engine='unittest_path_fixtures_v2')
    def body(lines):
        messages=[dict(role='user',content=contract.capsule(context))]
        for i,(target,content,total) in enumerate(lines):
            messages.extend([dict(role='assistant',tool_calls=[dict(id=str(i),type='function',function=dict(name='read_file',
                arguments=json.dumps(dict(path=target,offset=1,limit=100))))]),dict(role='tool',tool_call_id=str(i),
                content=json.dumps(dict(content=content,total_lines=total)))])
        return dict(messages=messages,tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
    partial=contract.apply(body([(path,'1|test',1),(dep,'1|first',2)]))
    params=partial['tools'][0]['function']['parameters']['properties']
    require(partial['tool_choice']==dict(type='function',function=dict(name='read_file'))
        and params['path']['enum']==[dep] and params['offset']['enum']==[2])
    complete=contract.apply(body([(path,'1|test',1),(dep,'1|first\n2|second',2)]))
    require(complete['tool_choice']=='auto' and contract.request(complete)==context)
    return dict(partial_dependency_forces_next_page=True,complete_dependency_restores_producer_choice=True,
        canonical_contract_unchanged=True)


def run(root,manifest,tests):
    root=Path(root);require(isinstance(tests,list) and 1<=len(tests)<=32 and tests==sorted(set(tests)))
    probe(root,manifest);files=json.loads((root/'manifest.json').read_bytes())['files'];dependencies=[];hashes={}
    for path in tests:
        relative(path);require(path in files and path.endswith('.py'))
        raw=(root/path).read_bytes();hashes[path]=hashlib.sha256(raw).hexdigest()
        dependencies.extend(discover(raw,path,files))
    paths=sorted({'/evidence/'+role+'/'+p for role in ('candidate','previous') for p in tests}
        |{'/evidence/candidate/'+d['path'] for d in dependencies})
    result=dict(operation='static_calibration_dependency_probe_v1',manifest_sha256=manifest,test_sha256=hashes,
        dependencies=dependencies,required_paths=paths,checks=read_contract_experiment(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        contract_sha256=hashlib.sha256(Path(contract.__file__).read_bytes()).hexdigest(),
        model_calls=0,product_tests_executed=False,historical_cause_proven=False,
        author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
    probe(root,manifest);return result


if __name__=='__main__':print(json.dumps(run(sys.argv[1],sys.argv[2],json.loads(sys.argv[3])),sort_keys=True))
