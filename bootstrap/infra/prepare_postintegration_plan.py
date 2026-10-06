"""Prepare one author-owned, independently reviewed reconciliation; no product unlock."""
import hashlib,json,os,shutil,sqlite3,time
from pathlib import Path
from hermes_cli import kanban_db as kb
from immutable_delivery import DeliveryStore
from planning_drafts import initialize,save as save_draft
from planning_corrections import validate

B=Path('/opt/data/kanban/boards/truco-online-r2-20260911'); P=Path('/deliveries'); G=Path('/opt/data/governance')
OLD='t_3c648e2e'; SOURCE='t_1d58b3ac'

def main():
    os.umask(0o077)
    state=json.loads((G/'execution.json').read_text()); cfg=json.loads((B/'planning.json').read_text())
    assert cfg==json.loads((P/'planning-config.json').read_text())
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    assert not state.get('postintegration_plan'), 'already prepared'
    with sqlite3.connect(G/'coordination.db') as db:
        raw=db.execute("SELECT data FROM records WHERE attempt=? AND kind='brief' AND id='approved'",(state['attempt'],)).fetchone()[0]
    approval=json.loads(raw)
    assert approval['actor']=='ceo' and approval['brief_sha256']==state['brief_sha256'] and approval['brief_id']==state['brief_id']
    assert approval['criteria']==[f'V01-{i:02d}' for i in range(1,11)] and approval['milestone_criteria']==[f'LOB-{i:02d}' for i in range(1,8)]
    assert hashlib.sha256((G/'approved-briefs'/state['brief_sha256']/'brief.md').read_bytes()).hexdigest()==state['brief_sha256']
    with sqlite3.connect(B/'kanban.db') as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
        assert all(db.execute('SELECT status FROM tasks WHERE id=?',(t,)).fetchone()[0]=='done' for t in (OLD,SOURCE))
    backup=G/('postintegration-backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    for f in (B/'planning.json',P/'planning-config.json',G/'execution.json'):shutil.copy2(f,backup/f.name)
    for f in (B/'kanban.db',P/'controller.db',G/'coordination.db'):
        with sqlite3.connect(f) as src,sqlite3.connect(backup/f.name) as dst:src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    (B/'MAINTENANCE').write_text('Post-integration plan reconciliation; product fenced.\n');os.chown(B/'MAINTENANCE',10000,10000)
    proof=sqlite3.connect(P/'controller.db');initialize(proof)
    receipt=json.loads(proof.execute('SELECT receipt FROM publication_intents WHERE task=? AND receipt IS NOT NULL',(SOURCE,)).fetchone()[0])
    assert receipt['merged'] and receipt['merge_commit']=='f63bee64d22bcaede1e0c895d80db2baa9086ed2'
    revision=proof.execute('SELECT revision FROM approvals WHERE task=? ORDER BY review_run DESC LIMIT 1',(OLD,)).fetchone()[0]
    store=DeliveryStore(P);store.load(state['attempt'],OLD,revision)
    content=(store.path(state['attempt'],OLD,revision)/'files/PLAN.md').read_text()
    validate(dict(role='plan',correction_gate=True),content)
    stage=backup/'stage';stage.mkdir();os.environ['HERMES_ALLOWED_KANBAN_BOARD']=stage.name
    with sqlite3.connect(B/'kanban.db') as src,sqlite3.connect(stage/'kanban.db') as dst:src.backup(dst)
    db=kb.connect(stage/'kanban.db')
    try:
        tid=kb.create_task(db,title='PLAN-RECONCILE — H1-H4 and product gate prerequisites',assignee='techlead',workspace_kind='scratch',
            initial_status='blocked',parents=[OLD,SOURCE],max_runtime_seconds=1200,max_retries=1,idempotency_key=state['attempt']+':postintegration-plan')
        edits=[];expected=content
        def replace(old,new):
            nonlocal expected
            assert expected.count(old)==1
            edits.append(dict(old=old,new=new));expected=expected.replace(old,new,1)
        replace('**Tarefa:** '+OLD,'**Tarefa:** '+tid)
        for line in expected.splitlines():
            if 't_10ca48e7' in line or 't_fd99c33d' in line:
                replace(line,line.replace('t_10ca48e7','t_9e3c460e').replace('t_fd99c33d','t_10707a95'))
        for line in expected.splitlines():
            if line.startswith('**Fora do escopo desta entrega:**'):
                replace(line,'**Fora do escopo desta entrega:** implementação, deploy e homologação. Fundação (PR14) e planejamento (PR19) foram integrados em main com recibos. Código de produto usará release/v0.1. O adaptador de execução de produto e demais gates operacionais continuam pendentes; nenhum card de implementação foi liberado.')
            elif line.startswith('**CI:**'):
                replace(line,'**CI:** o run 35259080433 passou em evento pull_request no head ed43c62daa3a357f7da7cce45ad6e2988a7982be do PR19. Isso comprova o gate desta publicação de planejamento, não suites futuras do jogo. TDD-18 continua responsável pela CI completa de aplicação; cada novo SHA exigirá sua própria CI.')
            elif line.startswith('2. **Integração de documentos por PR:**'):
                replace(line,'2. **Integração de documentos por PR:** concluída em main via PR19, commit f63bee64d22bcaede1e0c895d80db2baa9086ed2, recibo CTO run 75. Esta correção precisará de nova revisão e publicação antes de virar baseline. Código do produto integra em release/v0.1; merge documental não libera execução.')
            elif line.startswith('3. **CI por `pull_request` real:**'):
                replace(line,'3. **CI por `pull_request` real:** comprovada para o PR19 no run 35259080433. Não dispensa a CI por SHA dos novos PRs nem a validação do adaptador de execução do produto.')
            elif line.startswith('| R5 |'):
                replace(line,'| R5 | CI real de publicação comprovada no PR19 (run 35259080433); testes da aplicação ainda não existem. | Exigir CI do SHA de cada PR de implementação e executar a suite completa definida em TDD-18. |')
            elif line.startswith('| P2 |'):
                replace(line,'| P2 | Fundação e documentos integrados em main por PR14/PR19; CI real da publicação passou. Adaptador de worktrees/PRs e gates próprios do produto ainda precisam de validação. | Publicar esta correção revisada; depois validar o modo produto antes de TDD-01. Não tratar merge documental como homologação. |')
        replace('CI por `pull_request` real permanece pendência técnica a fechar antes da implementação.','CI de publicação passou no PR19; a suite de aplicação continua requisito desta tarefa e não foi comprovada pelo PR documental.')
        addition=('\n## Reconciliação H1–H4 após integração\n\n'
            'H1 — Tech Lead: referências atualizadas para stories t_9e3c460e e design t_10707a95; snapshots anteriores preservados.\n'
            'H2 — DevOps: CI pull_request run 35259080433 validou somente o SHA documental; suites futuras do produto permanecem obrigatórias.\n'
            'H3 — Produto: aprovação do CEO encontrada no ledger da tentativa truco-restart-20260911, registro brief/approved, vinculada ao ID/hash acima e V01-01..10/LOB-01..07, fonte conversa Codex, mensagem “de acordo. Prossiga”. O arquivo do brief é a proposta congelada anterior à aprovação; seu texto AGUARDANDO_APROVACAO_DO_CEO não invalida o recibo posterior. Não editar esse arquivo nem solicitar nova aprovação do mesmo escopo. Aprovação do brief não autoriza ferramentas, merge ou homologação.\n'
            'H4 — Tech Lead: main recebeu apenas fundação/planejamento autorizados. Código usará release/v0.1, com PR e revisão independente.\n'
            'Gate ainda fechado: adaptar ferramentas/isolamento para código real, validar worktrees/PR/CI/TDD/revisão/deploy com evidências, publicar esta correção e validar mapeamento do grafo antes de criar/despachar implementação. Lobby não encerra a versão.\n')
        tail=expected.splitlines()[-1];replace(tail,tail+addition)
        validate(dict(role='plan',correction_gate=True),expected)
        assert len(edits)<=24, 'must fit three writes with at most eight patches each'
        objective=('Apply ONLY the registered exact replacements to the saved predecessor draft. Read planning_read(view="draft"), then planning_patch with current expected_sha, up to 8 edits per call. Preserve every other byte and all 21 TDD nodes. Do not rewrite or translate. Submit for independent CTO review; no implementation, Git operations or release. Edits: '+json.dumps(edits,ensure_ascii=False))
        workspace=B/'workspaces'/tid;workspace.mkdir(parents=True);os.chown(workspace,10000,10000)
        db.execute('UPDATE tasks SET workspace_path=?,body=? WHERE id=?',(str(workspace),objective,tid));db.commit()
        cfg['cards'][tid]=dict(role='plan',author='techlead',reviewer='cto',parents=[OLD,SOURCE],predecessor=OLD,review_source=SOURCE,
            correction_gate=True,exact_content_sha256=hashlib.sha256(expected.encode()).hexdigest(),objective=objective)
        cfg['cards'][OLD]['superseded_by']=tid;save_draft(proof,tid,0,content,'approved_predecessor_no_new_approval');kb.unblock_task(db,tid)
        with sqlite3.connect(B/'kanban.db') as dst:db.backup(dst)
        report=dict(brief_approval_verified=True,brief_sha256=state['brief_sha256'],proposal_graph_nodes=21,graph_matrix_and_dag_valid=True,
            implementation_allowed=False,pending=['independent correction review and publication','product execution adapter validation','native task graph materialization behind gate'],correction_task=tid)
        (backup/'gate-audit.json').write_text(json.dumps(report,indent=2));(backup/'expected-plan.md').write_text(expected)
    finally:db.close();proof.close()
    for f in (B/'planning.json',P/'planning-config.json'):f.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    state.update(phase='POSTINTEGRATION_PREPARED',postintegration_plan=dict(task=tid,backup=str(backup),audit=report),next_action='Review plan reconciliation; product execution adapter remains fenced.')
    (G/'execution.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    for f in (B/'planning.json',B/'kanban.db',G/'execution.json'):os.chown(f,10000,10000)
    print(json.dumps(dict(task=tid,backup=str(backup),edits=len(edits),audit=report)))

if __name__=='__main__':main()
