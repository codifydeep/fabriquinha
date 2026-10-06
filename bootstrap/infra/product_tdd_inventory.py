"""Case-level TDD gate, opt-in for newly registered contracts only."""
import json,hashlib
from product_case_inventory import inventory,compare
from product_workspace import digest

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS tdd_baselines(attempt TEXT,task TEXT,base TEXT,image TEXT,receipt TEXT,PRIMARY KEY(attempt,task,base,image))');db.commit()

def baseline(tdd,current,card,runner):
    image=card.get('baseline_image',tdd.image)
    schema(tdd.db);key=(current['attempt'],current['task'],card['base'],image)
    prior=tdd.db.execute('SELECT receipt FROM tdd_baselines WHERE attempt=? AND task=? AND base=? AND image=?',key).fetchone()
    if prior:return json.loads(prior[0])
    files=card.get('baseline_files',card['files']);result=runner(files,image)
    if result.get('image')!=image or result.get('snapshot')!={n:hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()}:raise PermissionError('baseline provenance mismatch')
    cases=inventory(result);failures=[k for k,v in cases.items() if v['status']=='failed']
    bug=card.get('tdd_mode')=='bugfix'
    if result['exit_code'] not in ((0,1) if bug else (0,)) or (failures and (not bug or any(not cases[k]['assertion_failure'] for k in failures))):raise PermissionError('baseline is not green or a registered behavioral bug reproduction')
    if result['exit_code']==1 and not failures:raise PermissionError('baseline infrastructure failure')
    receipt=dict(base=card['base'],image=image,source_sha256=digest(files),cases=cases,failed_cases=failures,log_sha256=hashlib.sha256(result['output'].encode()).hexdigest())
    with tdd.db:tdd.db.execute('INSERT INTO tdd_baselines VALUES(?,?,?,?,?)',(*key,json.dumps(receipt)))
    return receipt

def evaluate(card,base,result,phase,files,maintenance=None):
    cases=inventory(result);approved=card.get('reviewed_test_maintenance',{})
    coverage=compare(base['cases'],cases,approved.get('case_mapping',{}),approved.get('renames',{}))
    failed=[k for k,v in cases.items() if v['status']=='failed']
    if card.get('tdd_mode')=='revalidation' and (not card.get('base_update_source') or files!=card['files'] or phase=='red'):
        raise PermissionError('base update only revalidates the exact deterministic merge with original TDD provenance')
    allowed=set(coverage['new_cases'])
    if card.get('tdd_mode')=='bugfix':allowed.update(base['failed_cases'])
    if maintenance:allowed.update(maintenance.get('observed_red_cases',[]))
    if phase=='red' and (not failed or any(k not in allowed or not cases[k]['assertion_failure'] for k in failed)):
        raise PermissionError('Red must fail new/approved behavior only, not unchanged baseline or infrastructure')
    if card.get('tdd_mode')=='refactor':
        if phase=='red':raise PermissionError('pure refactor uses characterization and green before/after, no artificial Red')
        from product_tdd import test_files
        if test_files(files)!=test_files(card['files']):raise PermissionError('refactor cannot alter characterization tests without a separately reviewed maintenance contract')
    return dict(baseline_sha256=digest(base),cases=cases,coverage=coverage,failed_cases=failed,semantic_relevance_requires_independent_review=True)
