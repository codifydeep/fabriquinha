"""Disposable prototype integration; no native workers, GitHub or product release."""
import json,sqlite3,tempfile
from pathlib import Path
from product_workspace import Workspace
from product_test_sandbox import run
from product_tdd import TDD

IMAGE='sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293'
with tempfile.TemporaryDirectory(prefix='truco-adapter-workspace-') as folder:
    root=Path(folder);db=sqlite3.connect(root/'private.db')
    current=dict(attempt='isolated-adapter-probe',task='t_probe',run=1,claim='operator-fixture',profile='backend_data',mode='implementation')
    request={k:current[k] for k in ('attempt','task','run','claim')}
    w=Workspace(db,lambda request:current)
    baseline="import {test} from 'node:test';import assert from 'node:assert/strict';test('existing regression',()=>assert.equal(1+1,2));"
    test="import {test} from 'node:test';import assert from 'node:assert/strict';import {capacity} from '../src/app.mjs';test('new acceptance',()=>assert.equal(capacity(2),false));"
    w.seed(current['attempt'],current['task'],'backend_data','a'*40,{'src/app.mjs':'export const capacity = n => true;','tests/existing.test.mjs':baseline},['tests/existing.test.mjs'])
    d=w.read_draft(request);w.edit(request,d['version'],d['sha256'],{'tests/capacity.test.mjs':test})
    def execute(label):
        draft=w.read_draft(request);directory=root/label;directory.mkdir()
        for name,content in draft['files'].items():
            path=directory/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
        return run(directory,IMAGE,label+'-workspace-probe')
    tdd=TDD(w,IMAGE)
    red=tdd.execute(request,'red',lambda files,image:execute('red'));assert red['accepted'] and red['exit_code']==1
    d=w.read_draft(request);w.edit(request,d['version'],d['sha256'],{'src/app.mjs':'export const capacity = n => n < 2;'})
    green=tdd.execute(request,'green',lambda files,image:execute('green'));assert green['accepted'] and '# tests 2' in green['output']
    suite=tdd.execute(request,'suite',lambda files,image:execute('suite'));assert suite['accepted']
    assert red['tests_sha256']==green['tests_sha256']==suite['tests_sha256']
    final=w.read_draft(request);receipt=w.freeze(request,final['version'])
    db.close();db=sqlite3.connect(root/'private.db');w=Workspace(db,lambda request:current)
    assert TDD(w,IMAGE).submission_evidence(request)==suite
    current.update(mode='review',profile='techlead')
    assert w.inspect(request,receipt['revision'])['tests/existing.test.mjs']==baseline
    try:w.edit(request,final['version'],final['sha256'],{'src/app.mjs':'tampered'})
    except PermissionError:pass
    else:raise AssertionError('review write accepted')
    print(json.dumps(dict(passed=True,scope='workspace_and_node_sandbox_prototype',red_exit=red['exit_code'],green_exit=green['exit_code'],
        red_log_sha256=red['log_sha256'],green_log_sha256=green['log_sha256'],snapshot_revision=receipt['revision'],
        tests_identical=True,restart_preserved_snapshot=True,review_write_denied=True,native_claim_binding=False,
        durable_tdd_receipts=True,agent_e2e_validated=False,product_released=False),indent=2))
    db.close()
