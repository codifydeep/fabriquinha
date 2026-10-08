"""One durable bridge from a selected brief to the existing delivery controller.

This is not a new agent runner. The child controllers retain all execution,
immutable review, test-first, CI, merge and exact-SHA QA responsibilities.
"""
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

from release_eval import save_receipt

ROOT = Path(__file__).resolve().parent
STEPS = ('planning', 'materializing', 'compiling', 'executing')


def verify_registration(config, private):
    path = Path(private) / 'host-service' / (config['name'] + '.brief-input.json')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError('native brief input registration missing or unsafe')
    expected = {'input_sha256': config['sha256'], 'configuration': str(config['path'])}
    if json.loads(path.read_text()) != expected:
        raise ValueError('native brief input registration drift')


def supervise(path, identity, run, *, reconcile_planning=False, compilation_revision=None):
    if compilation_revision is not None and not re.fullmatch(r'[a-f0-9]{64}', compilation_revision):
        raise ValueError('verified compilation revision required')
    path = Path(path)
    if path.is_symlink():
        raise ValueError('pipeline ledger must not be a symlink')
    ledger = json.loads(path.read_text()) if path.exists() else {
        'identity': identity, 'stage': 'ready', 'completed': []}
    if ledger.get('identity') != identity:
        raise ValueError('pipeline input identity drift')
    completed = ledger.get('completed')
    if not isinstance(completed, list) or completed != list(STEPS[:len(completed)]):
        raise ValueError('invalid pipeline progress')
    if ledger.get('stage') == 'blocked':
        planning = reconcile_planning and ledger.get('active') == 'planning' and not completed
        revisions = ledger.get('compilation_recovery_revisions', [])
        compilation = (compilation_revision is not None and ledger.get('active') == 'compiling'
                       and completed == list(STEPS[:2]) and compilation_revision not in revisions)
        if not planning and not compilation and (ledger.get('active') != 'executing' or completed != list(STEPS[:3])):
            return 1
        if compilation:
            ledger['compilation_recovery_revisions'] = [*revisions, compilation_revision]
        # The existing sequence supervisor reconciles only evidence-qualified
        # recoveries; it does not blindly respawn an unresolved author. Keep
        # this route observable rather than strand a later broker recovery.
        incident = {field: ledger.get(field) for field in
                    ('active', 'category', 'owner', 'last_exit_code', 'next_action')}
        history = ledger.setdefault('prior_incidents', [])
        if not any(all(item.get(field) == value for field, value in incident.items())
                   for item in history):
            history.append({**incident, 'observed_at': ledger.get('updated_at'),
                            'status': 'reconciliation_in_progress'})
        # A retry of the controller is not proof of recovery. Preserve the
        # incident, but do not present its old fault as the current execution.
        for field in ('owner', 'last_exit_code', 'category', 'next_action'):
            ledger.pop(field, None)
    # Completion must survive actual revalidation of the sequence, not only
    # the presence of this local terminal flag. Never rerun planning here.
    pending = ('executing',) if completed == list(STEPS) else STEPS[len(completed):]
    for step in pending:
        ledger.update(stage='working', active=step, updated_at=time.time())
        save_receipt(path, ledger)
        result = run(step)
        if result != 0:
            ledger.update(stage='blocked', owner='techlead', last_exit_code=result,
                          category='brief_delivery_' + step + '_not_qualified',
                          next_action='Inspect this step\'s durable incident and evidence; '
                                      'do not bypass gates or blindly repeat the agent task',
                          updated_at=time.time())
            save_receipt(path, ledger)
            return 1
        if step not in completed:
            completed.append(step)
        for field in ('owner', 'last_exit_code', 'category', 'next_action'):
            ledger.pop(field, None)
        ledger.update(stage='step_complete', completed=completed, active=None,
                      updated_at=time.time())
        save_receipt(path, ledger)
    ledger.update(stage='qualified', active=None, updated_at=time.time())
    save_receipt(path, ledger)
    return 0


