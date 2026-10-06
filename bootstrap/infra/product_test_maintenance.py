"""Exact-diff, independently reviewed maintenance. No author-side unfreezing."""
import json,re
from product_workspace import digest,validate_files
from product_recovery import is_test
from product_case_inventory import inventory,compare

FIELDS={'target_task','draft_sha256','brief','replacements','renames','case_mapping','contract_sources','change_kind'}

def proposed_files(packet,spec,files):
    if not isinstance(spec,dict) or set(spec) not in (FIELDS,FIELDS|{'remove_empty'}):raise ValueError('exact test-maintenance specification required')
    if spec['target_task']!=packet['target_task'] or spec['draft_sha256']!=packet['draft_sha256'] or digest(files)!=spec['draft_sha256']:raise PermissionError('stale maintenance target')
    if spec['change_kind'] not in ('coverage_extension','technical_refactor','fixture_correction','align_approved_contract'):raise PermissionError('business-contract changes need scoped product approval')
    if not isinstance(spec['brief'],str) or not 100<=len(spec['brief'])<=8000:raise ValueError('technical rationale required')
    if not isinstance(spec['contract_sources'],list) or not spec['contract_sources'] or any(not isinstance(v,str) for v in spec['contract_sources']) or not set(spec['contract_sources'])<=set(packet['allowed_contract_sources']):raise PermissionError('registered contract references required')
    replacements=spec['replacements'];renames=spec['renames']
    if not isinstance(replacements,dict) or not 1<=len(replacements)<=8 or not isinstance(renames,dict) or not isinstance(spec['case_mapping'],dict):raise ValueError('bounded test diff required')
    if any(not is_test(p) or not isinstance(v,str) or not v.strip() for p,v in replacements.items()):raise PermissionError('nonempty tests only')
    if any(not isinstance(a,str) or not isinstance(b,str) or not is_test(a) or not is_test(b) or a not in files or b in files or b not in replacements or a==b for a,b in renames.items()):raise PermissionError('registered collision-free test renames only: {old_path: new_path}, strings only')
    if len(set(renames.values()))!=len(renames):raise PermissionError('rename collision')
    if any(re.search(r'\b(?:skip|only|todo|xit|xdescribe)\s*[.(]',v) for v in replacements.values()):raise PermissionError('ignored or focused tests forbidden')
    updated=dict(files);updated.update(replacements)
    removed=spec.get('remove_empty',[])
    if not isinstance(removed,list) or any(not isinstance(p,str) for p in removed) or len(set(removed))!=len(removed) or any(p not in packet.get('removable_empty_artifacts',[]) or p not in files or files[p].strip() or p in replacements or p in renames for p in removed):raise PermissionError('only controller-verified new empty artifacts may be removed')
    for path in removed:del updated[path]
    for old in renames:del updated[old]
    validate_files(updated)
    if updated==files:raise ValueError('maintenance has no diff')
    return updated

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS test_maintenance_validation(proposal_sha TEXT,review_run INTEGER,receipt TEXT,PRIMARY KEY(proposal_sha,review_run))')
    db.execute('CREATE TABLE IF NOT EXISTS test_maintenance_applied(proposal_sha TEXT PRIMARY KEY,attempt TEXT,task TEXT,before_version INTEGER,before_files TEXT,before_protected TEXT,after_sha TEXT,receipt TEXT)')
    db.commit()

