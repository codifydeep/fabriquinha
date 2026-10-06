"""Controller-only dependency resolver/image builder. Never mounts credentials/socket into jobs."""
import hashlib,json,sqlite3,subprocess,tempfile,time,threading
from pathlib import Path
from product_workspace import digest
from product_recovery import CONFIGS,apply_dependencies

BASE='node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5'
def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS product_validation_jobs(id TEXT PRIMARY KEY,request TEXT,result TEXT,state TEXT,error TEXT)');db.commit()
def execute(root,settings,job,request):
    db=sqlite3.connect(root/'controller.db',timeout=15)
    row=db.execute('SELECT proposal,verdict,state FROM team_decisions WHERE task=?',(request['approval_task'],)).fetchone();db.close()
    if not row or row[2]!='DELIVERED':raise PermissionError('durable approval required')
    proposal,verdict=json.loads(row[0]),json.loads(row[1])
    if verdict['decision']!='approve' or verdict['proposal_sha256']!=request['approval_sha'] or digest(proposal)!=request['approval_sha']:raise PermissionError('exact technical approval required')
    if proposal['action'] not in ('return_to_author','enable_shared_build','prepare_toolchain') or proposal['head']!=request['head']:raise PermissionError('validation approval scope')
    files=dict(request['files'])
    if proposal['action']=='prepare_toolchain':
        from product_platform import configs
        files=configs(files,proposal['specification']);spec={k:proposal['specification'][k] for k in ('dependencies','devDependencies')}
    elif proposal['action']=='enable_shared_build':
        from product_build_contract import enable_shared_build
        if proposal['specification']['target_task']!=request['target_task'] or proposal['specification']['draft_sha256']!=request['draft_sha256']:raise PermissionError('build approval target')
        files['tsconfig.build.json']=enable_shared_build(files['tsconfig.build.json'])
        spec=dict(dependencies={},devDependencies={})
    else:
        spec={k:proposal['specification'][k] for k in ('dependencies','devDependencies')}
        files['package.json']=apply_dependencies(files['package.json'],spec)
    with tempfile.TemporaryDirectory(prefix='validation-job-',dir=settings['snapshot_root']) as folder:
        context=Path(folder);context.chmod(0o755)
        for n in CONFIGS:(context/n).write_text(files[n])
        def command(args,timeout=300):
            result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
            if result.returncode:raise RuntimeError('validation preparation failed: '+(result.stdout+result.stderr)[-3500:])
            return result.stdout
        name='truco-online-dependencies-'+job[:12]
        try:
            if any(spec.values()):
                command(['docker','run','--rm','--name',name,'--label','com.docker.compose.project=truco-online','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--user=0:0','--memory=512m','--pids-limit=64','--tmpfs=/tmp:rw,size=256m','-e','npm_config_cache=/tmp/npm','-e','npm_config_fetch_timeout=20000','-e','npm_config_fetch_retries=1','-e','NODE_OPTIONS=--dns-result-order=ipv4first','--mount',f'type=bind,source={context},target=/work','-w','/work','--entrypoint','npm',settings['image'],'install','--package-lock-only','--ignore-scripts','--no-audit'])
            files['package-lock.json']=(context/'package-lock.json').read_text()
            contract={n:hashlib.sha256(files[n].encode()).hexdigest() for n in CONFIGS}
            (context/'project-contract.json').write_text(json.dumps(contract))
            for n in ('run.mjs','vitest.config.mjs'):(context/n).write_text((Path('/opt/hermes/project-validator')/n).read_text())
            (context/'Dockerfile').write_text('FROM '+BASE+'\nWORKDIR /opt/toolchain\nCOPY package.json package-lock.json ./\nRUN npm ci --ignore-scripts --no-audit --no-fund && npm audit --audit-level=high\nCOPY run.mjs vitest.config.mjs project-contract.json ./\nUSER 10000:10000\nENTRYPOINT ["node", "/opt/toolchain/run.mjs"]\n')
            tag='truco-online-project-validation:'+job[:16]
            command(['docker','build','--label','com.codifydeep.project=truco-online','-t',tag,str(context)],timeout=600)
            image=command(['docker','image','inspect','--format','{{.Id}}',tag]).strip()
            result=dict(image=image,configs={n:files[n] for n in CONFIGS},contract=contract,approved_by=request['approval_task'])
            if proposal['action']=='prepare_toolchain':
                from product_docker_runner import DockerRunner
                sources=dict(request['validation_sources']);sources.update(result['configs'])
                tested=DockerRunner(settings['snapshot_root'],'lobby-ts')(sources,image)
                from product_case_inventory import inventory,diagnostics
                if tested['exit_code']!=0:raise RuntimeError('platform baseline failed: '+json.dumps(diagnostics(tested)))
                result['baseline_validation']=dict(passed=True,cases=inventory(tested),source_sha256=digest(sources),log_sha256=tested['log_sha256'])
            return result
        finally:
            subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=15)
def start(root,settings):
    def loop():
        db=sqlite3.connect(root/'controller.db',timeout=15);schema(db)
        with db:db.execute("UPDATE product_validation_jobs SET state='QUEUED' WHERE state='BUILDING'")
        while True:
            if (Path(settings['board'])/'MAINTENANCE').exists():time.sleep(3);continue
            row=db.execute("SELECT id,request FROM product_validation_jobs WHERE state='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
            if not row:time.sleep(3);continue
            job,raw=row
            with db:db.execute("UPDATE product_validation_jobs SET state='BUILDING' WHERE id=?",(job,))
            try:
                result=execute(root,settings,job,json.loads(raw))
                with db:db.execute("UPDATE product_validation_jobs SET state='READY',result=? WHERE id=?",(json.dumps(result),job))
            except Exception as exc:
                with db:db.execute("UPDATE product_validation_jobs SET state='FAILED',error=? WHERE id=?",(str(exc),job))
            print(json.dumps(dict(event='validation_job',job=job,state=db.execute('SELECT state FROM product_validation_jobs WHERE id=?',(job,)).fetchone()[0])),flush=True)
    thread=threading.Thread(target=loop,daemon=True);thread.start()
