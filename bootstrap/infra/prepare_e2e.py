"""Operator setup of a fresh E2E board. No product dispatch or auto-approval."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import yaml
from coordination_store import CoordinationStore
from e2e_controller import ATTEMPT

ROOT=Path('/opt/data'); BOARD=ROOT/'kanban/boards'/ATTEMPT; CONTROL=ROOT/'governance'/ATTEMPT
PROFILES=['produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security']


def cli(*args):
    return subprocess.check_output(['/opt/hermes/.venv/bin/hermes','kanban',*args],text=True)


def main():
    os.umask(0o077)
    product=json.loads((ROOT/'governance/execution.json').read_text())
    assert not product['product_dispatch_enabled'] and not product['rehearsal_passed']
    assert (ROOT/'kanban/boards'/product['board']/'MAINTENANCE').exists()
    old=ROOT/'kanban/boards/rehearsal-e2e-20260915-r4'
    with sqlite3.connect(old/'kanban.db') as db:
        assert not db.execute("SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL").fetchone()
    (old/'MAINTENANCE').write_text('Not approved: workspace drift after publication; preserved for comparison with new model.\n')
    old_execution=ROOT/'governance'/old.name/'execution.json'
    old_state=json.loads(old_execution.read_text())
    old_state.update(phase='ENSAIO_NAO_APROVADO',
        outcome_reason='workspace_drift_after_publication',superseded_by=ATTEMPT)
    old_execution.write_text(json.dumps(old_state,indent=2))
    CONTROL.mkdir(parents=True,exist_ok=True)
    backup=CONTROL/'profiles-before-e2e.tgz'
    if not backup.exists():
        with tarfile.open(backup,'w:gz') as out:
            for profile in PROFILES:
                for name in ['config.yaml','.env','gateway_state.json']:
                    path=ROOT/'profiles'/profile/name
                    if path.exists(): out.add(path,arcname=str(path.relative_to(ROOT)))
    # CLI loads the selected profile's .env over process variables. Align
    # profiles before its first scoped write, with gateways stopped.
    for profile in PROFILES:
        envpath=ROOT/'profiles'/profile/'.env'
        updates=dict(HERMES_EXECUTION_ATTEMPT=ATTEMPT,HERMES_KANBAN_BOARD=ATTEMPT,HERMES_ALLOWED_KANBAN_BOARD=ATTEMPT,
            HERMES_TEAM_EXECUTION=str(CONTROL/'execution.json'),HERMES_COORDINATION_DB=str(CONTROL/'coordination.db'))
        lines=[line for line in envpath.read_text().splitlines() if line.split('=',1)[0] not in updates]
        envpath.write_text('\n'.join(lines+[k+'='+v for k,v in updates.items()])+'\n')
    if not BOARD.exists(): cli('boards','create',ATTEMPT,'--name','ENSAIO E2E — HTTP/PR/Docker/recovery')
    cli('--board',ATTEMPT,'init')
    (BOARD/'MAINTENANCE').write_text('E2E setup and acceptance; operator releases only after verification.\n')
    journal=CONTROL/'cards.json'
    if journal.exists(): cards=json.loads(journal.read_text())
    else:
        cards={}
        for role,profile,parents in [('build','backend_data',[]),('deploy','devops',['build']),('qa','quality_security',['deploy'])]:
            args=['--board',ATTEMPT,'create','E2E-'+role.upper()+' — HTTP score rehearsal','--assignee',profile,
                '--workspace','scratch','--initial-status','blocked','--max-runtime','20m','--max-retries','2',
                '--idempotency-key',ATTEMPT+':'+role,'--json','--body','Use only the E2E operations in the scoped worker context. This is not the Truco product.']
            for parent in parents: args+=['--parent',cards[parent]]
            cards[role]=json.loads(cli(*args))['id']
        journal.write_text(json.dumps(cards,indent=2))
    data=dict(attempt=ATTEMPT,cards=cards,inject_worker_failure=True,inject_supervisor_restart=True)
    (BOARD/'e2e.json').write_text(json.dumps(data,indent=2))
    private=Path('/deliveries')
    assert private.is_dir(), 'private controller volume must be mounted during bootstrap'
    installed=private/'e2e-config.json'
    prior=private/('e2e-config.before-'+ATTEMPT+'.json')
    if installed.exists() and not prior.exists(): prior.write_bytes(installed.read_bytes())
    staged=private/'e2e-config.pending.json'
    staged.write_text(json.dumps(data,indent=2)); os.replace(staged,installed)
    assert json.loads(installed.read_text())==json.loads((BOARD/'e2e.json').read_text())
    # Explicit final checks: backend incident waits for deployment and QA.
    contracts={cards['build']:dict(immutable_review=True,incident_completion_requires=[cards['deploy'],cards['qa']]),
        cards['deploy']:dict(immutable_review=True),cards['qa']:dict(immutable_review=True,parent=cards['build'])}
    (BOARD/'validation-contracts.json').write_text(json.dumps(contracts,indent=2))
    store=CoordinationStore(CONTROL/'coordination.db')
    try:
        store.create_attempt(ATTEMPT,ATTEMPT,'isolated-http-e2e')
        state=dict(attempt=ATTEMPT,board=ATTEMPT,phase='E2E_PREPARED',product_dispatch_enabled=False,rehearsal_passed=False,
            telegram_chat_id=product['telegram_chat_id'],ceo_telegram_id=product['ceo_telegram_id'],command_bot=product['command_bot'])
        (CONTROL/'execution.json').write_text(json.dumps(state,indent=2))
    finally: store.close()
    for profile in PROFILES:
        home=ROOT/'profiles'/profile; path=home/'config.yaml'; config=yaml.safe_load(path.read_text())
        config['model']={'default':'deepseek/deepseek-v4-flash-0731','provider':'openrouter'}
        config['kanban'].update(dispatch_in_gateway=profile=='techlead',max_in_progress=2,max_in_progress_per_profile=1,
            dispatch_interval_seconds=15,review_dispatch=True,auto_decompose=False)
        config['agent']['max_turns']=40; path.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
        envpath=home/'.env'
        updates=dict(HERMES_EXECUTION_ATTEMPT=ATTEMPT,HERMES_KANBAN_BOARD=ATTEMPT,HERMES_ALLOWED_KANBAN_BOARD=ATTEMPT,
            HERMES_TEAM_EXECUTION=str(CONTROL/'execution.json'),HERMES_COORDINATION_DB=str(CONTROL/'coordination.db'))
        lines=[line for line in envpath.read_text().splitlines() if line.split('=',1)[0] not in updates]
        envpath.write_text('\n'.join(lines+[k+'='+v for k,v in updates.items()])+'\n')
    for tree in (BOARD,CONTROL):
        for path in [tree,*tree.rglob('*')]: os.chown(path,10000,10000)
    print(json.dumps(dict(attempt=ATTEMPT,cards=cards,maintenance=True,controller_config=data),indent=2))

if __name__=='__main__': main()
