"""Real native Kanban + product handlers/outbox; test runner stub, no LLM."""
import hashlib
import sqlite3
import tempfile
import os
from pathlib import Path
from hermes_cli import kanban_db as kb
from product_claim import NativeClaim
from product_workspace import Workspace
from product_tdd import TDD
from product_controller import ProductController
from product_handoff import deliver
from product_verdict import deliver_verdict


def runner(files, image):
    red = files['src/app.mjs'] == 'red'
    return dict(image=image, snapshot={n: hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()},
                exit_code=1 if red else 0, output='# tests 1\n# fail ' + ('1\nERR_ASSERTION' if red else '0\n'))


REAL = os.environ.get('PRODUCT_DOCKER_TRIAL_ROOT')
IMAGE = 'sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293' if REAL else 'sha256:'+'b'*64
source_red = 'export const capacity = n => true;' if REAL else 'red'
source_green = 'export const capacity = n => n < 2;' if REAL else 'green'
test_source = "import {test} from 'node:test';import assert from 'node:assert/strict';import {capacity} from '../src/app.mjs';test('capacity',()=>assert.equal(capacity(2),false));" if REAL else 'assert'
if REAL:
    from product_docker_runner import DockerRunner
    runner = DockerRunner(REAL)
with tempfile.TemporaryDirectory(prefix='product-handoff-', dir=REAL) as tmp:
    board = Path(tmp); kb.init_db(board/'kanban.db'); native = kb.connect(board/'kanban.db')
    tid = kb.create_task(native, title='Disposable product handoff', assignee='backend_data', initial_status='blocked', workspace_kind='scratch')
    kb.unblock_task(native, tid); author = kb.claim_task(native, tid, claimer='probe')
    binding = NativeClaim(board, 'trial', {tid: dict(author='backend_data', reviewer='techlead')})
    private = sqlite3.connect(board/'private.db')
    w = Workspace(private, binding); w.seed('trial', tid, 'backend_data', 'a'*40, {'src/app.mjs':source_red,'tests/app.test.mjs':test_source}, ['tests/app.test.mjs'])
    c = ProductController(w, TDD(w, IMAGE), runner)
    req = dict(attempt='trial', task=tid, run=author.current_run_id, claim=author.claim_lock)
    def call(op, **kw): return c.handle(dict(req, operation='product_'+op, **kw))
    try: call('submit', version=0)
    except PermissionError: pass
    else: raise AssertionError('missing suite accepted')
    call('test', phase='red'); draft=call('read')
    call('edit',version=0,sha256=draft['sha256'],replacements={'src/app.mjs':source_green})
    call('test',phase='green');call('test',phase='suite')
    envelope=call('submit',version=1)
    private.close()
    private=sqlite3.connect(board/'private.db');w=Workspace(private,binding)
    c=ProductController(w,TDD(w,IMAGE),runner)
    # Fail AFTER native transition, BEFORE the private acknowledgement commit.
    private.execute("CREATE TRIGGER interrupted_ack BEFORE UPDATE ON product_handoffs BEGIN SELECT RAISE(ABORT,'simulated restart'); END")
    try: deliver(c,native,envelope)
    except sqlite3.IntegrityError: pass
    else: raise AssertionError('injected failure not exercised')
    private.execute('DROP TRIGGER interrupted_ack');private.commit();private.close()
    private=sqlite3.connect(board/'private.db');w=Workspace(private,binding)
    c=ProductController(w,TDD(w,IMAGE),runner)
    assert deliver(c,native,envelope)['recovered']
    assert native.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='review_requested'",(tid,)).fetchone()[0]==1
    review=kb.claim_review_task(native,tid,claimer='review-probe')
    req.update(run=review.current_run_id,claim=review.claim_lock)
    assert call('inspect',revision=envelope['revision'])['src/app.mjs']==source_green
    validated=call('review_test',revision=envelope['revision'])
    assert validated['passed'] and not validated['approved']
    assert validated==call('review_test',revision=envelope['revision'])
    try:call('test',phase='red')
    except PermissionError:pass
    else:raise AssertionError('reviewer reran Red')
    changes=call('verdict',revision=envelope['revision'],decision='request_changes',reason='Reject zero players: add acceptance coverage without weakening existing tests.')
    assert deliver_verdict(c,native,changes)['decision']=='request_changes'
    assert deliver_verdict(c,native,changes)['recovered']
    task=native.execute('SELECT assignee,status FROM tasks WHERE id=?',(tid,)).fetchone()
    assert task['assignee']=='backend_data' and task['status']=='ready'
    author2=kb.claim_task(native,tid,claimer='rework-probe')
    req.update(run=author2.current_run_id,claim=author2.claim_lock)
    draft=call('read')
    extra="import {test} from 'node:test';import assert from 'node:assert/strict';import {capacity} from '../src/app.mjs';test('zero players',()=>assert.equal(capacity(0),false));" if REAL else 'new assertion'
    changeset={'tests/zero.test.mjs':extra}
    if not REAL: changeset['src/app.mjs']='red'
    edited=call('edit',version=draft['version'],sha256=draft['sha256'],replacements=changeset)
    assert call('test',phase='red')['accepted']
    call('edit',version=edited['version'],sha256=edited['sha256'],replacements={'src/app.mjs':'export const capacity = n => n > 0 && n < 2;' if REAL else 'green'})
    assert call('test',phase='green')['accepted'];assert call('test',phase='suite')['accepted']
    second=call('submit',version=call('read')['version']);assert second['revision']!=envelope['revision']
    deliver(c,native,second)
    review2=kb.claim_review_task(native,tid,claimer='second-review')
    req.update(run=review2.current_run_id,claim=review2.claim_lock)
    for revision in (envelope['revision'],second['revision']):
        try:call('verdict',revision=revision,decision='approve',reason='Attempt before exact independent validation.')
        except PermissionError:pass
        else:raise AssertionError('obsolete or unvalidated approval accepted')
    assert call('review_test',revision=second['revision'])['passed']
    approval=call('verdict',revision=second['revision'],decision='approve',reason='Existing and zero-player acceptance tests pass on the exact immutable revision.')
    private.execute("CREATE TRIGGER interrupt_verdict BEFORE UPDATE ON product_verdicts BEGIN SELECT RAISE(ABORT,'restart'); END")
    try:deliver_verdict(c,native,approval)
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('verdict interruption not exercised')
    private.execute('DROP TRIGGER interrupt_verdict');private.commit();private.close()
    private=sqlite3.connect(board/'private.db');w=Workspace(private,binding);c=ProductController(w,TDD(w,IMAGE),runner)
    assert deliver_verdict(c,native,approval)['recovered']
    assert native.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()[0]=='done'
    assert native.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='completed'",(tid,)).fetchone()[0]==1
    assert private.execute('SELECT count(*) FROM product_submissions').fetchone()[0]==2
    from product_worker_service import WorkerService
    from coordination_store import CoordinationStore
    service=WorkerService(w,TDD(w,IMAGE),runner,native)
    service.recover()
    ledger=CoordinationStore(board/'notifications.db');ledger.create_attempt('trial','disposable','v0.0')
    service.export_notifications(ledger)
    pending=ledger.pending('trial');assert len(pending)==4
    service.export_notifications(ledger);assert ledger.pending('trial')==pending
    # Lost local acknowledgement repeats the ledger key, never a new event.
    private.execute('UPDATE product_notifications SET sent=0');private.commit()
    service.export_notifications(ledger);assert ledger.pending('trial')==pending
    ledger.close()
    private.close();native.close()
print('PASS native handoff, TDD, changes request, original author rework, stale approval rejection, exact independent approval and restart recovery. Docker runner='+str(bool(REAL))+'. No agent E2E certification.')
