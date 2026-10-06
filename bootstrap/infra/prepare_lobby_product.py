"""One-time materialization of the reviewed product graph, not another rehearsal."""
import hashlib,json,os,re,shutil,sqlite3,time
from pathlib import Path
from hermes_cli import kanban_db as kb
from product_graph import audit

DATA=Path('/opt/data'); CONTROL=Path('/control')
SLUG='truco-online-lobby-20260918'; ATTEMPT='truco-restart-20260911'
BASE='af8999b849f7c5e43b7c5179073d08c3f34a33bd'
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def main():
    state=json.loads((DATA/'governance/execution.json').read_text())
    if (CONTROL/'config.json').exists():raise RuntimeError('Already prepared; do not reset')
    assert state['attempt']==ATTEMPT
    assert state['publication_integrations'][-1]['merge_commit']==BASE
    old=DATA/'kanban/boards'/state['board']/'kanban.db'
    with sqlite3.connect(old) as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    with sqlite3.connect(DATA/'governance/coordination.db') as db:
        approval=json.loads(db.execute("SELECT data FROM records WHERE attempt=? AND kind='brief' AND id='approved'",(ATTEMPT,)).fetchone()[0])
    assert approval['actor']=='ceo' and approval['brief_sha256']==state['brief_sha256']
    approved=DATA/'governance/approved-briefs'/state['brief_sha256']/'brief.md'
    assert hashlib.sha256(approved.read_bytes()).hexdigest()==state['brief_sha256']
    plan=Path('/deliveries')/ATTEMPT/'t_2d0009c2/b06e5378587a687c018376493621bd399447edd3f3fca7dc35b9807e0d66a403/files/PLAN.md'
    content=plan.read_text();graph=audit(content)
    backup=DATA/'governance'/('lobby-resume-backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    shutil.copy2(DATA/'governance/execution.json',backup/'execution.json')
    with sqlite3.connect(old) as src,sqlite3.connect(backup/'planning-board.db') as dst:
        src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    kb.create_board(SLUG,name='Truco v0.1 — Lobby real',description='Controlled product implementation, not a rehearsal. Snapshot review does not mean PR integration or homologation.')
    board=DATA/'kanban/boards'/SLUG;db=kb.connect(board/'kanban.db')
    (board/'MAINTENANCE').write_text('Preparing scoped product controller; no generic dispatch.\n')
    ids={}
    for layer in graph['topological_layers']:
        for key in layer:
            item=graph['nodes'][key]
            line=next(line for line in content.splitlines() if line.startswith('- **'+key+'**'))
            ids[key]=kb.create_task(db,title=key+' — '+line.split(' — ',1)[1].split(' | ')[0],
                body=line+'\nOriginal approved plan; blocked until runtime and integrated dependencies qualify. Never claim done from snapshot approval alone.',
                assignee=item['owner'],initial_status='blocked',parents=[ids[k] for k in item['parents']],
                max_runtime_seconds=1200,max_retries=0,idempotency_key=ATTEMPT+':lobby:'+key,
                skills=['karpathy-guidelines'])
    release=kb.create_task(db,title='RELEASE-v0.1 — Full Truco Paulista + 3D (sentinel, not executable)',
        body='CEO-approved brief '+state['brief_sha256']+'; all V01-01..10 required. Lobby is intermediate. No automatic worker. Only full evidence may transition to HOMOLOGADA.',
        assignee='techlead',initial_status='blocked',idempotency_key=ATTEMPT+':release-sentinel')
    brief=('REAL PRODUCT: TDD-01A is the incremental Fastify/TypeScript backend foundation of TDD-01. '
        'Implement server/app.ts exporting buildApp(), returning a Fastify instance with GET /health returning HTTP 200 and JSON {status:"ok"}. '
        'No listen() side effects on import; callers own ready/close. Keep unknown routes returning 404. '
        'Use Vitest in tests/*.test.ts, Fastify.inject(), and close instances. First add the new health test and execute product_test red; '
        'the current app deliberately lacks the health route. Then minimally implement, execute green and suite, and submit. '
        'No node:test; trusted runner runs TypeScript strict checking and ALL Vitest tests. Dependencies are preinstalled, no shell/downloads. '
        'Preserve tests/regression.test.ts and package.json. Do not implement sessions/rooms/database/frontend in this card. '
        'Reviewer techlead inspects the immutable source and runs validation before approving or requesting changes. '
        'On rework, read preserved draft and review feedback; do not recreate an already passing baseline. '
        'This is actual reusable server code, not a fixture. Snapshot approval does not finish TDD-01: Compose/Postgres/migrate, PR/CI/integration remain required. '
        'No further generic rehearsals; technical questions go to Tech Lead/CTO, not CEO.')
    first=kb.create_task(db,title='TDD-01A — Real Fastify backend health foundation',body=brief,
        assignee='backend_data',initial_status='blocked',max_runtime_seconds=1200,max_retries=0,
        skills=['karpathy-guidelines'],idempotency_key=ATTEMPT+':lobby:TDD-01A')
    files={
        'package.json':'{"name":"truco-online","private":true,"type":"module"}\n',
        'server/app.ts':'import Fastify from "fastify";\nexport function buildApp() { return Fastify(); }\n',
        'tests/regression.test.ts':'import {test,expect} from "vitest";\nimport {buildApp} from "../server/app.js";\ntest("unknown routes stay 404", async()=>{const app=buildApp();try{const r=await app.inject({method:"GET",url:"/not-a-route"});expect(r.statusCode).toBe(404);}finally{await app.close();}});\n',
    }
    cards={first:dict(author='backend_data',reviewer='techlead',base=BASE,brief=brief,files=files,
                     protected=['package.json','tests/regression.test.ts'],parent_work_item=ids['TDD-01'])}
    config=dict(scope='truco-lobby',attempt=ATTEMPT,release='v0.1',cards=cards,
        board='/board',snapshot_root=os.environ['LOBBY_SNAPSHOT_ROOT'],image=os.environ['LOBBY_TOOLCHAIN_IMAGE'],runner='lobby-ts')
    save(CONTROL/'config.json',config);save(board/'product-adapter.json',config)
    save(board/'product-roadmap.json',dict(attempt=ATTEMPT,brief_sha256=state['brief_sha256'],base=BASE,
        nodes=ids,first=first,release=release,graph=graph,gate='only TDD-01A enabled; other nodes await integrated prerequisites',
        product_pr_target='release/v0.1',max_workers=2,max_per_profile=1))
    shutil.copy2(plan,board/'approved-plan.md');shutil.copy2(approved,board/'approved-brief.md')
    state.update(phase='CONTROLLED_LOBBY_PREPARED',generic_rehearsals_closed=True,
        controlled_product_dispatch=dict(board=SLUG,cards=[first],enabled=False,controller='truco-online-lobby-controller'),
        next_action='Start real TDD-01A author/reviewer; publish reviewed product foundation, then continue original lobby DAG. No repeated CEO briefing or generic rehearsals.')
    save(DATA/'governance/execution.json',state)
    for path in [board,*board.rglob('*')]:os.chown(path,10000,10000)
    os.chown(DATA/'governance/execution.json',10000,10000)
    save(CONTROL/'preparation.json',dict(first=first,board=SLUG,backup=str(backup),scope='real product',graph_nodes=21,brief_approved=True))
    print(json.dumps(dict(first=first,board=SLUG,graph_nodes=21,release=release,backup=str(backup),status='prepared_not_started')))
if __name__=='__main__':main()
