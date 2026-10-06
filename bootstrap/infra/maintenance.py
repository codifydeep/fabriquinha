"""Operator-only maintenance: backup configuration, disable dispatch, retain work."""
import argparse
import json
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path
import yaml

PROFILES = ('produto', 'designer', 'cto', 'techlead', 'backend_data',
            'frontend', 'mobile', 'devops', 'quality_security')
ROOT = Path('/opt/data')

def begin():
    target = ROOT / 'observability' / ('maintenance-' + time.strftime('%Y%m%d-%H%M%S'))
    target.mkdir(parents=True, mode=0o700)
    db = ROOT / 'kanban/boards/truco-online/kanban.db'
    db.with_name('MAINTENANCE').write_text('Authorized maintenance; preserve worktrees.\n')
    with sqlite3.connect(db) as src, sqlite3.connect(target / 'kanban.db') as dst:
        src.backup(dst)
    with tarfile.open(target / 'profiles.tgz', 'w:gz') as archive:
        for name in PROFILES:
            for file in (ROOT / 'profiles' / name).iterdir():
                if file.is_file() and file.name in ('config.yaml', 'SOUL.md', '.env', 'AGENTS.md'):
                    archive.add(file, arcname=str(file.relative_to(ROOT)))
    originals = {}
    for name in PROFILES:
        path = ROOT / 'profiles' / name / 'config.yaml'
        config = yaml.safe_load(path.read_text())
        originals[name] = config.setdefault('kanban', {}).get('dispatch_in_gateway', True)
        config['kanban']['dispatch_in_gateway'] = False
        path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    (target / 'dispatch.json').write_text(json.dumps(originals))
    print(target, flush=True)
    # Stop supervised gateways before reclaiming workers, so nothing respawns.
    for name in PROFILES:
        subprocess.run(['/command/s6-svc', '-d', '/run/service/gateway-' + name], check=True)
        subprocess.run(['/command/s6-svwait', '-d', '-t', '30000', '/run/service/gateway-' + name], check=True)
        state_path = ROOT / 'profiles' / name / 'gateway_state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state.update(desired_state='stopped', gateway_state='stopped', restart_requested=False)
        state_path.write_text(json.dumps(state))

def resume():
    execution_path = ROOT / 'governance/execution.json'
    board = 'truco-online'
    if execution_path.exists():
        execution = json.loads(execution_path.read_text())
        if not execution.get('rehearsal_passed') or not execution.get('product_dispatch_enabled'):
            raise RuntimeError('cannot resume product before verified rehearsal and explicit release gate')
        board = execution['board']
        if not board or '/' in board or '..' in board:
            raise RuntimeError('invalid active board')
    marker = ROOT / 'kanban/boards' / board / 'MAINTENANCE'
    if not marker.exists():
        raise RuntimeError('maintenance marker missing; refusing ambiguous resume')
    for name in PROFILES:
        path = ROOT / 'profiles' / name / 'config.yaml'
        config = yaml.safe_load(path.read_text())
        if config['model'] != {'default':'qwen3.5:9b', 'provider':'ollama-local'}:
            raise RuntimeError('model drift for ' + name)
        config['kanban']['dispatch_in_gateway'] = name == 'techlead'
        config['kanban']['max_in_progress'] = 2
        config['kanban']['max_in_progress_per_profile'] = 1
        path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    marker.rename(marker.with_name('MAINTENANCE.completed.' + time.strftime('%Y%m%d-%H%M%S')))
    # Hermes' finish script marks clean exits as intentionally down; -r can
    # therefore leave the gateway stopped. Wait for down before explicit up.
    subprocess.run(['/command/s6-svc','-d','/run/service/gateway-techlead'], check=True)
    subprocess.run(['/command/s6-svwait','-d','-t','30000','/run/service/gateway-techlead'], check=True)
    subprocess.run(['/command/s6-svc','-u','/run/service/gateway-techlead'], check=True)
    print('Dispatch resumed only in techlead; max 2 workers, 1 per profile')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['begin','resume'])
    args = parser.parse_args()
    begin() if args.action == 'begin' else resume()
