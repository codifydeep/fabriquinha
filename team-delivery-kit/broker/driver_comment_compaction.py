"""Fixed controller transform: comments only, with JavaScript/Python AST equality."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

TEST='tests/test_incremental_u3.py'
NODE_CHECK=r'''
const vm=require('vm'), crypto=require('crypto'),fs=require('fs');
const key='internal/deps/acorn/acorn/dist/acorn';
const source=process.binding('natives')[key];
if(typeof source!=='string')throw Error('bundled parser unavailable');
const exports={};vm.runInNewContext(source,{exports,module:{exports}});
const parse=exports.parse;
if(typeof parse!=='function')throw Error('parser unavailable');
const input=JSON.parse(fs.readFileSync(0,'utf8'));const comments=[];
const options={ecmaVersion:'latest',sourceType:'script'};
const before=parse(input.body,{...options,onComment:comments});
let after=input.body,removed=0;
for(const comment of comments.reverse()) {
  if(comment.value.includes('C10STATUS'))continue;
  after=after.slice(0,comment.start)+' '+after.slice(comment.start,comment.end).replace(/[^\r\n]/g,'')+after.slice(comment.end);
  removed++;
}
// Removing whitespace-only lines is accepted only when the parsed AST is identical.
after=after.split('\n').filter(line=>line.trim()!=='').join('\n');
const clean=(key,value)=>(key==='start'||key==='end')?undefined:value;
const a=JSON.stringify(before,clean),b=JSON.stringify(parse(after,options),clean);
if(a!==b)throw Error('JavaScript AST changed');
console.log(JSON.stringify({body:after,comments_removed:removed,
  javascript_ast_sha256:crypto.createHash('sha256').update(a).digest('hex')}));
'''


def compact(source):
    tree=ast.parse(source);nodes=[n for n in tree.body if isinstance(n,ast.Assign)
        and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='DRIVER_BODY']
    if len(nodes)!=1:raise ValueError('one literal DRIVER_BODY required')
    literal=nodes[0].value;body=ast.literal_eval(literal)
    if not isinstance(body,str):raise ValueError('string driver required')
    checked=subprocess.run(['node','-e',NODE_CHECK],input=json.dumps({'body':body}),
        text=True,capture_output=True,timeout=10)
    if checked.returncode:raise ValueError('fixed AST-preserving compaction rejected')
    proof=json.loads(checked.stdout)
    lines=source.splitlines(keepends=True)
    start=sum(map(len,lines[:literal.lineno-1]))+literal.col_offset
    end=sum(map(len,lines[:literal.end_lineno-1]))+literal.end_col_offset
    body=proof.pop('body')
    # Preserve physical source lines for bounded full reads and exact surgical anchors.
    expression='r"""'+body+'"""'
    try:literal_body=ast.literal_eval(expression)
    except (SyntaxError,ValueError):raise ValueError('safe multiline driver representation required') from None
    if literal_body!=body:raise ValueError('driver literal representation changed')
    result=source[:start]+expression.encode('utf-8')+source[end:]
    before=ast.parse(source);after=ast.parse(result)
    for t in (before,after):
        node=next(n for n in t.body if isinstance(n,ast.Assign) and
            len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='DRIVER_BODY')
        node.value=ast.Constant(value='DRIVER_ONLY')
    if ast.dump(before,include_attributes=False)!=ast.dump(after,include_attributes=False):raise ValueError('non-driver Python AST changed')
    if not 0<len(result)<len(source)<=32768 or proof['comments_removed']<1:raise ValueError('no bounded compaction savings')
    return result,dict(proof,source_sha256=hashlib.sha256(source).hexdigest(),
        compacted_sha256=hashlib.sha256(result).hexdigest(),source_bytes=len(source),compacted_bytes=len(result),
        non_driver_ast_preserved=True,javascript_ast_preserved=True,delivery_approval=False,
        operation='controller_driver_comment_compaction')


def main():
    try:from maintenance_snapshot_validate import manifest
    except ImportError:from broker.maintenance_snapshot_validate import manifest
    source,destination=Path('/source'),Path('/compacted')
    raw,files=manifest(source)
    if hashlib.sha256(raw).hexdigest()!=os.environ['EXPECTED_MANIFEST']:raise ValueError('source manifest drift')
    if files[TEST]['sha256']!=os.environ['EXPECTED_TEST']:raise ValueError('source test drift')
    if any(destination.iterdir()):raise ValueError('fresh transform destination required')
    result,receipt=compact((source/TEST).read_bytes())
    updated={}
    for name in files:
        content=result if name==TEST else (source/name).read_bytes()
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o400),'wb') as f:f.write(content)
        updated[name]={'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}
    encoded=json.dumps({'files':updated},sort_keys=True,separators=(',',':')).encode()
    with os.fdopen(os.open(destination/'manifest.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o400),'wb') as f:f.write(encoded)
    manifest(destination)
    receipt['manifest_sha256']=hashlib.sha256(encoded).hexdigest()
    print(json.dumps(receipt))


if __name__=='__main__':main()
