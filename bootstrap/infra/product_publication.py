"""Read-only Node publication gate. Never converts snapshot review to PR approval."""
import json
from product_workspace import digest,validate_files

PREFIX='adapter-node/'
BASE_BRANCH='codex/adapter-node-base-20260918'
HEAD_BRANCH='codex/adapter-node-build-20260918'

def approved_packet(private,native,attempt,task):
    row=private.execute('SELECT run,version,revision,envelope,state FROM product_handoffs WHERE attempt=? AND task=? ORDER BY rowid DESC LIMIT 1',(attempt,task)).fetchone()
    if not row or row[4]!='DELIVERED':raise PermissionError('latest delivery required')
    run,version,revision,raw,_=row;delivery=json.loads(raw)
    stored=private.execute('SELECT files FROM product_submissions WHERE attempt=? AND task=? AND run=? AND version=? AND revision=?',(attempt,task,run,version,revision)).fetchone()
    if not stored:raise PermissionError('snapshot missing')
    files=json.loads(stored[0]);validate_files(files)
    if digest(dict(attempt=attempt,task=task,run=run,base=delivery['base'],files=files))!=revision:
        raise PermissionError('snapshot hash mismatch')
    suite=delivery['suite']
    if digest(suite)!=delivery['evidence_sha256'] or not suite['accepted'] or suite['source_sha256']!=digest(files):
        raise PermissionError('suite mismatch')
    decision=private.execute('SELECT envelope,state FROM product_verdicts WHERE attempt=? AND task=? ORDER BY rowid DESC LIMIT 1',(attempt,task)).fetchone()
    if not decision or decision[1]!='DELIVERED':raise PermissionError('delivered verdict required')
    verdict=json.loads(decision[0])
    if verdict['decision']!='approve' or verdict['revision']!=revision or verdict['author']==verdict['reviewer']:
        raise PermissionError('independent exact-revision approval required')
    proof=private.execute('SELECT receipt FROM product_review_tests WHERE attempt=? AND task=? AND revision=? AND review_run=?',
                          (attempt,task,revision,verdict['review_run'])).fetchone()
    if not proof:raise PermissionError('review test missing')
    review=json.loads(proof[0])
    if not review['passed'] or digest(review)!=verdict['validation_sha256'] or review['source_sha256']!=digest(files) or review['image']!=suite['image']:
        raise PermissionError('review validation mismatch')
    native_task=native.execute('SELECT status FROM tasks WHERE id=?',(task,)).fetchone()
    closed=native.execute('SELECT outcome,summary FROM task_runs WHERE id=? AND task_id=?',(verdict['review_run'],task)).fetchone()
    expected='product-verdict:'+digest(verdict)+'\n'+verdict['reason']
    if not native_task or native_task[0]!='done' or not closed or tuple(closed)!=('completed',expected):
        raise PermissionError('native completion mismatch')
    return dict(attempt=attempt,task=task,revision=revision,files=files,image=suite['image'],
                author=verdict['author'],reviewer=verdict['reviewer'],review_run=verdict['review_run'],
                evidence_sha256=delivery['evidence_sha256'],validation_sha256=verdict['validation_sha256'],
                base_branch=BASE_BRANCH,head_branch=HEAD_BRANCH,pr_approved=False,release_homologated=False)

def verify_publication(packet,files):
    expected={PREFIX+name:value for name,value in packet['files'].items()}
    if files!=expected:raise PermissionError('published files diverge from approved snapshot')
    return dict(snapshot_verified=True,revision=packet['revision'],pr_approved=False)
