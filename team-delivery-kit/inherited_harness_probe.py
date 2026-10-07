"""Hash-verified syntax experiment. Never import tests or execute product code."""
import ast
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import subprocess
from r3_snapshot_probe import probe as verify_snapshot


def digest(raw):return hashlib.sha256(raw).hexdigest()


def literal_template(source,name):
    if not re.fullmatch('[A-Z][A-Z_0-9]{1,80}',name):raise ValueError('literal template name required')
    values=[node.value.value for node in ast.parse(source).body
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets)
        and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)]
    if len(values)!=1:raise ValueError('one constant harness template required')
    # Filename substitution only; never evaluate Python or JavaScript here.
    return values[0] % dict(source_path=json.dumps('/delivery/product.js'),source_filename=json.dumps('/delivery/product.js'))


def syntax(source):
    result=subprocess.run(['node','--check','--input-type=commonjs'],input=source.encode(),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False)
    error=result.stderr.decode(errors='replace')
    category=('valid' if result.returncode==0 else 'illegal_return' if 'Illegal return statement' in error
              else 'syntax_error' if 'SyntaxError' in error else 'compiler_failure')
    return dict(exit_code=result.returncode,category=category,output_sha256=digest(result.stdout+result.stderr))


def run(root,manifest,test_file,product_file,template_name):
    root=Path(root);identity=verify_snapshot(root,manifest)
    for name,suffix in ((test_file,'.py'),(product_file,'.js')):
        path=PurePosixPath(name)
        if path.is_absolute() or path.as_posix()!=name or '..' in path.parts or not name.endswith(suffix):
            raise ValueError('canonical declared syntax input required')
    inventory=json.loads((root/'manifest.json').read_text())['files']
    if test_file not in inventory or product_file not in inventory:raise ValueError('frozen declared inputs required')
    test=(root/test_file).read_bytes();product=(root/product_file).read_bytes()
    harness=literal_template(test.decode(),template_name)
    result=dict(operation='immutable_embedded_harness_syntax_experiment_v1',
        manifest_sha256=identity['manifest_sha256'],test_file=test_file,product_file=product_file,
        template_name=template_name,test_sha256=digest(test),product_sha256=digest(product),
        harness_sha256=digest(harness.encode()),harness=syntax(harness),product=syntax(product.decode()),
        control=syntax("'use strict';\nfunction flush() { return Promise.resolve(); }\n"),
        product_executed=False,test_edits_authorized=False,delivery_approval=False)
    if result['control']['exit_code']!=0:raise ValueError('compiler control failed')
    verify_snapshot(root,manifest)  # Input hashes must still match after probe.
    return result


if __name__=='__main__':
    import sys
    print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