def main():
    from bootstrap_multica import BACKEND_PORT, PRIVATE
    from evalctl import PROJECT, verify
    from planned_delivery import load_configuration
    from start_eval import read_model_budget
    config = load_configuration(os.environ['DELIVERY_KIT_BRIEF_DELIVERY_CONFIG'])
    if os.environ.get('DELIVERY_KIT_BRIEF_SERVICE') == '1':
        verify_registration(config, PRIVATE)
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081' or verify():
        raise ValueError('isolated healthy port2 control plane required')
    directory = PRIVATE / 'brief-delivery'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (config['name'] + '.json')
    if path.is_symlink():
        raise ValueError('pipeline ledger must not be a symlink')
    lock_path = directory / (config['name'] + '.lock')
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists() and read_model_budget()['remaining'] < config['minimum_calls']:
            raise ValueError('insufficient approved reserve for planning plus dependent delivery')
        env = {**os.environ, 'DELIVERY_KIT_PLANNING_CONFIG': str(config['planning_path']),
               'DELIVERY_KIT_PROJECT_CONFIG': str(ROOT / 'projects' / config['project_config']),
               'DELIVERY_KIT_SEQUENCE_PLAN': str(ROOT / 'projects' / (config['prefix'] + '.sequence.json')),
               'DELIVERY_KIT_TEST_FIRST': '1'}
        for key in ('DELIVERY_KIT_EXISTING_ISSUE_ID', 'DELIVERY_KIT_RUN_SPEC',
                    'DELIVERY_KIT_DELIVERY_CONTRACT', 'DELIVERY_KIT_CONTROLLED_WORKER_LOSS',
                    'DELIVERY_KIT_TEST_REVISION_PARENT', 'DELIVERY_KIT_TEST_REVISION_DEPTH'):
            env.pop(key, None)
        scripts = dict(zip(STEPS, ('planning_intake.py', 'materialize_plan.py',
                                  'planned_delivery.py', 'sequence_supervisor.py')))
        def pending_clarification():
            planning_path = PRIVATE / 'planning-intake' / (config['name'] + '.json')
            if planning_path.is_symlink() or not planning_path.is_file():
                return False
            state = json.loads(planning_path.read_text())
            from planning_source_review import pending as source_pending
            if (state.get('configuration_sha256')==config['selection']['configuration_sha256']
                    and source_pending(state)):
                return True
            from planning_constraint_recovery import pending as constraint_pending
            from start_eval import cli
            registry=json.loads((PRIVATE/'planning-agents.json').read_text())
            if constraint_pending(state,config['selection']['configuration_sha256'],registry,cli):
                return True
            from planning_intake import product_protocol_revalidation, cto_context_replan
            if (state.get('configuration_sha256') == config['selection']['configuration_sha256']
                    and (product_protocol_revalidation(state) is not None
                         or cto_context_replan(state) is not None)):
                return True
            from planning_ceo_answer import pending
            if state.get('configuration_sha256') == config['selection']['configuration_sha256']:
                if pending(PRIVATE, config['name'], state):
                    return True
            return (state.get('stage') == 'blocked_awaiting_ceo'
                    and not state.get('brief_clarification_product')
                    and state.get('configuration_sha256') == config['selection']['configuration_sha256'])
        def run(step):
            def child():
                return subprocess.run([sys.executable, '-u', str(ROOT / scripts[step])],
                                      cwd=ROOT, env=env, check=False).returncode
            result = child()
            if step == 'planning' and result and pending_clarification():
                return child()  # one source re-read, not a supplied business answer
            return result
        revision = None
        state = json.loads(path.read_text()) if path.exists() else {}
        if state.get('stage') == 'blocked' and state.get('active') == 'compiling':
            from compilation_recovery import qualified_revision
            revision = qualified_revision(config, PRIVATE)
        result = supervise(path, config['sha256'], run, reconcile_planning=pending_clarification(),
                           compilation_revision=revision)
    ledger = json.loads(path.read_text())
    print(json.dumps({'name': config['name'], 'stage': ledger['stage'],
                      'active': ledger.get('active'), 'completed': ledger['completed']}))
    if os.environ.get('DELIVERY_KIT_BRIEF_SERVICE') == '1' and ledger['stage'] in ('qualified', 'blocked'):
        return 0
    return result


if __name__ == '__main__':
    raise SystemExit(main())
