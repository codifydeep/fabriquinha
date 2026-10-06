"""Readonly diagnostic instrumentation of a frozen driver; NEVER Green evidence."""
import hashlib,importlib.util,json,os,shutil,subprocess
from pathlib import Path
root=Path('/seed');path=root/'tests/test_incremental_u3.py'
if hashlib.sha256(path.read_bytes()).hexdigest()!=os.environ['EXPECTED_TEST']:
    raise ValueError('exact frozen diagnostic test required')
spec=importlib.util.spec_from_file_location('frozen_driver',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
program='let queueTrace=[];\n'+module.DRIVER_PREAMBLE % {'source_path':json.dumps(str(module.APP_JS_PATH)),
    'html_path':json.dumps(str(module.INDEX_HTML_PATH))}+module.DRIVER_BODY
patches={
    'pending.push({ url: target, resolve: resolve });':
        "pending.push({ url: target, resolve: resolve });queueTrace.push({op:'held',url:target,size:pending.length});",
    'function resolveNewest(body) {':
        "function resolveNewest(body) {queueTrace.push({op:'newest',urls:pending.map(p=>p.url)});",
    'function resolveOldest(body) {':
        "function resolveOldest(body) {queueTrace.push({op:'oldest',urls:pending.map(p=>p.url)});",
    'function report(payload) { process.stdout.write(JSON.stringify(payload)); }':
        'function report(payload) { payload.queue_trace=queueTrace;payload.remaining_urls=pending.map(p=>p.url);process.stdout.write(JSON.stringify(payload)); }'}
for old,new in patches.items():
    if program.count(old)!=1:raise ValueError('fixed diagnostic anchor drift')
    program=program.replace(old,new)
result=subprocess.run([shutil.which('node'),'--input-type=commonjs','-'],input=program,
    text=True,capture_output=True,timeout=20,env={'PATH':os.environ['PATH']},check=True)
report=json.loads(result.stdout)
print(json.dumps({'schema':'c10-queue-diagnostic-v1','test_sha256':os.environ['EXPECTED_TEST'],
    'instrumented_program_sha256':hashlib.sha256(program.encode()).hexdigest(),
    'snapshot_modified':False,'functional_green':False,'delivery_approval':False,
    'pending_left':report.get('pending_left'),'remaining_urls':report.get('remaining_urls'),
    'trace':report['queue_trace'][-20:]}))
