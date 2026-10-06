"""Generic reviewed platform requests. The controller executes only fixed jobs."""
import json
from product_policy import CAPABILITIES
from product_recovery import CONFIGS,dependencies,apply_dependencies
from product_workspace import digest

def validate(spec,requested):
    if not isinstance(spec,dict) or set(spec)!={'capability','brief','dependencies','devDependencies','targets'} or spec['capability']!=requested:raise ValueError('exact requested capability specification required')
    if requested not in ('backend','frontend','quality'):raise PermissionError('this operation prepares code validators only')
    dependencies({k:spec[k] for k in ('dependencies','devDependencies')})
    if not isinstance(spec['brief'],str) or not 100<=len(spec['brief'])<=8000:raise ValueError('executable platform rationale required')
    if not isinstance(spec['targets'],list) or set(spec['targets'])-{'server','shared','web','tests'} or not {'server','tests'}<=set(spec['targets']) or len(set(spec['targets']))!=len(spec['targets']):raise PermissionError('targets may expand, never shrink required coverage')
    if requested=='frontend' and 'web' not in spec['targets']:raise PermissionError('frontend requires actual web validation')

def fingerprint(spec):
    return digest({k:spec[k] for k in ('capability','dependencies','devDependencies','targets')})

def requests(db):
    """Only root requests; escalation journal keys share the prefix."""
    for key,raw in db.execute("SELECT key,value FROM records WHERE key LIKE 'platform-request:%'").fetchall():
        if key.count(':')!=1:continue
        record=json.loads(raw)
        if not isinstance(record,dict) or not {'state','task','capability','parent'}<=set(record):
            raise ValueError('invalid platform request record: '+key)
        yield key,record

def configs(files,spec):
    validate(spec,spec['capability']);result=dict(files)
    result['package.json']=apply_dependencies(files['package.json'],{k:spec[k] for k in ('dependencies','devDependencies')})
    for name in ('tsconfig.json','tsconfig.build.json'):
        cfg=json.loads(files[name]);options=cfg.setdefault('compilerOptions',{})
        cfg['include']=sorted(set(cfg.get('include',[]))|{root+'/**/*.ts' for root in spec['targets'] if name=='tsconfig.json' or root!='tests'})
        options['rootDir']='.'
        if 'web' in spec['targets']:
            cfg['include']=sorted(set(cfg['include'])|{'web/**/*.tsx'})
            options['jsx']='react-jsx'
            if 'lib' in options:options['lib']=sorted(set(options['lib'])|{'DOM','DOM.Iterable'})
        result[name]=json.dumps(cfg,indent=2)+'\n'
    return result

def request_capability(c,spec,head,planning_task):
    target=spec['capability'];key='platform-request:'+digest(dict(head=head,parent=spec['parent'],capability=target))
    prior=c.get(key)
    if prior:return prior['task']
    if target=='deployment':
        from product_environment import packet_for
        packet=packet_for(c,head,'Qualify the fixed local Compose/HTTP adapter on existing integrated source. This does not satisfy a product milestone or full release acceptance.')
        task=c.team_task(key,packet,'PLATFORM — Qualify local environment adapter',author='devops',capability='platform')
        c.put(key,dict(task=task,head=head,capability=target,parent=spec['parent'],state='REVIEW_REQUIRED'));return task
    files=c.source_files(head)
    if target not in ('backend','frontend','quality'):
        raise PermissionError('capability needs a qualified adapter registration; never create a task with an unimplemented action')
    actions=['prepare_toolchain']
    packet=dict(head=head,requested_capability=target,requested_by=planning_task,parent=spec['parent'],files={n:files[n] for n in CONFIGS},allowed_actions=actions,
        constraints='Own the missing platform capability, not product implementation. prepare_toolchain specification {capability,brief,dependencies,devDependencies,targets}; exact registry package versions, additive targets server/shared/web/tests, no shell, URLs or skipped tests. CTO reviews the immutable proposal; controller builds and validates the fixed environment. A proposal alone is not a ready capability.')
    task=c.team_task(key,packet,'PLATFORM — Enable '+target,author='devops',capability='platform')
    c.put(key,dict(task=task,head=head,capability=target,parent=spec['parent'],state='REVIEW_REQUIRED'))
    return task

