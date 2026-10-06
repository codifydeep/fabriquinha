"""Create a new isolated trial only; never reads or modifies production boards."""
import json,os
from pathlib import Path
from hermes_cli import kanban_db as kb

root=Path(os.environ['PRODUCT_TRIAL_ROOT']).resolve(strict=True)
board=root/'board';control=root/'control';snapshots=root/'snapshots'
if (control/'config.json').exists():raise RuntimeError('trial already registered; refusing reset')
for path in (board,control,snapshots,root/'socket'):path.mkdir(exist_ok=True)
kb.init_db(board/'kanban.db');db=kb.connect(board/'kanban.db')
task=kb.create_task(db,title='ADAPTER-TRIAL: capacity predicate with immutable independent review',
    assignee='backend_data',initial_status='blocked',workspace_kind='scratch')
brief='''Isolated fixture, not Truco. Implement exported capacity(n) in src/app.mjs: true only for integer n with 0<n<2. Add Node built-in tests using node:test and node:assert/strict. Preserve tests/regression.test.mjs. On first submission test n=2 and n=1, but leave n=0 coverage for reviewer feedback. Reviewer must request zero-player coverage on the first revision, then independently validate and approve the corrected second revision. Author must run actual Red, Green and suite using product_test. No dependency downloads, shell or external services. Do not declare release homologation.'''
cards={task:dict(author='backend_data',reviewer='techlead',base='0'*40,brief=brief,
    files={'src/app.mjs':'export const capacity = n => true;','tests/regression.test.mjs':"import {test} from 'node:test';import assert from 'node:assert/strict';test('existing arithmetic',()=>assert.equal(1+1,2));"},
    protected=['tests/regression.test.mjs'])}
attempt='product-adapter-agent-trial-01'
(board/'product-adapter.json').write_text(json.dumps(dict(attempt=attempt,cards=cards)))
(control/'config.json').write_text(json.dumps(dict(attempt=attempt,cards=cards,board=str(board),snapshot_root=str(snapshots),
    image='sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293')))
db.close()
print(json.dumps(dict(prepared=True,task=task,attempt=attempt,status='blocked',product_enabled=False)))
