"""Native disposable Kanban claims; no production board, model or GitHub calls."""
import sqlite3,tempfile
from pathlib import Path
from hermes_cli import kanban_db as kb
from product_claim import NativeClaim
from product_workspace import Workspace

with tempfile.TemporaryDirectory(prefix='native-product-claim-') as tmp:
    board=Path(tmp);kb.init_db(board/'kanban.db');db=kb.connect(board/'kanban.db')
    tid=kb.create_task(db,title='Adapter isolated native claim',assignee='backend_data',initial_status='blocked',workspace_kind='scratch')
    kb.unblock_task(db,tid);author=kb.claim_task(db,tid,claimer='adapter-probe');assert author
    binding=NativeClaim(board,'native-product-probe',{tid:dict(author='backend_data',reviewer='techlead')})
    req=dict(attempt='native-product-probe',task=tid,run=author.current_run_id,claim=author.claim_lock)
    private=sqlite3.connect(board/'private.db');w=Workspace(private,binding)
    w.seed(req['attempt'],tid,'backend_data','a'*40,{'src/app.mjs':'source'},[])
    assert binding(dict(req,mode='review',profile='cto'))['mode']=='implementation'
    d=w.read_draft(req);w.edit(req,d['version'],d['sha256'],{'src/app.mjs':'changed'})
    snapshot=w.freeze(req,1)
    for bad in (dict(req,claim='forged'),dict(req,run=req['run']+1),dict(req,attempt='other')):
        try:w.read_draft(bad)
        except PermissionError:pass
        else:raise AssertionError('forged identity accepted')
    assert kb.request_review(db,tid,reviewer='techlead',expected_run_id=author.current_run_id)
    try:w.read_draft(req)
    except PermissionError:pass
    else:raise AssertionError('completed author claim accepted')
    review=kb.claim_review_task(db,tid,claimer='independent');assert review
    reviewer=dict(req,run=review.current_run_id,claim=review.claim_lock)
    assert binding(reviewer)['mode']=='review'
    assert w.inspect(reviewer,snapshot['revision'])['src/app.mjs']=='changed'
    try:w.edit(reviewer,1,d['sha256'],{'src/app.mjs':'overwrite'})
    except PermissionError:pass
    else:raise AssertionError('reviewer write accepted')
    (board/'MAINTENANCE').write_text('probe')
    try:w.inspect(reviewer,snapshot['revision'])
    except PermissionError:pass
    else:raise AssertionError('maintenance ignored')
    private.close();db.close()
print('PASS native Hermes author/review claims, stale and forged identity denial, reviewer write denial, maintenance fence. No agent E2E certification.')
