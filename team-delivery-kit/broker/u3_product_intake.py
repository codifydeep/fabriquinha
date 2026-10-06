"""Reviewed coverage intake and CTO classification; no implicit release or TDD waiver."""
import json,time
try:import u3_controls_execution as controls,u3_controls_intake as intake,native,handoff_runtime
except ImportError:from broker import u3_controls_execution as controls,u3_controls_intake as intake,native,handoff_runtime

def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS u3_product_intakes(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')

def saved(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='u3_product_intakes'").fetchone():return None
        row=con.execute('SELECT config,state FROM u3_product_intakes WHERE source_task=?',(controls.SOURCE,)).fetchone()
    return tuple(map(json.loads,row)) if row else None

def qualify(c,s,proof):
    history=s.get('history',[])
    if (s.get('stage')!='controls_review_approved' or s.get('delivery_approval') is not False
            or len(history)!=2 or c['cto'] in (c['author'],c['reviewer'])):
        raise ValueError('complete independent controls required')
    for i,r in enumerate(history,1):
        v=r['validation'];decision=r['decision']
        if (r['criterion']!='C0'+str(i) or r['author']!=c['author'] or r['reviewer']!=c['reviewer']
                or decision.get('action')!='approve_test_revision' or decision.get('optional_files')!=[]
                or decision.get('manifest_sha256')!=v['manifest_sha256']
                or r['seed']['manifest_sha256']!=v['manifest_sha256']
                or v['full_suite']['tests']!=259+i or v['full_suite']['exit_code']!=0
                or v['original_files_unchanged'] is not True or v['delivery_approval'] is not False):
            raise ValueError('exact independent controls receipts required')
    if (proof.get('schema')!='u3-product-coverage-probe-v1'
            or proof.get('classification')!='existing_behavior_coverage_only'
            or proof.get('controls_manifest_sha256')!=history[-1]['validation']['manifest_sha256']
            or proof.get('previous_files_unchanged') is not True or proof.get('new_code_required') is not False
            or proof.get('historical_tdd_red') is not False or proof.get('product_admission_authorized') is not False
            or proof.get('delivery_approval') is not False or proof.get('network')!='none'
            or proof.get('inputs_mount')!='readonly' or proof.get('model_calls')!=0
            or set(proof.get('new_test_sha256',{}))!={'tests/test_incremental_u3.py',*controls.FILES.values()}):
        raise ValueError('exact nonapproving product coverage proof required')
    try:from u3_product_probe import classify
    except ImportError:from broker.u3_product_probe import classify
    classify(proof['baseline'],proof['original_with_approved_tests'],proof['candidate'])
    return {'schema':'u3-product-coverage-intake-v1','root':c['plan_config']['root'],'unit':'U3',
        'controls_source':controls.SOURCE,'controls_manifest_sha256':proof['controls_manifest_sha256'],
        'probe_sha256':intake.digest(proof),'reviews':[r['review_task'] for r in history],
        'historical_tdd_red':False,'delivery_approval':False,'product_admission_authorized':False}

def paths():
    return ['/evidence/candidate/'+p for p in (*controls.SOURCES,*controls.FILES.values())]+[
        '/evidence/previous/app/static/app.js','/evidence/previous/app/static/index.html']

def register(b):
    with b.LOCK:
        c,s=controls.saved(b)
        with b.db() as con:intake.verify(con,c['plan_config']);initialize(con)
        prior=saved(b)
        if prior:return prior[1]
        with b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle coverage intake required')
            root=json.loads(con.execute('SELECT state FROM incremental_checkpoints WHERE source_task=?',
                (c['plan_config']['root'],)).fetchone()[0]);issue=root['units']['U3']['binding']['issue_id']
        base=b.issue_base(issue);seed=s['history'][-1]['seed']
        labels=b.docker('GET','/volumes/'+base['volume'])['Labels']
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.issue-id')!=issue:
            raise ValueError('exact owned original product base required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        for i,r in enumerate(s['history'],1):
            task=native.task_record(settings,r['review_task'],c['reviewer']);reads=fx.read_evidence(task)
            author=native.task_record(settings,r['seed']['task_id'],c['author'])
            expected=controls.review_paths({'step':i})
            if (author.get('status')!='completed' or task.get('status')!='completed'
                    or task.get('issue_id')!=author.get('issue_id') or fx.decision(task)!=r['decision']
                    or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in expected)):
                raise ValueError('actual independent complete reviews required')
        proof=controls.job(b,'/u3_product_probe.py',[
            dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True),
            dict(controls.owned(b,seed['snapshot'],seed['task_id']),Target='/candidate')],
            ['BASE_MANIFEST='+base['manifest_sha256'],'CONTROLS_MANIFEST='+seed['manifest_sha256']])
        certificate=qualify(c,s,proof)
        try:from incremental_provisioning import NativeIssues
        except ImportError:from broker.incremental_provisioning import NativeIssues
        issues=NativeIssues(settings);parent=issues.request('/issues/'+s['issue_id'])
        child=issues.ensure(dict(title='U3 existing-behavior coverage '+intake.digest(certificate)[:12],
            description='CTO classification gate: 255 original tests pass; original product plus three approved tests passes 261. '
                'No product bytes changed. Decide coverage-only integration versus request changes. '
                'No historical TDD Red, release, merge or deploy approval. Budget reserve 48 calls required.',
            parent_issue_id=s['issue_id'],project_id=parent.get('project_id'),stage=3,status='todo'))
        config=dict(certificate=certificate,proof=proof,base=base,seed=seed,cto=c['cto'],controls_config=c,
            issue_id=child['id'],identifier=child.get('identifier'))
        state=dict(stage='awaiting_budget',owner=c['cto'],minimum_calls=48,delivery_approval=False,
            product_admission_authorized=False,next_action='CTO readonly coverage classification after authorized budget reserve')
        with b.db() as con:
            con.execute('INSERT INTO u3_product_intakes VALUES(?,?,?)',
                (controls.SOURCE,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))
        return state

def save(b,s):
    with b.db() as con:con.execute('UPDATE u3_product_intakes SET state=? WHERE source_task=?',
        (json.dumps(s,sort_keys=True),controls.SOURCE))

def tick(b):
    entry=saved(b)
    if not entry:return
    config,s=entry
    if s['stage'] in ('blocked','coverage_classification_approved'):return
    with b.LOCK:
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        try:
            c,current=controls.saved(b)
            if qualify(c,current,config['proof'])!=config['certificate']:raise ValueError('coverage intake drift')
            with b.db() as con:intake.verify(con,c['plan_config'])
            if s['stage']=='awaiting_budget':
                if fx.remaining_calls()<s['minimum_calls']:return
                digest=config['certificate']['controls_manifest_sha256']
                note=('CTO COVERAGE CLASSIFICATION ONLY. Original product code is byte-identical to the independently '
                    'reviewed candidate. Fixed original baseline255 passed; original plus the three approved tests '
                    'and complete candidate261 both passed. Therefore this is existing behavior coverage, NOT a newly '
                    'implemented feature or historical TDD Red. Review actual files and approve this coverage-only '
                    'classification or reject with specific evidence. No writes, tools escalation, merge, deployment, '
                    'waiver of feature TDD or release approval. Optional_files=[]; exact manifest '+digest+'.\n'
                    'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+digest+'\nDELIVERY_TYPED_REVIEW_V1:'+digest+
                    '\nDELIVERY_DETERMINISTIC_READ_V1\n'+''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in paths()))
                wake=fx.ensure_planning_start(config['issue_id'],config['cto'],config['seed']['task_id'],
                    intake.digest({'certificate':config['certificate'],'note':note}),note,allow_create=True)
                s.update(stage='awaiting_cto',wakeup_id=wake['id'],at=time.time(),next_action='CTO reads original and reviewed artifacts; classification only')
                save(b,s);return
            runs=[t for t in native.issue_task_runs(settings,config['issue_id']) if t.get('wakeup_id')==s['wakeup_id'] and t.get('agent_id')==config['cto']]
            if len(runs)>1:raise ValueError('duplicate CTO classifications')
            if not runs or runs[0]['status'] in ('queued','running','dispatched'):
                if time.time()-s['at']>1800:raise TimeoutError('CTO classification deadline')
                return
            task=runs[0];decision=fx.decision(task);reads=fx.read_evidence(task)
            if (task['status']!='completed' or decision.get('action')!='approve_test_revision'
                    or decision.get('manifest_sha256')!=config['certificate']['controls_manifest_sha256']
                    or decision.get('optional_files')!=[]
                    or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p]['total_lines'] for p in paths())):
                raise ValueError('CTO rejected or incomplete coverage classification')
            s.update(stage='coverage_classification_approved',decision=decision,task_id=task['id'],
                next_action='Prepare protected coverage-only integration; original release and historical TDD hold unchanged')
            save(b,s)
        except handoff_runtime.BudgetStatusUnavailable:
            # Proxy restart is a health check, not another agent intervention.
            # Preserve the pending gate so an authorized cap update can resume it.
            return
        except Exception as error:
            s.update(stage='blocked',category=type(error).__name__,owner=config['cto'],
                next_action='CTO diagnosis required; no identical retry or implicit product approval');save(b,s)

def mounts(b,binding):
    entry=saved(b)
    if not entry:return []
    c,s=entry
    if s['stage']!='awaiting_cto' or binding['issue_id']!=c['issue_id'] or binding['agent_id']!=c['cto']:return []
    with b.db() as con:r=con.execute('SELECT task_id FROM native_bindings WHERE request_id=?',(binding['request_id'],)).fetchone()
    t=native.task_record(json.loads((b.STATE/'native.json').read_text()),r['task_id'],c['cto'])
    if t.get('wakeup_id')!=s['wakeup_id']:raise ValueError('exact CTO coverage wake required')
    labels=b.docker('GET','/volumes/'+c['base']['volume'])['Labels']
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.issue-id')!=c['base']['issue_id']:
        raise ValueError('original base ownership drift')
    return [dict(controls.owned(b,c['seed']['snapshot'],c['seed']['task_id']),Target='/evidence/candidate'),
        dict(Type='volume',Source=c['base']['volume'],Target='/evidence/previous',ReadOnly=True)]
