"""Fence and archive an old attempt after a verified checkpoint.

Operator-only; never resumes workers or deletes repository contents.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import time
import yaml
from coordination_store import CoordinationStore

ROOT = Path('/opt/data')
REPO = Path('/Users/weber/Documents/projetos_pessoais_desenv/hermes/truco-online')
PROFILES = ('produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security')
ATTEMPT = 'truco-restart-20260911'
BOARD = 'truco-online-r2-20260911'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def cli(*args):
    return run('/opt/hermes/.venv/bin/hermes', '-p', 'techlead', 'kanban', *args)


def main(checkpoint):
    os.umask(0o077)
    if checkpoint.parent != ROOT / 'observability' or not checkpoint.name.startswith('restart-'):
        raise ValueError('exact verified checkpoint directory required')
    inventory = json.loads((checkpoint / 'inventory.json').read_text())
    if len(inventory.get('restore_checks', [])) != 3:
        raise ValueError('restore rehearsal has not passed')
    # Verify small manifest and Git bundle again before external mutations.
    hashes = json.loads((checkpoint / 'sha256.json').read_text())
    for name in ('inventory.json', 'repository.bundle'):
        with (checkpoint / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != hashes[name]:
                raise ValueError('checkpoint changed: ' + name)
    old = ROOT / 'kanban/boards/truco-online'
    if not (old / 'MAINTENANCE').exists():
        raise ValueError('old board maintenance fence required')
    processes = run('ps', '-eo', 'pid,args')
    if any('hermes_cli.kanban_worker' in line for line in processes.splitlines()):
        raise ValueError('worker still alive')
    journal_path = checkpoint / 'restart-journal.json'
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'attempt': ATTEMPT, 'closed_prs': []}
    def save():
        journal_path.write_text(json.dumps(journal, indent=2))
    if not journal.get('git_archive_tag'):
        tag = 'archive/pre-restart-20260911'
        head = run('git', '-C', str(REPO), 'rev-parse', 'HEAD')
        found = subprocess.run(['git','-C',str(REPO),'rev-parse','--verify','refs/tags/' + tag], capture_output=True, text=True)
        if found.returncode:
            run('git','-C',str(REPO),'tag',tag,head)
        elif found.stdout.strip() != head:
            raise ValueError('archive tag points to a different commit')
        run('git','-C',str(REPO),'push','origin','refs/tags/' + tag)
        journal['git_archive_tag'] = tag
        save()
    for pr in inventory['open_prs']:
        number = pr['number']
        if number in journal['closed_prs']:
            continue
        current = json.loads(run('gh','pr','view',str(number),'--repo','codifydeep/truco-online','--json','state,headRefOid'))
        if current['state'] == 'MERGED':
            raise ValueError(f'PR {number} merged after checkpoint; reassessment required')
        if current['headRefOid'] != pr['headRefOid']:
            raise ValueError(f'PR {number} changed after checkpoint')
        if current['state'] == 'OPEN':
            run('gh','pr','close',str(number),'--repo','codifydeep/truco-online','--comment',
                'Encerrado por decisão explícita do CEO para recomeço rastreável em 2026-09-11. '
                'Não é aprovação, entrega ou homologação. Histórico preservado neste PR, '
                'tag archive/pre-restart-20260911 e backup privado ' + checkpoint.name + '. '
                'A tentativa nova será ' + ATTEMPT + '; nenhum segredo foi publicado.')
        journal['closed_prs'].append(number)
        save()
    if not journal.get('cancelled'):
        cli('--board','truco-online','comment','t_d0d99acc',
            'CANCELADA_PELO_CEO: tentativa anterior encerrada para recomeço rastreável, conforme aprovação de 2026-09-11. '
            'Não houve HOMOLOGADA. Backup verificado: ' + checkpoint.name + '; próxima tentativa: ' + ATTEMPT)
        tasks = json.loads(cli('--board','truco-online','list','--json'))
        ids = [task['id'] for task in tasks if task['status'] != 'archived']
        if ids:
            cli('--board','truco-online','archive',*ids)
        journal['cancelled'] = True
        save()
    # Keep the archive in its native location for now. Archival flags plus a
    # write fence make the history inspectable; no old queue is selected.
    metadata = json.loads((old / 'board.json').read_text())
    metadata.update(archived=True, name='ARQUIVO — Truco tentativa anterior — CANCELADA_PELO_CEO')
    (old / 'board.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    (old / 'READ_ONLY').write_text('Archived by CEO for restart; checkpoint ' + checkpoint.name + '\n')
    with sqlite3.connect(old / 'kanban.db') as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL TABLE%'")]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                name = 'archive_readonly_' + hashlib.sha256((table + operation).encode()).hexdigest()[:16]
                conn.execute(f'CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON {quoted} BEGIN SELECT RAISE(ABORT, \'archived board is read-only\'); END')
    cli('boards','create',BOARD,'--name','Truco Online — recomeço 2026-09-11','--default-workdir',str(REPO)) if not (ROOT / 'kanban/boards' / BOARD).exists() else None
    cli('--board', BOARD, 'init')
    new_meta_path = ROOT / 'kanban/boards' / BOARD / 'board.json'
    new_meta = json.loads(new_meta_path.read_text())
    new_meta['execution_attempt'] = ATTEMPT
    new_meta_path.write_text(json.dumps(new_meta, indent=2))
    (ROOT / 'kanban/boards' / BOARD / 'MAINTENANCE').write_text('Blocked pending isolated end-to-end rehearsal.\n')
    cli('boards','switch',BOARD)
    for profile in PROFILES:
        root = ROOT / 'profiles' / profile
        archived = checkpoint / 'retired-profile-state' / profile
        archived.mkdir(parents=True, exist_ok=True)
        for name in ('sessions','memories','plans','pending_messages','cron','workspace',
                     'state.db','state.db-wal','state.db-shm','verification_evidence.db',
                     'verification_evidence.db-wal','verification_evidence.db-shm'):
            source = root / name
            target = archived / name
            if source.exists() and not target.exists():
                source.rename(target)
        config_path = root / 'config.yaml'
        config = yaml.safe_load(config_path.read_text())
        config.setdefault('kanban', {})['dispatch_in_gateway'] = False
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
        state_path = root / 'gateway_state.json'
        gateway_state = json.loads(state_path.read_text()) if state_path.exists() else {}
        gateway_state.update(desired_state='stopped', gateway_state='stopped',
                             restart_requested=False, exit_reason='authorized_restart_maintenance')
        state_path.write_text(json.dumps(gateway_state))
        env_path = root / '.env'
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        lines = [line for line in lines if not line.startswith(('HERMES_KANBAN_BOARD=', 'HERMES_EXECUTION_ATTEMPT='))]
        env_path.write_text('\n'.join(lines + ['HERMES_KANBAN_BOARD=' + BOARD, 'HERMES_EXECUTION_ATTEMPT=' + ATTEMPT]) + '\n')
    registry = ROOT / 'governance/active-release.json'
    if registry.exists() and not (checkpoint / 'retired-active-release.json').exists():
        registry.rename(checkpoint / 'retired-active-release.json')
    store = CoordinationStore(ROOT / 'governance/coordination.db')
    try:
        store.create_attempt(ATTEMPT, BOARD, 'v0.1')
    finally:
        store.close()
    env=dict(line.split('=',1) for line in (ROOT/'profiles/techlead/.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    ceo=env.get('TELEGRAM_ALLOWED_USERS','').strip().strip('"\'')
    chat=env.get('TELEGRAM_ALLOWED_CHATS','').strip().strip('"\'')
    if not ceo.isdigit() or not chat.lstrip('-').isdigit():
        raise ValueError('one explicit CEO and team chat identity required; do not infer from chat text')
    (ROOT / 'governance/execution.json').write_text(json.dumps({
        'attempt': ATTEMPT, 'board': BOARD, 'phase': 'ESTABILIZACAO',
        'product_dispatch_enabled': False, 'rehearsal_passed': False,
        'checkpoint': str(checkpoint), 'repo': str(REPO),
        'ceo_telegram_id':ceo,'telegram_chat_id':chat,'command_bot':'techlead_truco_poc_bot',
        'created_at': int(time.time())}, indent=2))
    journal.update(archived_board='truco-online', new_board=BOARD, phase='ARCHIVED_AND_FENCED')
    save()
    print(json.dumps(journal), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=Path, required=True)
    main(parser.parse_args().checkpoint)
