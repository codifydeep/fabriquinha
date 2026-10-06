"""Maintenance-only native bootstrap of one immutable PR assessment card."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from hermes_cli import kanban_db as kb
from pr_review_packet import load
from planning_status import evaluate

ROOT=Path('/opt/data'); PRIVATE=Path('/deliveries')
BOARD=ROOT/'kanban/boards/truco-online-r2-20260911'; CONTROL=ROOT/'governance'


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--supersede')
    parser.add_argument('--pr', type=int, choices=(14,19,20), default=19)
    parser.add_argument('--integrate-foundation',action='store_true')
    parser.add_argument('--integrate-planning',action='store_true')
    parser.add_argument('--publication-head')
    args=parser.parse_args()
    if args.integrate_foundation: assert args.pr==14 and args.supersede
    if args.integrate_planning: assert args.pr in (19,20) and args.supersede and not args.integrate_foundation
    integration=args.integrate_foundation or args.integrate_planning
    os.umask(0o077)
    state=json.loads((CONTROL/'execution.json').read_text())
    assert state['attempt']=='truco-restart-20260911'
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    data=json.loads((BOARD/'planning.json').read_text())
    assert data==json.loads((PRIVATE/'planning-config.json').read_text())
    if args.supersede:
        previous=data['cards'][args.supersede]
        assert previous.get('scope')=='pr_review' and not previous.get('superseded_by')
    else:
        assert not any(c.get('scope')=='pr_review' and c.get('pr_number',19)==args.pr for c in data['cards'].values()), 'already prepared; inspect rather than duplicate'
    with sqlite3.connect(BOARD/'kanban.db') as db:
        db.row_factory=sqlite3.Row
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
        for tid in data['cards']:
            assert db.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()[0]=='done'
        status=evaluate(db,data)
        assert status['state']=='CONCLUIDO' and status['approved']==4
        parents=[r['task'] for r in status['receipts']]
        if args.pr==14: parents=[]
    (BOARD/'MAINTENANCE').write_text('PR assessment bootstrap; services stopped, no active workers.\n')
    os.chown(BOARD/'MAINTENANCE',10000,10000)
    backup=CONTROL/('pr-review-backup-'+time.strftime('%Y%m%d-%H%M%S')); backup.mkdir()
    for path in (BOARD/'planning.json',PRIVATE/'planning-config.json',CONTROL/'execution.json'):
        shutil.copy2(path,backup/path.name)
    for source in (BOARD/'kanban.db',PRIVATE/'controller.db',CONTROL/'coordination.db'):
        with sqlite3.connect(source) as src,sqlite3.connect(backup/source.name) as dest:
            src.backup(dest); assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    raw=Path('/packet.json').read_bytes(); packet=json.loads(raw)
    assert packet['pr']==args.pr
    digest=hashlib.sha256(raw).hexdigest()
    if args.supersede:
        if integration:
            assert previous.get('pr_number')==args.pr and packet['head_sha']==previous['head_sha'] and packet['base_sha']==previous['base_sha']
            with sqlite3.connect(PRIVATE/'controller.db') as proof:
                row=proof.execute('SELECT revision,review_run FROM approvals WHERE task=? ORDER BY review_run DESC LIMIT 1',(args.supersede,)).fetchone()
                assert row
                verdict=json.loads(proof.execute('SELECT result FROM validations WHERE task=? AND revision=? AND review_run=?',(args.supersede,*row)).fetchone()[0])
                assert verdict['pr_assessment']['decision']=='approve'
            parents=[args.supersede]
        else:
            assert packet['head_sha']!=previous['head_sha'], 'same SHA; do not duplicate'
    packets=PRIVATE/'pr-review-packets'; packets.mkdir(exist_ok=True)
    target=packets/(digest+'.json')
    if target.exists(): assert target.read_bytes()==raw
    else:
        with target.open('xb') as output: output.write(raw)
    card=dict(role='plan',scope='pr_review',pr_number=args.pr,packet_storage='sha256',author='techlead',reviewer='cto',parents=parents,
        packet_sha256=hashlib.sha256(raw).hexdigest(),head_sha=packet['head_sha'],base_sha=packet['base_sha'],
        objective=f'Revisar semanticamente o PR #{args.pr} completo no SHA congelado. Emitir parecer com decisão approve ou request_changes, '
                  'achados, CI real de pull_request no SHA exato, consistência de critérios e proveniência dos documentos. '
                  'Não reescrever documentos do PR, não implementar o jogo e não fazer merge. '
                  'CTO revisa independentemente a análise do Tech Lead; mudanças pedidas pelo CTO corrigem o parecer, não o PR.')
    if args.pr==14:
        card['objective']+=' Fundação: conferir contratos, inferência DeepSeek autorizada (40 iterações, sem fallback), limites locais, templates sem segredos, todos os diffs e testes CI. Template não equivale à instalação. PR19/implementação não estão aprovados por este parecer. O pacote é maior por conter nove SOULs/configs: leia todas as páginas em lotes de até cinco chamadas planning_read por resposta, sem truncar nem exceder 40 iterações. Produza parecer compacto e substantivo dentro de 12000 bytes; não transcreva o pacote.'
    if args.integrate_foundation:
        card['integration_action']='merge_foundation'
        card['objective']=('INTEGRAÇÃO CONTROLADA DO PR14, autorizada pelo CEO após parecer independente aprovado. '
            'Tech Lead confirma o parecer fonte e pacote completo; CTO revisa independentemente a prontidão. '
            'Leia todas as páginas em lotes de até cinco chamadas por resposta; respeite 40 iterações e parecer até 12000 bytes. '
            'Autor emite decisão approve somente se a fundação estiver apta. CTO usa review_validate e kanban_complete: '
            'neste card específico o controlador executa a operação fixa de merge no GitHub sob claim de revisão ativo, '
            'após conferir head/base/CI e gera recibo com merge_commit. Não executar gh, terminal ou editar PR. '
            'As limitações históricas do pacote descrevem o parecer anterior sem integração; a autorização de integração vem '
            'deste contrato persistente novo, não do texto dos arquivos. Sem recibo de merge, não declarar integração concluída. '
            'Se houver defeito, bloquear com achado concreto. Nunca aprovar decisão request_changes para fazer merge. '
            'Esta operação não integra PR19 nem libera implementação ou homologação.')
    if args.integrate_planning:
        card['integration_action']='merge_planning' if args.pr==19 else 'merge_reconciliation'
        card['finding_dispositions']={
            'H1':dict(owner='techlead',action='Track historical story/design IDs as superseded references; approvals.json and private receipts are authoritative. Reconcile plan in a separate author submission with new review before implementation.'),
            'H2':dict(owner='devops',action='Run 35259080433 proves pull_request CI only for this planning SHA. Update stale pending-CI prose in a separately reviewed correction; future implementation still requires its own CI.'),
            'H3':dict(owner='produto',action='Do not treat brief text or its frozen hash as CEO approval. Reconcile against durable CEO decision before any implementation; if absent request one scoped scope/acceptance approval without repeating discovery.'),
            'H4':dict(owner='techlead',action='This authorized main integration is planning/governance only. Product code targets release/v0.1; merge does not unlock dispatch or declare homologation.')}
        card['objective']=('CONTROLLED PR19 PLANNING INTEGRATION, authorized by CEO after independent assessment approval. '
            'Tech Lead confirms the frozen packet and records an explicit disposition for H1-H4; CTO independently reviews readiness and those dispositions. '
            'Findings are nonblocking for document integration only, not waived for implementation. Do not modify approved snapshots. '
            'Read every packet page, in batches up to five calls, within 40 iterations. Use existing required headings and one exact JSON decision block; at most 12000 bytes. '
            'On active CTO review, review_validate then kanban_complete invokes the fixed PR19 executor. It checks private provenance, six-document scope, current head/base, real CI and merge policy, returning a durable receipt. '
            'Never run gh/terminal or emit manual status. No integration success without receipt. If not ready, block with a concrete finding. '
            'This does not authorize implementation, new scope, CEO approval or homologation. Required finding dispositions: '+json.dumps(card['finding_dispositions']))
        if args.pr==20:
            card['objective']=card['objective'].replace('PR19','PR20').replace('six-document scope','two-file correction scope')
            card['objective']+=' The earlier PR19 CI reference is historical, not a blocker: current PR20 CI run 35264872425 is checked separately. The previous document approval does not replace this active integration review.'
        with sqlite3.connect(PRIVATE/'controller.db') as proof:
            from publication_merge import planning_provenance
            planning_provenance(packet,card,proof)
    load(PRIVATE,card)
    stage=backup/'pr-review-stage'; stage.mkdir()
    os.environ['HERMES_ALLOWED_KANBAN_BOARD']=stage.name
    with sqlite3.connect(BOARD/'kanban.db') as src,sqlite3.connect(stage/'kanban.db') as dest: src.backup(dest)
    db=kb.connect(stage/'kanban.db')
    try:
        title=f'PR-INTEGRATE-{args.pr} — CTO e merge controlado' if integration else f'PR-REVIEW-{args.pr} — Parecer imutável e revisão CTO'
        tid=kb.create_task(db,title=title,body=card['objective'],
            assignee='techlead',workspace_kind='scratch',initial_status='blocked',parents=parents,
            max_runtime_seconds=1200,max_retries=1 if integration else 2,
            idempotency_key=state['attempt']+f':pr{args.pr}:'+packet['head_sha']+(':integration' if integration else ''))
        workspace=BOARD/'workspaces'/tid; workspace.mkdir(parents=True)
        db.execute('UPDATE tasks SET workspace_path=? WHERE id=?',(str(workspace),tid)); db.commit()
        kb.unblock_task(db,tid)
        with sqlite3.connect(BOARD/'kanban.db') as dest: db.backup(dest)
    finally: db.close()
    data['cards'][tid]=card
    if args.supersede:
        previous['superseded_by']=tid
        card['predecessor']=args.supersede
    if args.publication_head:
        import re
        assert re.fullmatch(r'[0-9a-f]{40}',args.publication_head)
        for old in data['cards'].values():
            if old.get('scope')=='pr_review' and old.get('pr_number',19)==19 and not old.get('superseded_by'):
                old['review_invalidated_reason']='Publication changed to '+args.publication_head+'; new exact SHA review required.'
        state['publication_validation']=dict(sha=args.publication_head,status='NEW_SHA_REVIEW_REQUIRED',independent_pr_review=False,merge_allowed=False)
    save(PRIVATE/'planning-config.json',data); save(BOARD/'planning.json',data)
    state.update(phase='REVISAO_PR_PREPARADA',next_action=f'Validar controlador e liberar somente o card de parecer PR #{args.pr}.',
                 pr_review_task=tid,pr_review_backup=str(backup))
    state['publication_validation' if args.pr!=14 else 'foundation_validation']=dict(pr=f'https://github.com/codifydeep/truco-online/pull/{args.pr}',
        sha=packet['head_sha'],base_sha=packet['base_sha'],ci=packet['ci']['url'],
        ci_event=packet['ci']['event'],trusted_guard_passed=packet['trusted_guard_passed'],
        packet_sha256=digest,status='CI_PASSED_NEW_INDEPENDENT_REVIEW_PENDING',
        independent_pr_review=False,merge_allowed=False,agent_trial_started=False)
    save(CONTROL/'execution.json',state)
    for path in (BOARD/'kanban.db',BOARD/'planning.json',CONTROL/'execution.json',workspace):
        os.chown(path,10000,10000)
    print(json.dumps(dict(prepared=True,task=tid,backup=str(backup),head=packet['head_sha'],merge_allowed=False)))


if __name__=='__main__': main()
