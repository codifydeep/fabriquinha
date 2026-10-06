"""Read-only behavioral diagnosis on exact Git bytes; never TDD/release evidence."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

SHA='e45c26256d8d0d3fa20b5d7bd021234421bcc2c1'
FILES=('app/static/app.js','app/static/index.html','tests/test_incremental_u3.py')
DRIVER=r'''
async function diagnose() {
  vm.runInContext(SOURCE, context, {filename: SOURCE_PATH});
  await flush();
  deferred.push(true);
  input(searchInput, 'alpha');
  target.loadFeedback();
  if (pending.length !== 2 || pending[0].url !== pending[1].url) {
    throw new Error('two identical view requests required');
  }
  const urls=pending.map(x=>x.url);
  resolveNewest({items:[{id:2,title:'CURRENT alpha',completed:false}]});
  await flush();
  const current=renderedTitles();
  resolveOldest({items:[{id:1,title:'STALE alpha',completed:false}]});
  await flush();
  const afterStale=renderedTitles();
  input(searchInput, 'absent');
  resolveNewest({items:[]});
  await flush();
  const message=byId['empty-state'].textContent;
  const visible=!byId['empty-state'].hidden;
  input(searchInput, '');
  resolveNewest({items:[{id:2,title:'CURRENT alpha',completed:false}]});
  await flush();
  report({executed:true,urls:urls,current:current,after_stale:afterStale,
          stale_same_view_discarded:JSON.stringify(current)===JSON.stringify(afterStale),
          empty_message:message,empty_visible:visible,after_clear:renderedTitles(),pending_left:pending.length});
}
diagnose().catch(e=>{report({executed:false,error:String(e)});process.exitCode=1;});
'''


def preamble(raw):
    tree=ast.parse(raw)
    values=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='DRIVER_PREAMBLE' for t in n.targets)]
    if len(values)!=1 or not isinstance(values[0],str):raise ValueError('exact literal DOM harness required')
    return values[0]


def run(repo):
    node=shutil.which('node')
    if not node:raise ValueError('Node required; never skip diagnosis')
    raw={name:subprocess.check_output(['git','-C',str(repo),'show',SHA+':'+name]) for name in FILES}
    with tempfile.TemporaryDirectory(prefix='delivery-kit-scope-audit-') as folder:
        root=Path(folder)
        for name,data in raw.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        program=preamble(raw[FILES[2]].decode())%dict(source_path=json.dumps(str(root/FILES[0])),html_path=json.dumps(str(root/FILES[1])))+DRIVER
        result=subprocess.run([node,'--input-type=commonjs','-'],input=program,text=True,capture_output=True,timeout=30)
        observed=json.loads(result.stdout)
        if result.returncode or observed.get('executed') is not True:raise ValueError('diagnosis failed to execute')
    return dict(schema='search-scope-diagnosis-v1',source_sha=SHA,
        file_sha256={n:hashlib.sha256(v).hexdigest() for n,v in raw.items()},
        driver_sha256=hashlib.sha256(DRIVER.encode()).hexdigest(),observed=observed,
        product_modified=False,model_calls=0,historical_tdd_red=False,release_homologated=False,
        interpretation=dict(C10='missing_same_view_request_generation_guard' if not observed['stale_same_view_discarded'] else 'observed_pass',
                            C11='empty_search_message_requires_semantic_review'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.repo),indent=2))