def tick(c):
    from product_validation_jobs import schema
    schema(c.private)
    for key,record in requests(c.db):
        if record['state']=='READY':continue
        if record.get('prerequisite_task'):
            from product_prerequisite import resume
            resume(c,key,record);continue
        if record.get('config_task'):
            original=record['config_task'];current=original
            while c.get('superseded:'+current):current=c.get('superseded:'+current)['task']
            publications=[json.loads(r[0]) for r in c.db.execute("SELECT value FROM records WHERE key LIKE 'publication:%'")]
            merged=next((p for p in publications if p['source_task']==current and p['state']=='INTEGRATED'),None)
            if merged:
                from product_autonomy import atomic
                cfg=json.loads((c.root/'config.json').read_text());cfg.setdefault('enabled_capabilities',{})[record['capability']]=dict(adapter=CAPABILITIES[record['capability']]['adapter'],image=record['result']['image'],validated_receipt=digest(record['result']),config_commit=merged['merge'],config_sha256=digest(record['result']['configs']))
                atomic(c.root/'config.json',cfg);atomic(c.board/'product-adapter.json',cfg);c.cfg=cfg
                record.update(state='READY',commit=merged['merge']);c.put(key,record)
            continue
        task=c.escalate(record['task'],key+':escalation');answer=c.decision(task)
        if not answer or answer[1]['decision']!='approve':continue
        p,v=answer
        if p['action']=='request_prerequisite' and record['capability']=='deployment':
            from product_prerequisite import create
            create(c,key,record,p);continue
        if p['action']=='deploy_local' and record['capability']=='deployment':
            from product_deployment_jobs import proof
            receipt=proof(c.private,dict(run=v['run']),p)
            if not receipt or receipt['reviewer']!=v['reviewer'] or not receipt['passed']:raise PermissionError('executed platform environment qualification required')
            from product_autonomy import atomic
            cfg=json.loads((c.root/'config.json').read_text());cfg.setdefault('enabled_capabilities',{})['deployment']=dict(adapter='deployment',validated_receipt=digest(receipt),qualification_commit=receipt['commit'])
            atomic(c.root/'config.json',cfg);atomic(c.board/'product-adapter.json',cfg);c.cfg=cfg
            record.update(state='READY',receipt=receipt);c.put(key,record);continue
        if p['action']!='prepare_toolchain':continue
        validate(p['specification'],record['capability'])
        job='platform-'+digest(p);row=c.private.execute('SELECT result,state,error FROM product_validation_jobs WHERE id=?',(job,)).fetchone()
        if not row:
            files=c.source_files(p['head']);request=dict(approval_task=task,approval_sha=digest(p),head=p['head'],files={n:files[n] for n in CONFIGS},validation_sources=files)
            with c.private:c.private.execute('INSERT INTO product_validation_jobs VALUES(?,?,NULL,?,NULL)',(job,json.dumps(request),'QUEUED'))
            record.update(state='VALIDATING',job=job);c.put(key,record);continue
        if row[1]=='FAILED':
            if record.get('state')!='FAILED':
                record.update(state='FAILED',error=row[2],owner='devops',next_action='Diagnose fixed preparation evidence; no identical rebuild');c.put(key,record)
                packet=json.loads((c.root/'team-packets'/f'{task}.json').read_text());packet.update(preparation_error=row[2],failed_proposal_sha=digest(p))
                packet['rejected_preparations']=packet.get('rejected_preparations',[])+[fingerprint(p['specification'])]
                diagnosis=c.team_task(key+':failure:'+digest(p),packet,'PLATFORM — Diagnose preparation failure',author='devops',capability='platform');record['task']=diagnosis;c.put(key,record)
            continue
        if row[1]!='READY':continue
        result=json.loads(row[0])
        if not result.get('baseline_validation',{}).get('passed'):raise PermissionError('actual full-project validation required')
        # Keep the prepared toolchain pending until its config is integrated.
        record.update(state='VALIDATED_PENDING_CONFIG_INTEGRATION',result=result,owner='devops',next_action='Publish reviewed configuration through ordinary PR/CI/review before capability activation')
        from hermes_cli import kanban_db as kb
        from product_policy import context
        from product_workspace import Workspace
        from product_claim import NativeClaim
        files=c.source_files(p['head']);files.update(result['configs']);policy=context('platform')
        brief='Validate the exact independently reviewed platform configuration. Do not alter product behavior or tests. This configuration-only card uses baseline characterization, Green and full suite, no fabricated Red. Submit immutable delivery for CTO review and ordinary PR/CI integration. The capability is not active before integration.'
        child=kb.create_task(c.native,title='PLATFORM — Validate and publish '+record['capability']+' configuration',assignee='devops',body=brief,initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=key+':configuration:'+job)
        card=dict(policy,base=p['head'],files=files,protected=list(files),brief=brief,autonomous=True,validation_image=result['image'],tdd_contract='case-inventory-v2',tdd_mode='refactor',platform_preparation=job)
        workspace=Workspace(c.private,NativeClaim(c.board,c.cfg['attempt'],{child:card}))
        if not c.private.execute('SELECT 1 FROM product_drafts WHERE task=?',(child,)).fetchone():workspace.seed(c.cfg['attempt'],child,'devops',p['head'],files,list(files),'cto')
        c.register(child,card);kb.unblock_task(c.native,child);record['config_task']=child
        c.put(key,record)
