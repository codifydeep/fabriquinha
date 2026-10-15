"""Fixed AST + Node file-read SPIKE; not a product test or calibration verdict."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from generic_harness_calibration import require
from generic_calibration_seam_probe import run as seam
from r3_snapshot_probe import probe


def binding(source,targets):
    tree=ast.parse(source);templates={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
            templates[node.targets[0].id]=node.value.value
    matches=[]
    for node in ast.walk(tree):
        if not (isinstance(node,ast.BinOp) and isinstance(node.op,ast.Mod) and isinstance(node.left,ast.Name)
                and node.left.id in templates and isinstance(node.right,ast.Dict)):continue
        entries={}
        for k,v in zip(node.right.keys,node.right.values):
            if not isinstance(k,ast.Constant) or not isinstance(k.value,str):break
            text=ast.unparse(v)
            attributes=[a for a in targets if text=='json.dumps(str('+a+'))']
            if len(attributes)!=1 or k.value in entries:break
            entries[k.value]=attributes[0]
        else:
            if 'source_path' not in entries:continue
            template=templates[node.left.id]
            lines=[line.strip() for line in template.splitlines() if re.fullmatch(
                r'\s*const SOURCE = fs\.readFileSync\(%\(source_path\)s, [\'"]utf8[\'"]\);\s*',line)]
            if len(lines)==1:matches.append((node,template,entries,lines[0]))
    require(len(matches)==1)
    node,template,entries,line=matches[0]
    return dict(template_sha256=hashlib.sha256(template.encode()).hexdigest(),line=node.lineno,
        attribute=entries['source_path'],product_path=targets[entries['source_path']],statement=line)


def run(candidate,manifest,test_hashes):
    candidate=Path(candidate);facts=seam(candidate,manifest,test_hashes);node=shutil.which('node');require(bool(node))
    bindings={}
    with tempfile.TemporaryDirectory(prefix='calibration-node-path-') as folder:
        for name,targets in facts['paths'].items():
            source=(candidate/name).read_text();b=binding(source,targets);outputs={}
            for kind in ('positive','negative'):
                path=Path(folder)/(kind+'.js');content='node-path-'+kind+'\n';path.write_text(content)
                statement=b['statement'] % {'source_path':json.dumps(str(path))}
                # Execute only the recognized fixed read statement. Never import
                # the test module or execute its whole JS/DOM harness.
                program="const fs = require('fs');\n"+statement+'\nprocess.stdout.write(SOURCE);'
                r=subprocess.run([node,'-e',program],capture_output=True,timeout=5)
                require(r.returncode==0 and r.stdout==content.encode() and not r.stderr)
                outputs[kind]=hashlib.sha256(r.stdout).hexdigest()
            require(outputs['positive']!=outputs['negative'])
            bindings[name]={k:v for k,v in b.items() if k!='statement'}
            bindings[name]['reads']=outputs
    probe(candidate,manifest)
    return dict(operation='fixed_node_path_seam_v1',candidate_manifest_sha256=manifest,test_sha256=test_hashes,
        paths=facts['paths'],bindings=bindings,snapshot_unchanged=True,template_unchanged=True,
        model_calls=0,product_tests_executed=False,calibration_approved=False,red_approved=False,
        author_retry_authorized=False,execution_authorized=False,delivery_approval=False)


def validate(value,c):
    require(set(value)=={'operation','candidate_manifest_sha256','test_sha256','paths','bindings',
        'snapshot_unchanged','template_unchanged','model_calls','product_tests_executed','calibration_approved',
        'red_approved','author_retry_authorized','execution_authorized','delivery_approval'})
    require(value['operation']=='fixed_node_path_seam_v1' and value['candidate_manifest_sha256']==c['prepared']['manifest_sha256']
        and value['test_sha256']==c['prepared']['test_sha256'] and value['snapshot_unchanged'] is True
        and value['template_unchanged'] is True and type(value['model_calls']) is int and value['model_calls']==0
        and set(value['paths'])==set(value['bindings'])==set(c['test_files'])
        and all(value[k] is False for k in ('product_tests_executed','calibration_approved','red_approved',
            'author_retry_authorized','execution_authorized','delivery_approval')))
    for name,b in value['bindings'].items():
        require(set(b)=={'template_sha256','line','attribute','product_path','reads'}
            and re.fullmatch('[a-f0-9]{64}',str(b['template_sha256'])) and type(b['line']) is int and b['line']>0
            and b['attribute'] in value['paths'][name] and value['paths'][name][b['attribute']]==b['product_path']
            and b['reads']=={k:hashlib.sha256(('node-path-'+k+'\n').encode()).hexdigest() for k in ('positive','negative')})


if __name__=='__main__':
    require(len(sys.argv)==4)
    print(json.dumps(run(sys.argv[1],sys.argv[2],json.loads(sys.argv[3])),sort_keys=True))
