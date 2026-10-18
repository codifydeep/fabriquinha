"""Counterexample experiment for a frozen Node UI test harness, NOT calibration.

Run only in the fixed no-network/no-credentials sandbox with a readonly candidate.
Parse Python AST without importing tests. Execute the literal Node harness using
a deliberately unguarded, tiny diagnostic request driver in temporary storage.
It is neither candidate implementation nor a positive calibration reference.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from generic_harness_calibration import require
from r3_snapshot_probe import probe

FALSE_FLAGS=('calibration_approved','red_approved','product_green','author_retry_authorized',
    'execution_authorized','delivery_approval','full_regression_suite_executed','python_test_module_imported',
    'python_assertions_executed','candidate_implementation_changed','positive_reference_submitted')


def bind(source):
    tree=ast.parse(source);constants={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            key=node.targets[0].id
            if key in ('PREFIX','NODE_HARNESS'):
                require(key not in constants and isinstance(node.value,ast.Constant) and type(node.value.value) is str)
                constants[key]=node.value.value
    require(set(constants)=={'PREFIX','NODE_HARNESS'} and 1<=len(constants['PREFIX'])<=120
        and 1<=len(constants['NODE_HARNESS'].encode())<=65536)
    names=('test_stale_response_never_overwrites_newer_query','test_poll_and_filter_change_request_latest')
    methods={}
    for cls in tree.body:
        if not isinstance(cls,ast.ClassDef):continue
        for node in cls.body:
            if isinstance(node,ast.FunctionDef) and node.name in names:
                require(node.name not in methods and not node.decorator_list);methods[node.name]=node
    require(set(methods)==set(names))
    def operand(node):
        if isinstance(node,ast.Constant) and type(node.value) in (str,int):return node.value
        if isinstance(node,ast.Name) and node.id=='PREFIX':return constants['PREFIX']
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):
            left,right=operand(node.left),operand(node.right);require(type(left) is str and type(right) is str);return left+right
        raise ValueError('fixed literal comparison operand required')
    def assertion(method,field,kind):
        found=[]
        for expr in methods[method].body:
            if not isinstance(expr,ast.Expr) or not isinstance(expr.value,ast.Call):continue
            call=expr.value;func=call.func
            if not (isinstance(func,ast.Attribute) and isinstance(func.value,ast.Name) and func.value.id=='self'
                    and func.attr==kind and len(call.args)==2 and not call.keywords):continue
            arg=call.args[0]
            if not (isinstance(arg,ast.Subscript) and isinstance(arg.value,ast.Attribute)
                    and isinstance(arg.value.value,ast.Name) and arg.value.value.id=='self' and arg.value.attr=='report'
                    and isinstance(arg.slice,ast.Constant) and arg.slice.value==field):continue
            found.append((operand(call.args[1]),call.lineno))
        require(len(found)==1);return found[0]
    stale,line=assertion(names[0],'stale_guard_text','assertEqual')
    require(len(methods[names[0]].body)==1 and type(stale) is str)
    initial,_=assertion(names[1],'initial_requests','assertEqual')
    minimum,poll_line=assertion(names[1],'poll_requests','assertGreaterEqual')
    require(type(initial) is int and type(minimum) is int and 0<=initial<=100 and 0<=minimum<=100)
    return dict(prefix=constants['PREFIX'],harness=constants['NODE_HARNESS'],stale_expected=stale,
        stale_assertion_line=line,initial_expected=initial,poll_minimum=minimum,poll_assertion_line=poll_line)


def witness(prefix):
    return ''''use strict';
const line = document.getElementById('feedback-latest-match');
const prefix = %s;
let status = 'all';
function refresh() {
  line.textContent = prefix + '\\u2026';
  fetch('/feedback/latest?status=' + status)
    .then(response => response.json())
    .then(body => { line.textContent = prefix + (body.latest_id === null ? '\\u2014' : '#' + body.latest_id); })
    .catch(() => { line.textContent = 'Newest matching unavailable'; });
}
for (const value of ['all', 'open', 'completed']) {
  document.getElementById('filter-' + value).addEventListener('click', () => { status = value; refresh(); });
}
setInterval(refresh, 1000);
refresh();
''' % json.dumps(prefix)


RACE='''const vm = require('vm');
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const line = {textContent: ''};
const handlers = {};
const requests = [];
const doc = {getElementById: id => id === 'feedback-latest-match' ? line :
  {addEventListener: (event, fn) => { handlers[id] = fn; }}};
const fetchStub = url => new Promise(resolve => requests.push({url, resolve}));
vm.runInNewContext(source, {document: doc, fetch: fetchStub, setInterval: () => 0});
async function flush() {for (let i = 0; i < 20; i++) await Promise.resolve();}
function complete(i, id) {requests[i].resolve({json: () => Promise.resolve({latest_id:id})});}
(async () => {
  complete(0,7); await flush();
  handlers['filter-open']();
  handlers['filter-completed']();
  complete(2,11); await flush(); const fresh = line.textContent;
  complete(1,4); await flush();
  process.stdout.write(JSON.stringify({requests:requests.length,fresh_text:fresh,after_late_text:line.textContent}));
})().catch(() => {process.exitCode=1;});
'''


def node(program,*arguments):
    result=subprocess.run(['node','--input-type=commonjs','-',*arguments],input=program.encode(),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=False)
    require(result.returncode==0 and 0<len(result.stdout)<=65536 and not result.stderr)
    value=json.loads(result.stdout);require(isinstance(value,dict));return value


def measurements(bound,frozen,race):
    require(frozen.get('executed') is True and type(frozen.get('initial_requests')) is int
        and type(frozen.get('poll_requests')) is int and isinstance(frozen.get('stale_guard_text'),str)
        and type(race.get('requests')) is int and race['requests']==3
        and isinstance(race.get('fresh_text'),str) and isinstance(race.get('after_late_text'),str))
    return dict(initial_requests=frozen['initial_requests'],poll_requests=frozen['poll_requests'],
        initial_comparison_satisfied=frozen['initial_requests']==bound['initial_expected'],
        one_refresh_per_poll_satisfies_poll_comparison=frozen['poll_requests']>=bound['poll_minimum'],
        unguarded_witness_satisfies_stale_comparison=frozen['stale_guard_text']==bound['stale_expected'],
        witness_really_accepts_stale_responses=race['fresh_text']==bound['prefix']+'#11'
            and race['after_late_text']==bound['prefix']+'#4',
        frozen_stale_text=frozen['stale_guard_text'],counterfactual_race=race,
        **{k:False for k in FALSE_FLAGS})


def run(candidate,manifest,test_sha):
    candidate=Path(candidate);probe(candidate,manifest)
    path='tests/test_feedback_latest_ui.py';raw=(candidate/path).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==test_sha);bound=bind(raw.decode());driver=witness(bound['prefix'])
    try:
        with tempfile.TemporaryDirectory(prefix='harness-protocol-') as folder:
            file=Path(folder)/'request-driver.js';file.write_text(driver)
            frozen=node(bound['harness']%dict(source_path=json.dumps(str(file)),source_name=json.dumps(str(file))))
            race=node(RACE,str(file))
        result=measurements(bound,frozen,race)
        return dict(operation='frozen_harness_protocol_counterexample_v1',candidate_manifest_sha256=manifest,
            probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            test_sha256={path:test_sha},witness_sha256=hashlib.sha256(driver.encode()).hexdigest(),
            harness_sha256=hashlib.sha256(bound['harness'].encode()).hexdigest(),
            assertion_bindings={k:bound[k] for k in ('stale_expected','stale_assertion_line','initial_expected','poll_minimum','poll_assertion_line')},
            frozen_node_harness_executed=True,snapshot_unchanged=True,model_calls=0,
            measurements=result,**{k:False for k in FALSE_FLAGS})
    finally:probe(candidate,manifest)


if __name__=='__main__':
    require(len(sys.argv)==4);signal.alarm(100)
    require(not Path('/var/run/docker.sock').exists() and not any(os.environ.get(k)
        for k in ('OPENROUTER_API_KEY','GITHUB_TOKEN','GH_TOKEN','BROKER_TOKEN')))
    print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
