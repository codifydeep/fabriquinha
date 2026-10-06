"""Operator bootstrap; run ONLY with gateways/observer/controller stopped.

Creates cards via native APIs in an isolated staging database, then copies it
into the verified EMPTY product board. No production guard bypass is installed.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import time
import yaml
from hermes_cli import kanban_db as kb
from install_company_contract import MISSIONS

ROOT = Path('/opt/data'); BOARD = ROOT / 'kanban/boards/truco-online-r2-20260911'
CONTROL = ROOT / 'governance'; PRIVATE = Path('/deliveries')
ATTEMPT = 'truco-restart-20260911'
HASH = '273d7760dc25b2641631a98a8d3aef352883d4a92469c145154285e9dd17d403'
OBJECTIVES = {
    'stories': 'Detalhar LOB-01..07 do brief em histórias pequenas e critérios Given/When/Then: apelidos, criar/listar/entrar, duas sessões em browsers, rejeição do terceiro, disputa pela última vaga e desconexão. Identificar perguntas de regra do Truco necessárias apenas antes do jogo. Não implementar, não rediscutir escopo aprovado. Cobertura explícita de todos LOB IDs.',
    'architecture': 'ADR da primeira fatia web/lobby: stack open source ARM64 local, sessão sem autenticação, isolamento, protocolo e contrato de erros, atomicidade da última vaga, reconexão, testes TDD/integração/E2E, Compose e evolução para 3D. Comparar alternativas, escolher e justificar. Separar hipóteses não medidas de evidências; não inventar benchmark. Decisões técnicas são suas, não do CEO.',
    'design': 'Especificar fluxos e estados de lobby em português a partir das histórias aprovadas: entrada/apelido, vazio/carregando/erro, criação/espera, disputa/lotação, desconexão e transição pré-jogo. Incluir acessibilidade, responsividade desktop e mapeamento LOB. Wireframes textuais, sem HTML/JS nem implementação de 3D nesta etapa.',
    'plan': 'Consolidar histórias/ADR/design aprovados num grafo TDD proposto, sem criar ou executar cards de implementação. Tarefas pequenas com IDs locais, responsáveis, revisores, dependências acíclicas, contrato API, testes Red/Green, integração, QA e deploy. Mapear LOB-01..07 e registrar como a v0.1 completa seguirá até V01-01..10; lobby não encerra release. Explicitar bloqueio da execução até validar worktrees/PRs e integrar documentos por PR.'}
ROLES = [('stories', 'produto', 'techlead', []), ('architecture', 'cto', 'techlead', []),
         ('design', 'designer', 'produto', ['stories']), ('plan', 'techlead', 'cto', ['stories', 'architecture', 'design'])]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    os.umask(0o077)
    state = json.loads((CONTROL / 'execution.json').read_text())
    assert state['attempt'] == ATTEMPT and state['brief_sha256'] == HASH
    assert state['rehearsal_passed'] and not state['product_dispatch_enabled']
    assert (BOARD / 'MAINTENANCE').exists()
    assert not (BOARD / 'planning.json').exists(), 'Already prepared: inspect before retrying.'
    with sqlite3.connect(BOARD / 'kanban.db') as db:
        assert db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    for path in (ROOT / 'kanban/boards').glob('*/kanban.db'):
        with sqlite3.connect(path) as db:
            assert not db.execute("SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL AND status='running'").fetchone(), str(path)
    brief = Path('/approved-brief.md').read_bytes()
    assert hashlib.sha256(brief).hexdigest() == HASH
    with sqlite3.connect(PRIVATE / 'controller.db') as db:
        receipt = json.loads(db.execute("SELECT value FROM e2e_state WHERE key=?", ('rehearsal-e2e-20260916-ds1:result',)).fetchone()[0])
        assert receipt['passed']
    backup = CONTROL / ('planning-backup-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    with tarfile.open(backup / 'profiles-governance-board.tgz', 'w:gz') as archive:
        paths = [BOARD, CONTROL / 'execution.json', CONTROL / 'coordination.db']
        paths += [ROOT / 'profiles' / profile / name for profile in MISSIONS
                  for name in ('SOUL.md', 'config.yaml', '.env', 'gateway_state.json')]
        paths += list((ROOT / 'skills').glob('**/company-delivery-contract/SKILL.md'))
        paths += list((ROOT / 'profiles').glob('**/company-delivery-contract/SKILL.md'))
        for path in paths:
            archive.add(path, arcname=str(path.relative_to(ROOT)))
    # Verify archive readability and SQLite copies without exposing credentials.
    with tarfile.open(backup / 'profiles-governance-board.tgz') as archive:
        for member in archive:
            if member.isfile():
                with archive.extractfile(member) as stream:
                    while stream.read(1024 * 1024): pass
    for source in (BOARD / 'kanban.db', CONTROL / 'coordination.db', PRIVATE / 'controller.db'):
        with sqlite3.connect(source) as src, sqlite3.connect(backup / source.name) as dest:
            src.backup(dest)
            assert dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    stage = backup / 'planning-bootstrap'; stage.mkdir()
    os.environ['HERMES_ALLOWED_KANBAN_BOARD'] = stage.name
    kb.init_db(stage / 'kanban.db'); db = kb.connect(stage / 'kanban.db')
    ids = {}; cards = {}
    for role, author, reviewer, parents in ROLES:
        tid = kb.create_task(db, title='DOC-' + role.upper() + '-v0.1 — Planejamento revisado',
            body=OBJECTIVES[role], assignee=author, workspace_kind='scratch', initial_status='blocked',
            parents=[ids[p] for p in parents], max_runtime_seconds=1200, max_retries=2,
            idempotency_key=ATTEMPT + ':planning:' + role)
        ids[role] = tid
        workspace = BOARD / 'workspaces' / tid; workspace.mkdir(parents=True)
        db.execute('UPDATE tasks SET workspace_path=? WHERE id=?', (str(workspace), tid)); db.commit()
        cards[tid] = dict(role=role, author=author, reviewer=reviewer, parents=[ids[p] for p in parents], objective=OBJECTIVES[role])
    for tid in ids.values(): kb.unblock_task(db, tid)
    with sqlite3.connect(BOARD / 'kanban.db') as dest: db.backup(dest)
    db.close()
    data = dict(attempt=ATTEMPT, brief_sha256=HASH, cards=cards)
    save(PRIVATE / 'planning-config.json', data)
    (PRIVATE / 'planning-brief.md').write_bytes(brief)
    save(BOARD / 'planning.json', data)
    save(CONTROL / 'planning-cards.json', ids)
    contract = Path('/input/company-contract.md').read_text()
    manifest = {}
    for profile, mission in MISSIONS.items():
        home = ROOT / 'profiles' / profile
        soul = '# Perfil ' + profile + '\n\n' + mission + '\n\n' + contract
        (home / 'SOUL.md').write_text(soul)
        manifest[profile + '/SOUL.md'] = hashlib.sha256(soul.encode()).hexdigest()
        config_path = home / 'config.yaml'; cfg = yaml.safe_load(config_path.read_text())
        assert cfg['model'] == {'default': 'deepseek/deepseek-v4-flash-0731', 'provider': 'openrouter'}
        cfg['toolsets'] = ['kanban']
        cfg['kanban'].update(dispatch_in_gateway=profile == 'techlead', max_in_progress=2,
            max_in_progress_per_profile=1, dispatch_interval_seconds=15, review_dispatch=True, auto_decompose=False)
        cfg['agent']['max_turns'] = 40
        config_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
        updates = dict(HERMES_EXECUTION_ATTEMPT=ATTEMPT, HERMES_KANBAN_BOARD=BOARD.name,
            HERMES_ALLOWED_KANBAN_BOARD=BOARD.name, HERMES_TEAM_EXECUTION=str(CONTROL / 'execution.json'),
            HERMES_COORDINATION_DB=str(CONTROL / 'coordination.db'), HERMES_WRITE_SAFE_ROOT=str(BOARD))
        env = home / '.env'
        lines = [s for s in env.read_text().splitlines() if s.split('=', 1)[0] not in updates]
        env.write_text('\n'.join(lines + [k + '=' + v for k, v in updates.items()]) + '\n')
        gateway = home / 'gateway_state.json'
        settings = json.loads(gateway.read_text()); settings.update(desired_state='running', restart_requested=False)
        save(gateway, settings)
    for tree in (ROOT / 'skills', ROOT / 'profiles'):
        for skill in tree.glob('**/company-delivery-contract/SKILL.md'):
            skill.write_text('---\nname: company-delivery-contract\ndescription: Contrato de trabalho do time Truco.\n---\n\n' + contract)
            manifest[str(skill.relative_to(ROOT))] = hashlib.sha256(skill.read_bytes()).hexdigest()
    manifest['contract_sha256'] = hashlib.sha256(contract.encode()).hexdigest()
    save(CONTROL / 'planning-installed-manifest.json', manifest)
    state.update(phase='PLANEJAMENTO_PREPARADO', planning_dispatch_enabled=False,
        implementation_dispatch_enabled=False, next_action='controller readiness then release registered planning cards', planning_backup=str(backup))
    save(CONTROL / 'execution.json', state)
    for path in [BOARD, *BOARD.rglob('*'), CONTROL, CONTROL / 'coordination.db', CONTROL / 'planning-cards.json',
                 CONTROL / 'planning-installed-manifest.json', CONTROL / 'execution.json']:
        if not path.is_symlink(): os.chown(path, 10000, 10000)
    print(json.dumps(dict(prepared=True, cards=ids, backup=str(backup), maintenance=True, implementation_allowed=False)))


if __name__ == '__main__': main()