def validate_proposal(db,who,proposal,packet,runner):
    schema(db);sha=digest(proposal)
    prior=db.execute('SELECT receipt FROM test_maintenance_validation WHERE proposal_sha=? AND review_run=?',(sha,who['run'])).fetchone()
    if prior:return json.loads(prior[0])
    spec=proposal['specification']
    row=db.execute('SELECT files FROM product_drafts WHERE attempt=? AND task=?',(who['attempt'],spec['target_task'])).fetchone()
    if not row:raise PermissionError('preserved draft required')
    before=json.loads(row[0]);after=proposed_files(packet,spec,before)
    image=packet['validation_image']
    # Removing a proved new zero-byte artifact removes no historical test case.
    # The exact original snapshot is still archived; the full original case set
    # must execute green before any assertion-changing maintenance is accepted.
    baseline={n:v for n,v in before.items() if n not in spec.get('remove_empty',[])}
    results=[runner(files,image) for files in (baseline,after)]
    import hashlib
    for files,result in zip((baseline,after),results):
        if result.get('image')!=image or result.get('snapshot')!={n:hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()}:raise PermissionError('validation source mismatch')
    from product_case_inventory import diagnostics
    if results[0]['exit_code']!=0:
        error=PermissionError('maintenance baseline failed; inspect structured evidence, never infer the cause')
        error.diagnostic=dict(phase='maintenance_baseline',**diagnostics(results[0]));raise error
    old,new=map(inventory,results)
    coverage=compare(old,new,spec['case_mapping'],spec['renames'])
    if results[0]['exit_code']!=0 or any(c['status']!='passed' for c in old.values()):raise PermissionError('maintenance baseline must be green; diagnose existing failure first')
    failures=[k for k,c in new.items() if c['status']=='failed']
    if results[1]['exit_code'] not in (0,1) or (results[1]['exit_code']==1 and not failures):raise PermissionError('maintenance exposed infrastructure failure, not behavioral Red')
    if any(new[k]['path'] not in spec['replacements'] or not new[k]['assertion_failure'] for k in failures):raise PermissionError('unexpected baseline regression outside proposed test changes')
    receipt=dict(proposal_sha256=sha,review_run=who['run'],reviewer=who['profile'],target=spec['target_task'],image=image,
        before_sha256=digest(before),baseline_sha256=digest(baseline),removed_empty_artifacts=spec.get('remove_empty',[]),after_sha256=digest(after),before_cases=old,after_cases=new,coverage=coverage,
        observed_red_cases=failures,phase='test_maintenance_validation_not_implementation_tdd',semantics_require_independent_review=True)
    with db:db.execute('INSERT INTO test_maintenance_validation VALUES(?,?,?)',(sha,who['run'],json.dumps(receipt)))
    return receipt

def apply(coordinator,task,card,proposal,verdict,incident):
    db=coordinator.private;schema(db);sha=digest(proposal)
    proof=db.execute('SELECT receipt FROM test_maintenance_validation WHERE proposal_sha=? AND review_run=?',(sha,verdict['run'])).fetchone()
    if not proof:raise PermissionError('independent before/after execution required')
    receipt=json.loads(proof[0]);spec=proposal['specification']
    if verdict['decision']!='approve' or verdict['proposal_sha256']!=sha or receipt['reviewer']!=verdict['reviewer'] or proposal['author']==verdict['reviewer']:raise PermissionError('exact independent maintenance approval required')
    row=db.execute('SELECT version,files,protected FROM product_drafts WHERE attempt=? AND task=?',(coordinator.cfg['attempt'],task)).fetchone()
    if not row:raise PermissionError('maintenance target missing')
    files=json.loads(row[1]);prior=db.execute('SELECT after_sha FROM test_maintenance_applied WHERE proposal_sha=?',(sha,)).fetchone()
    if not prior:
        packet=json.loads((coordinator.root/'team-packets'/f'{incident}.json').read_text())
        updated=proposed_files(packet,spec,files)
        if digest(updated)!=receipt['after_sha256']:raise PermissionError('maintenance differs from validated diff')
        protected=json.loads(row[2]);protected.update(spec['replacements'])
        for old in spec['renames']:protected.pop(old,None)
        with db:
            changed=db.execute('UPDATE product_drafts SET version=version+1,files=?,protected=? WHERE attempt=? AND task=? AND version=? AND files=?',(json.dumps(updated),json.dumps(protected),coordinator.cfg['attempt'],task,row[0],row[1]))
            if changed.rowcount!=1:raise PermissionError('maintenance concurrent draft mutation')
            db.execute('INSERT INTO test_maintenance_applied VALUES(?,?,?,?,?,?,?,?)',(sha,coordinator.cfg['attempt'],task,row[0],row[1],row[2],digest(updated),json.dumps(dict(proposal=proposal,verdict=verdict,validation=receipt))))
    elif digest(files)!=prior[0]:raise PermissionError('maintenance applied draft drift')
    changed=dict(card,removable_empty_artifacts=sorted(set(card.get('removable_empty_artifacts',[]))|set(spec.get('remove_empty',[]))),reviewed_test_maintenance=dict(proposal_sha256=sha,incident=incident,paths=list(spec['replacements']),renames=spec['renames'],case_mapping=spec['case_mapping']))
    coordinator.register(task,changed)
    return changed
