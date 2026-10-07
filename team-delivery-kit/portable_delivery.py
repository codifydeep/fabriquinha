"""Resumable operator controller for the isolated non-calculator qualification.

Agents implement and review in Multica. This controller alone converts one
approved frozen snapshot into a protected PR, exact-main CI and local QA.
"""
import hashlib
import fcntl
import json
import os
from portable_remediation_gate import qualify as qualify_remediation_delivery
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from docker_grouping import args as docker_group_args

from bootstrap_multica import PRIVATE
from evalctl import PROJECT as INSTANCE
from portable_contract import from_environment
from portable_preflight import verify as preflight
from portable_worker_recovery import RecoveryEscalation, reconcile as reconcile_worker
from portable_reviewer_recovery import reconcile as reconcile_reviewer
from portable_qualification import run_frozen_tests, verify_docker_deployment
from portable_qa_incident import QualityBlocked, find as find_qa_incident
from portable_qa_incident import record as record_qa_incident
from portable_qa_repair import DiagnosisRejected, resume_once as resume_qa_repair
from portable_qa_diagnosis_retry import find as find_qa_diagnosis_retry
from portable_qa_diagnosis_retry import record as record_qa_diagnosis_retry
from portable_qa_cto import find as find_qa_cto_escalation
from portable_qa_cto import record as record_qa_cto_escalation
from portable_qa_publication import publish as publish_qa_recovery
from portable_run_spec import load as load_run_spec
from project_selection import current
from release_eval import approved_submission, export_snapshot, save_receipt
from start_eval import cli
from prepare_issue_base import broker_post
from publication_access import WaitingPublicationAccess, require_access


LABEL = os.environ.get('DELIVERY_KIT_PORTABLE_LABEL', 'PORT-4')
if LABEL not in ('PORT-4', 'PORT-5', 'PORT-6', 'PORT-7', 'PORT-8', 'PORT-9') and not os.environ.get('DELIVERY_KIT_RUN_SPEC'):
    raise ValueError('unsupported portable qualification label')
BRANCH = 'codex/' + LABEL.lower() + '-reviewed'
CONTAINER = INSTANCE + '-slug-' + LABEL.lower().replace('-', '') + '-qa'
QA_PORT = {'PORT-4': 19312, 'PORT-5': 19313, 'PORT-6': 19314,
           'PORT-7': 19315, 'PORT-8': 19316, 'PORT-9': 19317}.get(LABEL, 0)
CONTAINER_PORT = 8080
DOCKERFILE = 'Dockerfile.slug'
IMAGE_NAME = INSTANCE + '-slug'
RUN_SPEC = None
RECEIPT = PRIVATE / 'release-receipts' / (LABEL + '.json')
STATUS = PRIVATE / 'autonomy-status' / (LABEL + '.json')
WORKER_RECOVERY = PRIVATE / 'worker-recovery' / (LABEL + '.json')
REVIEWER_RECOVERY = PRIVATE / 'worker-recovery' / (LABEL + '-reviewer.json')
PROJECT = current()
REPO = PROJECT['checkout']
REPOSITORY = PROJECT['repository']
LEGACY_CONFIG = (LABEL, BRANCH, CONTAINER, QA_PORT, CONTAINER_PORT, DOCKERFILE,
                 IMAGE_NAME, RECEIPT, STATUS, WORKER_RECOVERY, REVIEWER_RECOVERY)


def configure_run(contract):
    """Opt into a validated operator spec; leave historical PORT-* untouched."""
    global LABEL, BRANCH, CONTAINER, QA_PORT, CONTAINER_PORT, DOCKERFILE
    global IMAGE_NAME, RUN_SPEC, RECEIPT, STATUS, WORKER_RECOVERY, REVIEWER_RECOVERY
    spec = load_run_spec(contract)
    if not spec:
        (LABEL, BRANCH, CONTAINER, QA_PORT, CONTAINER_PORT, DOCKERFILE,
         IMAGE_NAME, RECEIPT, STATUS, WORKER_RECOVERY, REVIEWER_RECOVERY) = LEGACY_CONFIG
        RUN_SPEC = None
        return
    if contract['repository'] != REPOSITORY:
        raise ValueError('run spec project repository mismatch')
    RUN_SPEC = spec
    LABEL = spec['label']
    BRANCH = 'codex/' + LABEL.lower() + '-reviewed'
    CONTAINER = INSTANCE + '-' + LABEL.lower() + '-qa'
    QA_PORT = spec['qa_host_port']
    CONTAINER_PORT = spec['container_port']
    DOCKERFILE = spec['dockerfile']
    IMAGE_NAME = INSTANCE + '-delivery'
    RECEIPT = PRIVATE / 'release-receipts' / (LABEL + '.json')
    STATUS = PRIVATE / 'autonomy-status' / (LABEL + '.json')
    WORKER_RECOVERY = PRIVATE / 'worker-recovery' / (LABEL + '.json')
    REVIEWER_RECOVERY = PRIVATE / 'worker-recovery' / (LABEL + '-reviewer.json')


class WaitingApproval(Exception):
    pass


class WaitingBrowserAcceptance(Exception):
    pass


def command(*args, data=None, env=None):
    return subprocess.check_output(args, input=data, env=env).decode().strip()


def git(*args, data=None, env=None):
    return command('git', '-C', str(REPO), *args, data=data, env=env)


def json_command(*args):
    return json.loads(command(*args))


def status(stage, context, **details):
    save_receipt(STATUS, {'stage': stage, 'label': LABEL,
                          'issue_id': context['issue_id'], 'updated_at': time.time(),
                          **details})


def quality_failure(context, phase, source_sha, error, contract=None):
    """Durably escalate an exact HTTP contract failure, without claiming QA."""
    if not str(error).startswith('post-deploy '):
        raise error
    planning = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
    from start_eval import check_model_budget
    try:
        check_model_budget()
        budget_ready = True
    except (ValueError, OSError, subprocess.CalledProcessError):
        budget_ready = False
    existing = find_qa_incident(PRIVATE, context['issue_id'], LABEL)
    if existing and find_qa_cto_escalation(PRIVATE, existing['key']):
        # A durable CTO handoff owns the diagnosis. Do not wake the superseded
        # Tech Lead incident merely because model capacity returned.
        budget_ready = False
    incident = record_qa_incident(
        PRIVATE, cli, context=context, label=LABEL, phase=phase,
        source_sha=source_sha, error=error,
        techlead_id=planning['techlead'], budget_ready=budget_ready,
        parent_contract=contract)
    if context.get('durable_handoffs'):
        managed = managed_handoff(context)
        if managed and managed.get('state') and managed['state']['stage'] == 'test_revision_blocked':
            details = json.loads(managed['state']['data'])
            raise RecoveryEscalation('test_revision_blocked:' + details.get('reason', 'independent_review_required'))
        if managed and managed['route']['enabled']:
            from prepare_issue_base import broker_post
            broker_post('/v1/delivery-routes', {**managed['route'], 'enabled': False})
    return incident


def drive_qa_repair(incident, contract, *, stop_after_cto_dispatch=False):
    """Reconcile a diagnosed deployed failure into a new independent TDD run."""
    if not RUN_SPEC or 'key' not in incident:
        return {'stage': 'qa_replan_required', 'reason': 'legacy run has no pinned run spec'}
    if (incident['dispatch'] != 'techlead_started'
            and not find_qa_cto_escalation(PRIVATE, incident['key'])):
        return {'stage': 'budget_paused', 'incident_key': incident['key']}
    receipt = json.loads(RECEIPT.read_text())
    effective = receipt.get('effective_contract_sha256')
    if effective and effective != hashlib.sha256(json.dumps(
            contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest():
        return {'stage': 'qa_replan_required',
                'reason': 'effective reviewed contract differs from pinned parent'}
    from planning_intake import completed_output
    from prepare_issue_base import verified_main
    from start_eval import check_model_budget
    spec = {key: value for key, value in RUN_SPEC.items() if key != 'sha256'}
    def budget_available():
        try:
            check_model_budget()
            return True
        except (ValueError, OSError, subprocess.CalledProcessError):
            return False
    def escalate_cto(reason):
        planning = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
        return record_qa_cto_escalation(
            PRIVATE, cli, incident=incident, parent_contract=contract,
            cto_id=planning['cto'], reason=reason,
            budget_ready=budget_available())
    def diagnosis_output(issue_id, agent_id):
        completed = [run for run in cli('runs', issue_id)
                     if run.get('agent_id') == agent_id
                     and run.get('status') == 'completed']
        if len(completed) != 1:
            raise ValueError('QA diagnosis task identity drift')
        if incident['phase'] == 'browser':
            from portable_qa_evidence import confirm_reads
            try:
                confirm_reads(completed[0]['id'])
            except Exception as error:
                raise DiagnosisRejected('browser diagnosis lacks verified artifact reads',
                                        task_id=completed[0]['id']) from error
        result = completed[0].get('result')
        final = result.get('output') if isinstance(result, dict) else None
        if isinstance(final, str) and final.strip():
            return completed[0]['id'], final
        return completed_output(issue_id, agent_id, timeout=1)
    deadline = time.monotonic() + 1800
    while True:
        retry = find_qa_diagnosis_retry(PRIVATE, incident['key'])
        cto = find_qa_cto_escalation(PRIVATE, incident['key'])
        if cto:
            cto = escalate_cto(cto['reason'])
            if cto['dispatch'] == 'budget_paused':
                return {'stage': 'budget_paused', 'incident_key': incident['key'],
                        'cto_issue_id': cto['child_issue_id']}
            if cto['dispatch'] == 'cto_failed':
                return {'stage': 'cto_diagnosis_failed',
                        'cto_issue_id': cto['child_issue_id']}
            if stop_after_cto_dispatch and cto['dispatch'] == 'cto_started':
                # Operator-only fault injection stops after proving the real
                # handoff; it cannot accidentally dispatch a synthetic QA
                # expectation as a product repair.
                return {'stage': 'cto_handoff_observed',
                        'cto_issue_id': cto['child_issue_id']}
        elif retry:
            retry = record_qa_diagnosis_retry(
                PRIVATE, cli, incident=incident, parent_contract=contract,
                task_id=retry['rejected_task_id'],
                reason=retry['rejection_reason'],
                budget_ready=budget_available())
            if retry['dispatch'] == 'budget_paused':
                return {'stage': 'budget_paused', 'incident_key': incident['key'],
                        'retry_issue_id': retry['child_issue_id']}
            if retry['dispatch'] == 'retry_failed':
                cto = escalate_cto('Tech Lead diagnosis retry task failed')
                deadline = time.monotonic() + 1800
                continue
        try:
            result = resume_qa_repair(
                PRIVATE, incident, contract, spec, PROJECT, cli=cli,
                verified_sha=verified_main, budget_check=check_model_budget,
                output_reader=diagnosis_output,
                diagnosis_issue_id=(cto['child_issue_id'] if cto else
                                    retry['child_issue_id'] if retry else None),
                diagnosis_agent_id=cto['cto_id'] if cto else None)
        except DiagnosisRejected as error:
            if cto:
                return {'stage': 'cto_diagnosis_rejected', 'reason': str(error),
                        'cto_issue_id': cto['child_issue_id']}
            if retry:
                cto = escalate_cto('Second Tech Lead diagnosis rejected: ' + str(error)[:200])
                deadline = time.monotonic() + 1800
                continue
            created = record_qa_diagnosis_retry(
                PRIVATE, cli, incident=incident, parent_contract=contract,
                task_id=error.task_id, reason=str(error),
                budget_ready=budget_available())
            if created['dispatch'] == 'budget_paused':
                return {'stage': 'budget_paused', 'incident_key': incident['key'],
                        'retry_issue_id': created['child_issue_id']}
            continue
        if result['stage'] == 'diagnosis_blocked':
            if cto:
                return {'stage': 'cto_diagnosis_blocked', 'reason': result['reason'],
                        'cto_issue_id': cto['child_issue_id']}
            cto = escalate_cto('Tech Lead could not validate a safe local repair')
            deadline = time.monotonic() + 1800
            continue
        if result['stage'] != 'waiting_techlead_diagnosis':
            break
        if time.monotonic() >= deadline:
            if cto:
                return {'stage': 'cto_diagnosis_timeout',
                        'cto_issue_id': cto['child_issue_id']}
            cto = escalate_cto('Tech Lead diagnosis exceeded 30 minutes')
            deadline = time.monotonic() + 1800
            continue
        time.sleep(10)
    if result['stage'] == 'repair_dispatched':
        directory = PRIVATE / 'qa-repairs'
        env = {**os.environ,
               'DELIVERY_KIT_DELIVERY_CONTRACT': str(directory / (incident['key'] + '.contract.json')),
               'DELIVERY_KIT_RUN_SPEC': str(directory / (incident['key'] + '.run.json')),
               'DELIVERY_KIT_TEST_FIRST': '1'}
        child_started_at = time.time()
        child_run = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                   env=env, check=False)
        if child_run.returncode == 75:
            return {'stage': 'repair_controller_busy', 'label': result['label']}
        if child_run.returncode != 0:
            raise RuntimeError('QA repair controller exited ' + str(child_run.returncode))
        child_status_path = PRIVATE / 'autonomy-status' / (result['label'] + '.json')
        child_status = (json.loads(child_status_path.read_text())
                        if child_status_path.exists() else {})
        if (child_status.get('label') != result['label']
                or child_status.get('stage') != 'deployed_qa_passed'
                or child_status.get('updated_at', 0) < child_started_at):
            return {'stage': 'repair_incomplete', 'label': result['label'],
                    'reason': 'child controller did not freshly verify deployed QA',
                    'child_stage': child_status.get('stage')}
        child_path = PRIVATE / 'release-receipts' / (result['label'] + '.json')
        if not child_path.exists():
            return {'stage': 'repair_incomplete', 'label': result['label'],
                    'reason': 'child delivery receipt absent'}
        child = json.loads(child_path.read_text())
        child_contract = json.loads(Path(env['DELIVERY_KIT_DELIVERY_CONTRACT']).read_text())
        if (child.get('label') != result['label']
                or child.get('base_sha') != incident['source_sha']
                or child.get('contract_sha256') != hashlib.sha256(json.dumps(
                    child_contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()):
            raise ValueError('QA repair child delivery identity drift')
        if child.get('stage') != 'deployed_qa_passed':
            return {'stage': 'repair_incomplete', 'label': result['label'],
                    'reason': 'child did not pass deployed QA'}
        recovery = {'stage': 'qa_recovered_by_child', 'label': result['label'],
                'merge_sha': child['merge_sha'], 'pr_url': child['pr_url'],
                'qa_url': child['deployment']['url']}
        recovery['board'] = publish_qa_recovery(cli, incident, retry, child,
                                                recovery=recovery, cto=cto)
        save_receipt(PRIVATE / 'qa-recoveries' / (incident['parent_issue_id'] + '.json'),
                     {'incident': incident, 'recovery': recovery,
                      'child_issue_id': child['issue_id']})
        return recovery
    return result


def read_context(contract):
    path = PRIVATE / ('portable-context.json' if not RUN_SPEC and LABEL == 'PORT-4'
                      else 'portable-context-' + LABEL + '.json')
    context = json.loads(path.read_text())
    digest = hashlib.sha256(json.dumps(contract, sort_keys=True,
                            separators=(',', ':')).encode()).hexdigest()
    if (context['label'] != LABEL or context['contract_sha256'] != digest
            or not re.fullmatch(r'[0-9a-f]{40}', context['base_sha'])):
        raise ValueError('portable context identity mismatch')
    if RUN_SPEC and context.get('run_spec_sha256') != RUN_SPEC['sha256']:
        raise ValueError('portable run spec changed after dispatch')
    return context


def managed_handoff(context):
    query = ('import sqlite3,json,sys; c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
             'c.row_factory=sqlite3.Row; '
             'exists=c.execute("SELECT 1 FROM sqlite_master WHERE name=\'delivery_routes\'").fetchone(); '
             'route=c.execute("SELECT config FROM delivery_routes WHERE issue_id=?",(sys.argv[1],)).fetchone() if exists else None; '
             'state=c.execute("SELECT stage,owner,data,updated,source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1",(sys.argv[1],)).fetchone() if route else None; '
             'print(json.dumps({"route":json.loads(route[0]),"state":dict(state) if state else None} if route else None))')
    return json.loads(command('docker', 'exec', INSTANCE + '-execution-broker-1',
                              'python', '-c', query, context['issue_id']))


def revalidated_delivery(previous, current):
    """Only replace review identity, backed by the exact maintenance ledger."""
    if ({k: v for k, v in previous.items() if k != 'review_task'} !=
            {k: v for k, v in current.items() if k != 'review_task'}):
        raise ValueError('approved portable delivery changed')
    query = ('import sqlite3,json,sys; c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
        'r=c.execute("SELECT payload FROM review_policy_revalidations WHERE review_task=?",(sys.argv[1],)).fetchone(); '
        'old=c.execute("SELECT status FROM reviews WHERE review_task_id=?",(sys.argv[1],)).fetchone(); '
        'new=c.execute("SELECT status,source_task_id,manifest_sha256,reviewer_agent_id FROM reviews WHERE review_task_id=?",(sys.argv[2],)).fetchone(); '
        'print(json.dumps({"payload":json.loads(r[0]),"old_status":old[0],"new_status":new[0],'
        '"new_source":new[1],"new_manifest":new[2],"new_reviewer":new[3]} if r and old and new else None))')
    proof = json.loads(command('docker', 'exec', INSTANCE + '-execution-broker-1',
                              'python', '-c', query, previous['review_task'], current['review_task']))
    if (not proof or proof['old_status'] != 'policy_invalidated' or proof['new_status'] != 'approved'
            or proof['payload']['review_task'] != previous['review_task']
            or proof['payload']['source_task'] != current['source_task']
            or proof['payload']['manifest_sha256'] != current['manifest_sha256']
            or proof['new_source'] != current['source_task']
            or proof['new_manifest'] != current['manifest_sha256']
            or proof['new_reviewer'] != current['reviewer']):
        raise ValueError('approved review replacement lacks exact policy revalidation')
    return previous


def approved(context):
    if context.get('durable_handoffs'):
        managed = managed_handoff(context)
        if managed and managed.get('state') and managed['state']['stage'] == 'test_revision_blocked':
            details = json.loads(managed['state']['data'])
            raise RecoveryEscalation('test_revision_blocked:' + details.get('reason', 'independent_review_required'))
        if managed and managed.get('state') and managed['state']['stage'] == 'test_revision_required':
            raise RecoveryEscalation('test_revision_required:independent_new_test_revision_pending')
        if managed and managed.get('state') and managed['state']['stage'] == 'test_first_blocked':
            raise RecoveryEscalation('test_first_blocked:' + json.loads(managed['state']['data']).get('error', 'technical_replanning_required'))
        if managed and managed.get('state') and managed['state']['stage'] == 'technical_decision_required':
            state, route = managed['state'], managed['route']
            details = json.loads(state['data'])
            # Broker records the rejected first tests-only snapshot before its
            # next tick dispatches the one allowed path correction. Do not turn
            # this short, durable transition into a terminal operator exit.
            # Repeated failures and stale transitions still fail closed.
            age = time.time() - state.get('updated', 0)
            restart = details.get('host_restart_recovery') or {}
            if (route.get('test_first') and details.get('phase') == 'test_first'
                    and details.get('error') == 'host_restart_diagnosis_required'
                    and restart.get('request',{}).get('issue_id') == context['issue_id']
                    and restart.get('request',{}).get('source_task') == state.get('source_task')
                    and restart.get('proof',{}).get('baseline_unchanged') is True
                    and restart.get('author_retry_authorized') is False
                    and 0 <= age < 30):
                raise WaitingApproval('bounded broker host-restart diagnosis transition')
            if (route.get('test_first') and details.get('phase') == 'test_first'
                    and details.get('error') in ('test_author_execution_failed',
                                                  'test_author_execution_cancelled',
                                                  'ValueError:Red must be an executed failing test suite',
                                                  'ValueError:Red did not fail in a new test method',
                                                  'ValueError:Red failure summary missing',
                                                  'ValueError:Red test count missing')
                    and 0 <= age < 30):
                raise WaitingApproval('bounded broker CTO diagnosis transition')
            if (route.get('test_first') and len(route.get('test_first_files', [])) == 1
                    and details.get('phase') == 'test_first'
                    and details.get('error') == 'ValueError:test-first test path mismatch'
                    and 0 <= age < 30):
                runs = cli('runs', context['issue_id'])
                completed = [r for r in runs if r.get('agent_id') == route['author']
                             and r.get('status') == 'completed']
                if len(completed) == 1 and completed[0]['id'] == details.get('source_task'):
                    raise WaitingApproval('bounded broker test-path correction transition')
            raise RecoveryEscalation('technical_decision_required:' + details.get('error', 'technical_replanning_required'))
        if not managed or not managed['route']['enabled'] or not managed['state'] or managed['state']['stage'] != 'approved':
            raise WaitingApproval('durable handoff pending')
    suffix = '-v2' if LABEL in ('PORT-7', 'PORT-8', 'PORT-9') else ''
    author_file = RUN_SPEC['implementer_registry'] if RUN_SPEC else 'portable-implementer' + suffix + '.json'
    reviewer_file = RUN_SPEC['reviewer_registry'] if RUN_SPEC else 'portable-reviewer' + suffix + '.json'
    author = json.loads((PRIVATE / author_file).read_text())['agent_id']
    author_runs = [run for run in cli('runs', context['issue_id'])
                   if run.get('agent_id') == author]
    if author_runs:
        latest = max(author_runs, key=lambda run: (run.get('created_at') or '', run['id']))
        result = latest.get('result')
        output = result.get('output') if isinstance(result, dict) else None
        if (latest.get('status') == 'completed' and isinstance(output, str)
                and 'No visible answer was produced.' in output
                and 'output-token limit' in output):
            raise RecoveryEscalation('implementation_model_output_limit')
    try:
        return approved_submission(context['issue_id'], author_file, reviewer_file)
    except ValueError as error:
        if str(error) in ('no completed implementation', 'expected one approved exact revision'):
            reviewer = json.loads((PRIVATE / reviewer_file).read_text())['agent_id']
            runs = [run for run in cli('runs', context['issue_id'])
                    if run.get('agent_id') == reviewer]
            if runs:
                latest = max(runs, key=lambda run: (run.get('created_at') or '', run['id']))
                query = ('import json,sqlite3,sys; '
                         'c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
                         'r=c.execute("SELECT reason,status FROM review_incidents '
                         'WHERE review_task_id=?",(sys.argv[1],)).fetchone(); '
                         'h=c.execute("SELECT error_type,attempts FROM change_handoff_failures '
                         'WHERE review_task_id=?",(sys.argv[1],)).fetchone(); '
                         'print(json.dumps({"incident":r,"handoff":h}))')
                state = json.loads(command('docker', 'exec', INSTANCE + '-execution-broker-1',
                                           'python3', '-c', query, latest['id']))
                incident, handoff = state['incident'], state['handoff']
                if incident and incident[1] in ('escalation_required', 'infrastructure_model_limit'):
                    raise ValueError('portable review escalation: ' + incident[0]) from None
                if handoff and handoff[1] >= 2:
                    raise ValueError('portable handoff escalation: ' + handoff[0]) from None
            raise WaitingApproval(str(error)) from None
        raise


def recover_implementation_worker(context):
    if context.get('durable_handoffs'):
        managed = managed_handoff(context)
        if not managed:
            raise RecoveryEscalation('durable_handoff_registration_missing')
        return 'handoff:' + (managed['state']['stage'] if managed['state'] else 'waiting_author')
    suffix = '-v2' if LABEL in ('PORT-7', 'PORT-8', 'PORT-9') else ''
    author_file = RUN_SPEC['implementer_registry'] if RUN_SPEC else 'portable-implementer' + suffix + '.json'
    reviewer_file = RUN_SPEC['reviewer_registry'] if RUN_SPEC else 'portable-reviewer' + suffix + '.json'
    implementer = json.loads((PRIVATE / author_file).read_text())['agent_id']
    reviewer = json.loads((PRIVATE / reviewer_file).read_text())['agent_id']
    issue = cli('get', context['issue_id'])
    if issue.get('id') != context['issue_id']:
        raise RecoveryEscalation('issue_identity_mismatch')
    runs = cli('runs', context['issue_id'])
    if not isinstance(runs, list) or any(run.get('issue_id') != context['issue_id'] for run in runs):
        raise RecoveryEscalation('issue_run_identity_mismatch')
    author_runs = [run for run in runs if run.get('agent_id') == implementer]
    reviewer_runs = [run for run in runs if run.get('agent_id') == reviewer]
    latest_author = max(author_runs, key=lambda run: (run.get('created_at') or '', run['id'])) if author_runs else None
    latest_reviewer = max(reviewer_runs, key=lambda run: (run.get('created_at') or '', run['id'])) if reviewer_runs else None
    if latest_author and (not latest_reviewer or
                          (latest_author.get('created_at') or '', latest_author['id']) >
                          (latest_reviewer.get('created_at') or '', latest_reviewer['id'])):
        return reconcile_worker(context['issue_id'], implementer, runs, issue['status'],
                                WORKER_RECOVERY, lambda issue_id: cli('rerun', issue_id))
    if latest_reviewer and latest_reviewer.get('status') == 'failed':
        latest_review = latest_reviewer
        verified_loss = False
        if latest_review.get('failure_reason') == 'agent_error.provider_server_error':
            query = ('import json,sqlite3,sys; '
                     'c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
                     'r=c.execute("SELECT l.status FROM leases l JOIN native_bindings n '
                     'USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?",'
                     '(sys.argv[1],sys.argv[2],sys.argv[3])).fetchall(); '
                     'print(json.dumps(r))')
            leases = json.loads(command('docker', 'exec', INSTANCE + '-execution-broker-1',
                                        'python', '-c', query, latest_review['id'], reviewer,
                                        context['issue_id']))
            verified_loss = leases == [['failed']] or leases == [['interrupted']] or leases == [['lost']]
        def create_review_wakeup(issue_id, agent_id, task_id, marker):
            original = [w for w in cli('wakeup', 'list', issue_id)
                        if w.get('agent_id') == agent_id
                        and w.get('filter_agent_id') == implementer
                        and w.get('event_types') == ['task.completed']]
            if len(original) != 1 or not original[0].get('instruction'):
                raise RecoveryEscalation('original_review_instruction_missing')
            return cli('wakeup', 'create', issue_id, '--agent-id', agent_id,
                       '--event', 'task.failed', '--task-id', task_id, '--mode', 'once',
                       '--instruction', marker + '. ' + original[0]['instruction'])
        return reconcile_reviewer(
            context['issue_id'], implementer, reviewer, runs, issue['status'],
            REVIEWER_RECOVERY, lambda issue_id: cli('wakeup', 'list', issue_id),
            create_review_wakeup, worker_loss_verified=verified_loss)
    return reconcile_worker(context['issue_id'], implementer, runs, issue['status'],
                            WORKER_RECOVERY, lambda issue_id: cli('rerun', issue_id))


def snapshot_files(delivery, context, contract, after_merge=False):
    with tempfile.TemporaryDirectory(prefix='delivery-kit-portable-snapshot-') as directory:
        path = Path(directory)
        export_snapshot(delivery, path)
        result = preflight(REPO, context['base_sha'], path, contract,
                           allow_advanced_main=after_merge)
        if result['manifest_sha256'] != delivery['manifest_sha256']:
            raise ValueError('approved manifest identity mismatch')
        tests = run_frozen_tests(path, contract)
        if tests['status'] != 'passed':
            raise ValueError('frozen tests did not pass')
        names = json.loads((path / 'manifest.json').read_text())['files']
        return {name: (path / name).read_bytes() for name in names}, result, tests


def verify_commit(sha, base, files, contract, predecessor=None):
    if git('rev-parse', sha + '^') != (predecessor or base):
        raise ValueError('reviewed branch parent changed')
    changed = set(git('diff', '--name-only', base, sha).splitlines())
    if not changed or not changed <= set(contract['editable_files']):
        raise ValueError('reviewed branch changed protected or undeclared files')
    for name, content in files.items():
        if subprocess.check_output(['git', '-C', str(REPO), 'show', sha + ':' + name]) != content:
            raise ValueError('reviewed branch differs from snapshot: ' + name)


def ensure_branch(base, files, contract, predecessor=None):
    ref = 'refs/heads/' + BRANCH
    local = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--verify', ref],
                           capture_output=True, text=True)
    if local.returncode == 0:
        head = local.stdout.strip()
    else:
        remote = git('ls-remote', 'origin', ref)
        if remote:
            head = remote.split()[0]
            subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', head], check=True)
            git('update-ref', ref, head, '0' * 40)
        else:
            if git('rev-parse', 'main') != base:
                raise ValueError('main moved before branch creation')
            with tempfile.TemporaryDirectory(prefix='delivery-kit-portable-index-') as directory:
                env = {**os.environ, 'GIT_INDEX_FILE': str(Path(directory) / 'index')}
                git('read-tree', base, env=env)
                for name in contract['editable_files']:
                    content = files[name]
                    blob = git('hash-object', '-w', '--stdin', data=content)
                    git('update-index', '--add', '--cacheinfo', f'100644,{blob},{name}', env=env)
                tree = git('write-tree', env=env)
            head = git('commit-tree', tree, '-p', base,
                       '-m', LABEL + ': reviewed delivery')
            git('update-ref', ref, head, '0' * 40)
    if predecessor and head == predecessor:
        if subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor', base, predecessor],
                          capture_output=True).returncode:
            raise ValueError('candidate predecessor does not descend from original base')
        from portable_candidate_recovery import verify_preserved_tests
        before = {name: subprocess.check_output(['git', '-C', str(REPO), 'show', predecessor + ':' + name])
                  for name in files}
        verify_preserved_tests(before, files, contract)
        with tempfile.TemporaryDirectory(prefix='delivery-kit-candidate-index-') as directory:
            env = {**os.environ, 'GIT_INDEX_FILE': str(Path(directory) / 'index')}
            git('read-tree', predecessor, env=env)
            for name in contract['editable_files']:
                blob = git('hash-object', '-w', '--stdin', data=files[name])
                git('update-index', '--add', '--cacheinfo', f'100644,{blob},{name}', env=env)
            tree = git('write-tree', env=env)
        head = git('commit-tree', tree, '-p', predecessor, '-m', LABEL + ': reviewed candidate correction')
        git('update-ref', ref, head, predecessor)
    verify_commit(head, base, files, contract, predecessor=predecessor)
    remote = git('ls-remote', 'origin', ref)
    if remote and remote.split()[0] not in (head, predecessor):
        raise ValueError('remote reviewed branch moved')
    if not remote or remote.split()[0] != head:
        subprocess.run(['git', '-C', str(REPO), 'push', 'origin', ref + ':' + ref], check=True)
    return head


def ensure_pr(head, base, delivery):
    prs = json_command('gh', 'pr', 'list', '-R', REPOSITORY, '--state', 'all',
                       '--head', BRANCH, '--json',
                       'number,state,headRefOid,baseRefOid,mergeCommit,url')
    if len(prs) > 1:
        raise ValueError('duplicate portable PRs')
    if not prs:
        body = (f'Approved frozen delivery.\n'
                f'Source task: {delivery["source_task"]}\n'
                f'Independent review: {delivery["review_task"]}\n'
                f'Manifest SHA-256: {delivery["manifest_sha256"]}\n'
                'Exact CI and same-commit local QA are required.')
        command('gh', 'pr', 'create', '-R', REPOSITORY, '--base', 'main', '--head', BRANCH,
                '--title', LABEL + ': reviewed delivery', '--body', body)
        prs = json_command('gh', 'pr', 'list', '-R', REPOSITORY, '--state', 'all',
                           '--head', BRANCH, '--json',
                           'number,state,headRefOid,baseRefOid,mergeCommit,url')
    if len(prs) != 1 or prs[0]['headRefOid'] != head or prs[0]['baseRefOid'] != base:
        raise ValueError('portable PR identity mismatch')
    return prs[0]


def wait_ci(number, head, base, timeout=180):
    deadline = time.monotonic() + timeout
    recover_after = time.monotonic() + 120
    recovery_checked = False
    while time.monotonic() < deadline:
        item = json_command('gh', 'pr', 'view', str(number), '-R', REPOSITORY,
                            '--json', 'state,headRefOid,baseRefOid,mergeStateStatus,statusCheckRollup')
        if item['state'] != 'OPEN' or item['headRefOid'] != head or item['baseRefOid'] != base:
            raise ValueError('portable PR moved during CI')
        checks = [c for c in item['statusCheckRollup'] if c.get('name') == 'ci']
        if any(c.get('conclusion') not in ('SUCCESS', '') for c in checks):
            raise ValueError('portable PR CI failed')
        if len(checks) == 1 and checks[0].get('conclusion') == 'SUCCESS' and item['mergeStateStatus'] == 'CLEAN':
            return
        if not item['statusCheckRollup'] and not recovery_checked and time.monotonic() >= recover_after:
            from missing_ci_recovery import recover
            recovery_checked = True
            recover(PRIVATE, REPOSITORY, number, head, base)
        time.sleep(5)
    raise TimeoutError('portable PR CI deadline')


def ensure_merge(pr, head, base, files):
    if pr['state'] == 'OPEN':
        wait_ci(pr['number'], head, base)
        if git('rev-parse', 'main') != base:
            raise ValueError('main moved before merge')
        subprocess.run(['gh', 'pr', 'merge', str(pr['number']), '-R', REPOSITORY,
                        '--squash'], check=True)
    merged = json_command('gh', 'pr', 'view', str(pr['number']), '-R', REPOSITORY,
                          '--json', 'state,mergeCommit,headRefOid,baseRefOid')
    if (merged['state'] != 'MERGED' or merged['headRefOid'] != head
            or merged['baseRefOid'] != base or not merged['mergeCommit']):
        raise ValueError('portable merge identity mismatch')
    sha = merged['mergeCommit']['oid']
    subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', 'main'], check=True)
    if git('branch', '--show-current') != 'main':
        raise ValueError('portable checkout is not main')
    if git('rev-parse', 'main') != sha:
        subprocess.run(['git', '-C', str(REPO), 'merge', '--ff-only', 'origin/main'], check=True)
    for name, content in files.items():
        if subprocess.check_output(['git', '-C', str(REPO), 'show', sha + ':' + name]) != content:
            raise ValueError('merged portable bytes differ from snapshot')
    return sha


def wait_main_ci(sha, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = json_command('gh', 'api', 'repos/' + REPOSITORY + '/actions/runs?head_sha=' + sha)
        matching = [run for run in runs.get('workflow_runs', [])
                    if run.get('head_sha') == sha and run.get('event') == 'push'
                    and run.get('path') == '.github/workflows/ci.yml'
                    and run.get('conclusion') == 'success']
        if matching:
            return matching[0]['html_url']
        time.sleep(5)
    raise TimeoutError('portable main CI deadline')


def build_delivery_image(sha, contract, *, dockerfile=None, image_name=None):
    dockerfile = dockerfile or DOCKERFILE
    image_name = image_name or IMAGE_NAME
    with tempfile.TemporaryDirectory(prefix='delivery-kit-portable-build-') as directory:
        context = Path(directory)
        from portable_contract import validate_delivery_files
        tracked = git('ls-tree', '-r', '--name-only', sha).splitlines()
        names = validate_delivery_files(contract, set(tracked) & set(contract['files']))
        for name in names:
            target = context / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(
                ['git', '-C', str(REPO), 'show', sha + ':' + name]))
        tag = image_name + ':' + sha[:12]
        subprocess.run(['docker', 'build', '--pull=false', '--network', 'none',
                        '-f', str(context / dockerfile), '--build-arg', 'SOURCE_SHA=' + sha,
                        '-t', tag, str(context)], check=True, stdout=subprocess.DEVNULL)
    return tag


def runtime_env_args():
    """Pass only bounded public values from the pinned operator run spec."""
    return [part for name, value in sorted((RUN_SPEC or {}).get('runtime_env', {}).items())
            for part in ('--env', name + '=' + value)]


def verify_candidate_before_pr(sha, contract):
    """Run contract HTTP QA on the reviewed commit before any PR or merge."""
    name = CONTAINER + '-candidate'
    if subprocess.run(['docker', 'inspect', name], capture_output=True).returncode == 0:
        raise ValueError('stale candidate QA container requires operator diagnosis')
    tag = build_delivery_image(sha, contract)
    subprocess.run(['docker', 'run', '-d', '--rm', '--name', name, '--network', 'bridge',
                    *docker_group_args('candidate'),
                    '--publish', '127.0.0.1::' + str(CONTAINER_PORT), '--read-only',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=8m', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--memory', '128m',
                    '--cpus', '0.5', '--pids-limit', '64', '--restart', 'no',
                    *runtime_env_args(), tag],
                   check=True, stdout=subprocess.DEVNULL)
    try:
        details = json_command('docker', 'inspect', name)
        bindings = details[0]['NetworkSettings']['Ports'].get(str(CONTAINER_PORT) + '/tcp')
        if (not isinstance(bindings, list) or len(bindings) != 1
                or bindings[0].get('HostIp') != '127.0.0.1'
                or not str(bindings[0].get('HostPort', '')).isdigit()):
            raise ValueError('candidate QA port binding mismatch')
        url = 'http://127.0.0.1:' + bindings[0]['HostPort']
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                return verify_docker_deployment(name, url, sha, contract)
            except (OSError, ConnectionError):
                time.sleep(1)
        raise TimeoutError('candidate local QA deadline')
    finally:
        subprocess.run(['docker', 'stop', '--time', '2', name],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_deployed(sha, contract):
    url = 'http://127.0.0.1:' + str(QA_PORT)
    existing = subprocess.run(['docker', 'inspect', CONTAINER], capture_output=True)
    if existing.returncode == 0:
        return verify_docker_deployment(CONTAINER, url, sha, contract)
    tag = build_delivery_image(sha, contract)
    subprocess.run(['docker', 'run', '-d', '--name', CONTAINER, '--network', 'bridge',
                    *docker_group_args('app', kind='homologation'),
                    '--publish', '127.0.0.1:' + str(QA_PORT) + ':' + str(CONTAINER_PORT), '--read-only',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=8m', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--memory', '128m',
                    '--cpus', '0.5', '--pids-limit', '64', '--restart', 'no',
                    *runtime_env_args(), tag],
                   check=True, stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            return verify_docker_deployment(CONTAINER, url, sha, contract)
        except (OSError, ConnectionError):
            time.sleep(1)
    raise TimeoutError('portable local QA deadline')


def publish_board(context, receipt):
    issue_id = context['issue_id']
    fields = {'delivery_receipt_sha': receipt['merge_sha'],
              'delivery_pr_url': receipt['pr_url'],
              'delivery_main_ci_url': receipt['main_ci_run'],
              'delivery_qa_url': receipt['deployment']['url']}
    existing = cli('metadata', 'list', issue_id)
    if not isinstance(existing, dict):
        raise ValueError('portable issue metadata invalid')
    if RUN_SPEC and RUN_SPEC.get('browser_qa'):
        # Revalidate the durable exact-image evidence even if someone has set
        # browser_acceptance metadata by hand. Metadata alone cannot pass QA.
        from portable_browser_qa import qualify
        browser = qualify(config=RUN_SPEC['browser_qa'], deployed_container=CONTAINER,
                          source_sha=receipt['merge_sha'],
                          evidence_dir=PRIVATE / 'browser-acceptance' / LABEL,
                          runtime_env=RUN_SPEC.get('runtime_env', {}))
        receipt['browser_qa'] = browser
        save_receipt(RECEIPT, receipt)
        value = 'passed:' + receipt['merge_sha']
        if existing.get('browser_acceptance') != value:
            cli('metadata', 'set', issue_id, '--key', 'browser_acceptance',
                '--value', value, '--type', 'string')
            existing['browser_acceptance'] = value
    if ('browser_acceptance' in existing and
            existing['browser_acceptance'] != 'passed:' + receipt['merge_sha']):
        # A VM test or HTTP probe must never stand in for this required
        # exact-deployment browser acceptance. No worker is redispatched here.
        raise WaitingBrowserAcceptance('exact-SHA browser acceptance pending')
    for key, value in fields.items():
        if key in existing and existing[key] != value:
            raise ValueError('portable issue metadata drift: ' + key)
        if key not in existing:
            cli('metadata', 'set', issue_id, '--key', key, '--value', value,
                '--type', 'string')
    if existing.get('execution_gate') != 'deployed_qa_passed':
        cli('metadata', 'set', issue_id, '--key', 'execution_gate',
            '--value', 'deployed_qa_passed', '--type', 'string')
    if existing.get('delivery_handoff'):
        handoff = json.loads(existing['delivery_handoff'])
        if (handoff.get('stage') != 'approved' or
                handoff.get('source_task') != receipt['delivery']['source_task']):
            raise ValueError('published handoff differs from approved delivery')
        handoff.update(next_action='dependent_cards', publication='deployed_qa_passed')
        cli('metadata', 'set', issue_id, '--key', 'delivery_handoff',
            '--value', json.dumps(handoff, sort_keys=True, separators=(',', ':')),
            '--type', 'string')
    item = cli('get', issue_id)
    if item['status'] != 'done':
        cli('status', issue_id, 'done', '--no-start')
    return {'status': 'done', 'storage': 'issue_metadata'}


def detach_completed_candidate_author(context, delivery):
    """Prevent native child-completion wakeups from restarting a reviewed author.

    The controller owns publication now; author identity remains in the durable
    receipt, not in an executable parent assignment. Fail closed on ownership
    drift rather than unassigning another person's work.
    """
    parent = cli('get', context['issue_id'])
    if parent.get('assignee_id') is None:
        return
    if parent['assignee_id'] != delivery['author']:
        raise ValueError('candidate publication assignee drift')
    cli('metadata', 'set', context['issue_id'], '--key', 'delivery_author',
        '--value', delivery['author'], '--type', 'string')
    cli('assign', context['issue_id'], '--unassign', '--no-start')
    if cli('get', context['issue_id']).get('assignee_id') is not None:
        raise ValueError('candidate author detachment not confirmed')


def reconcile(context, contract):
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        if (receipt['issue_id'] != context['issue_id'] or receipt['base_sha'] != context['base_sha']
                or receipt['contract_sha256'] != context['contract_sha256']):
            raise ValueError('portable release receipt drift')
    else:
        receipt = {**context, 'branch': BRANCH}
    prior = receipt.get('qa_incident') or find_qa_incident(PRIVATE, context['issue_id'], LABEL)
    if prior and prior['phase'] == 'browser':
        from portable_browser_qa import scenario_resolution
        resolution = scenario_resolution(PRIVATE, prior)
        if resolution:
            receipt['browser_scenario_recovery'] = resolution
            # Preserve qa_incident and its failed attempt. This receipt merely
            # allows the normal exact-delivery gates to run again, not a merge,
            # test waiver or direct board completion.
            prior = None
    repair = receipt.get('candidate_recovery')
    if repair and repair.get('status') == 'resolved':
        prior = None
    candidate_delivery = None
    if prior and prior['phase'] == 'candidate':
        from portable_candidate_recovery import correction_payload
        if not repair:
            runs = [r for r in cli('runs', prior['child_issue_id'])
                    if r.get('agent_id') == prior['techlead_id'] and r.get('status') == 'completed']
            if not runs:
                raise WaitingApproval('candidate QA diagnosis pending')
            if len(runs) != 1:
                raise ValueError('candidate QA diagnosis task identity drift')
            payload = correction_payload(context, receipt, prior, contract,
                                         (runs[0].get('result') or {}).get('output', ''))
            repair = {'status': 'starting', 'payload': payload,
                      'original_delivery': receipt['delivery'], 'predecessor': prior['source_sha'],
                      'incident_issue': prior['child_issue_id'], 'diagnosis_task': runs[0]['id']}
            receipt['candidate_recovery'] = repair
            save_receipt(RECEIPT, receipt)
        if repair['status'] == 'blocked':
            raise RecoveryEscalation('candidate_correction_failed:' + repair['error'])
        if repair['status'] == 'starting':
            broker_post('/v1/candidate-corrections', repair['payload'])
            repair['status'] = 'awaiting_review'
            save_receipt(RECEIPT, receipt)
        candidate_delivery = approved(context)
        if candidate_delivery['source_task'] == repair['original_delivery']['source_task']:
            raise WaitingApproval('new independent candidate review required')
        if repair['status'] == 'awaiting_review':
            receipt['candidate_history'] = [{k: v for k, v in receipt.items()
                                             if k not in ('candidate_recovery', 'candidate_history')}]
            receipt['delivery'] = candidate_delivery
            for field in ('head_sha', 'candidate_qa', 'qa_incident'):
                receipt.pop(field, None)
            repair['status'] = 'reviewed'
            save_receipt(RECEIPT, receipt)
        prior = None
    if prior:
        parent = cli('get', context['issue_id'])
        if parent['status'] == 'cancelled':
            metadata = cli('metadata', 'list', context['issue_id'])
            if (metadata.get('execution_gate') != 'qa_recovered_by_child'
                    or metadata.get('qa_incident_issue_id') != prior['child_issue_id']
                    or metadata.get('qa_failed_source_sha') != prior['source_sha']):
                raise ValueError('cancelled QA parent lacks exact recovery evidence')
            raise QualityBlocked(prior)
        incident = quality_failure(context, prior['phase'], prior['source_sha'],
                                   ValueError(prior['category']), contract)
        if incident['key'] != prior['key']:
            raise ValueError('QA incident receipt drift')
        receipt['qa_incident'] = incident
        save_receipt(RECEIPT, receipt)
        raise QualityBlocked(incident)
    delivery = candidate_delivery or approved(context)
    recovery_proof = qualify_remediation_delivery(command, INSTANCE, context, delivery,
        previous=receipt.get('remediation_delivery'))
    if context.get('durable_handoffs'):
        query = ('import sqlite3,json,sys; c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
                 'r=c.execute("SELECT r.body FROM task_contracts t JOIN contract_revisions r USING(decision_task) WHERE t.task_id=?",(sys.argv[1],)).fetchone(); print(r[0] if r else "null")')
        revised = json.loads(command('docker', 'exec', INSTANCE + '-execution-broker-1', 'python', '-c', query, delivery['source_task']))
        if revised:
            from broker.contract_revision import revised as validate_revision
            from portable_contract import required_files
            baseline = git('ls-tree', '-r', '--name-only', context['base_sha']).splitlines()
            optional = sorted(required_files(contract) - required_files(revised))
            if validate_revision(contract, baseline, optional) != revised:
                raise ValueError('unqualified effective contract revision')
            contract = revised
            receipt['effective_contract_sha256'] = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if receipt.get('delivery') and receipt['delivery'] != delivery:
        previous = revalidated_delivery(receipt['delivery'], delivery)
        receipt.setdefault('review_revalidation_history', []).append(previous)
        receipt['operator_assisted'] = True
        if receipt.get('merge_sha'):
            receipt['merge_preceded_policy_revalidation'] = True
    receipt['delivery'] = delivery
    if recovery_proof is not None:
        receipt['remediation_delivery'] = recovery_proof
    files, preflight_result, tests = snapshot_files(
        delivery, context, contract, after_merge=bool(receipt.get('merge_sha')))
    receipt['preflight'] = preflight_result
    receipt['frozen_tests'] = tests
    save_receipt(RECEIPT, receipt)
    if os.environ.get('DELIVERY_KIT_FAULT_AFTER_SNAPSHOT') == '1' and not receipt.get('head_sha'):
        status('fault_injected_after_snapshot', context, owner='controller',
               manifest_sha256=delivery['manifest_sha256'])
        os._exit(73)
    require_access()
    head = ensure_branch(context['base_sha'], files, contract,
                         predecessor=repair['predecessor'] if repair else None)
    if receipt.get('head_sha') and receipt['head_sha'] != head:
        raise ValueError('portable reviewed branch moved')
    receipt['head_sha'] = head
    save_receipt(RECEIPT, receipt)
    if not receipt.get('merge_sha') and not receipt.get('candidate_qa'):
        try:
            receipt['candidate_qa'] = verify_candidate_before_pr(head, contract)
        except ValueError as error:
            if repair:
                repair.update(status='blocked', error=str(error)[:300])
                save_receipt(RECEIPT, receipt)
                managed = managed_handoff(context)
                if managed and managed['route']['enabled']:
                    broker_post('/v1/delivery-routes', {**managed['route'], 'enabled': False})
                raise RecoveryEscalation('candidate_correction_failed:' + str(error)) from error
            incident = quality_failure(context, 'candidate', head, error, contract)
            receipt['qa_incident'] = incident
            save_receipt(RECEIPT, receipt)
            raise QualityBlocked(incident) from error
        save_receipt(RECEIPT, receipt)
    if repair and repair['status'] != 'resolved':
        # --no-start on the child status only controls that child's execution.
        # Multica may still wake the assigned PARENT on sub-issue completion.
        # Detach before publishing resolution, and retain the receipt identity.
        detach_completed_candidate_author(context, delivery)
        repair.update(status='resolved', corrected_sha=head,
                      corrected_manifest_sha256=delivery['manifest_sha256'])
        save_receipt(RECEIPT, receipt)
        cli('metadata', 'set', repair['incident_issue'], '--key', 'candidate_correction_sha',
            '--value', head, '--type', 'string')
        cli('status', repair['incident_issue'], 'done', '--no-start')
    pr = ensure_pr(head, context['base_sha'], delivery)
    if receipt.get('pr_url') and receipt['pr_url'] != pr['url']:
        raise ValueError('portable PR changed')
    receipt.update(pr_number=pr['number'], pr_url=pr['url'])
    save_receipt(RECEIPT, receipt)
    if recovery_proof is not None:
        if approved(context) != delivery:
            raise ValueError('recovery delivery changed before merge')
        qualify_remediation_delivery(command, INSTANCE, context, delivery, previous=recovery_proof)
    sha = ensure_merge(pr, head, context['base_sha'], files)
    if receipt.get('merge_sha') and receipt['merge_sha'] != sha:
        raise ValueError('portable merge changed')
    receipt['merge_sha'] = sha
    save_receipt(RECEIPT, receipt)
    receipt['main_ci_run'] = wait_main_ci(sha)
    save_receipt(RECEIPT, receipt)
    if recovery_proof is not None:
        if approved(context) != delivery:
            raise ValueError('recovery delivery changed before deployment')
        qualify_remediation_delivery(command, INSTANCE, context, delivery, previous=recovery_proof)
    try:
        receipt['deployment'] = ensure_deployed(sha, contract)
    except ValueError as error:
        incident = quality_failure(context, 'deployed', sha, error, contract)
        receipt['qa_incident'] = incident
        save_receipt(RECEIPT, receipt)
        raise QualityBlocked(incident) from error
    save_receipt(RECEIPT, receipt)
    try:
        receipt['board'] = publish_board(context, receipt)
    except ValueError as error:
        if not str(error).startswith('post-deploy browser QA '):
            raise
        incident = quality_failure(context, 'browser', sha, error, contract)
        receipt['qa_incident'] = incident
        save_receipt(RECEIPT, receipt)
        raise QualityBlocked(incident) from error
    receipt['stage'] = 'deployed_qa_passed'
    save_receipt(RECEIPT, receipt)
    return receipt


def run_controller(contract=None):
    contract = contract or from_environment()
    configure_run(contract)
    context = read_context(contract)
    failures = {}
    waiting_since = time.monotonic()
    while True:
        try:
            receipt = reconcile(context, contract)
            status('deployed_qa_passed', context, pr_url=receipt['pr_url'],
                   merge_sha=receipt['merge_sha'], qa_url=receipt['deployment']['url'])
            print(json.dumps({'stage': receipt['stage'], 'pr_url': receipt['pr_url'],
                              'merge_sha': receipt['merge_sha'],
                              'qa_url': receipt['deployment']['url']}), flush=True)
            return
        except WaitingPublicationAccess as error:
            status('waiting_publication_access', context, owner='host_service',
                   category=str(error), next_action='restore_github_access_then_resume_same_delivery')
            print(json.dumps({'stage': 'waiting_publication_access',
                              'issue_id': context['issue_id'], 'category': str(error)}), flush=True)
            return
        except QualityBlocked as error:
            incident = error.incident
            status('qa_blocked', context, owner='techlead',
                   child_issue_id=incident['child_issue_id'],
                   phase=incident['phase'], category=incident['category'],
                   dispatch=incident['dispatch'])
            try:
                recovery = drive_qa_repair(incident, contract) if RUN_SPEC and 'key' in incident else None
            except Exception as recovery_error:
                recovery = {'stage': 'qa_repair_escalation',
                            'category': type(recovery_error).__name__ + ':' + str(recovery_error)[:180]}
            if recovery:
                status(recovery['stage'], context, owner='techlead',
                       child_issue_id=incident['child_issue_id'],
                       recovery=recovery)
            print(json.dumps({'stage': 'qa_blocked',
                              'issue_id': context['issue_id'],
                              'child_issue_id': incident['child_issue_id'],
                              'dispatch': incident['dispatch'],
                              'recovery': recovery}), flush=True)
            return
        except WaitingBrowserAcceptance:
            status('waiting_browser_acceptance', context, owner='quality_security',
                   next_action='Validate real browser on exact deployed SHA; no worker retry')
            print(json.dumps({'stage': 'waiting_browser_acceptance',
                              'issue_id': context['issue_id']}), flush=True)
            return
        except WaitingApproval:
            try:
                worker_state = recover_implementation_worker(context)
            except RecoveryEscalation as error:
                category = str(error)
                status('escalation_required', context, owner='techlead', category=category)
                print(json.dumps({'stage': 'escalation_required', 'category': category,
                                  'issue_id': context['issue_id']}), flush=True)
                return
            except Exception as error:
                category = 'recovery_control_plane:' + type(error).__name__ + ':' + str(error)[:120]
                failures[category] = failures.get(category, 0) + 1
                if failures[category] >= 2:
                    status('escalation_required', context, owner='techlead', category=category)
                    print(json.dumps({'stage': 'escalation_required', 'category': category,
                                      'issue_id': context['issue_id']}), flush=True)
                    return
                time.sleep(10)
                continue
            if worker_state == 'recovery_queued':
                waiting_since = time.monotonic()
                status('recovery_queued', context, owner='implementer/reviewer',
                       category='recoverable_worker_failure')
                continue
            if worker_state.startswith('handoff:'):
                status(worker_state.removeprefix('handoff:'), context, owner='durable_handoff_controller')
                time.sleep(10)
                continue
            status('waiting_approval', context, owner='implementer/reviewer')
            if time.monotonic() - waiting_since > 900:
                status('escalation_required', context, owner='techlead',
                       category='approval_timeout_without_evidence')
                print(json.dumps({'stage': 'escalation_required',
                                  'category': 'approval_timeout_without_evidence',
                                  'issue_id': context['issue_id']}), flush=True)
                return
            time.sleep(10)
        except RecoveryEscalation as error:
            category = str(error)
            if category.startswith('test_revision_required:') and RUN_SPEC:
                from portable_test_revision_recovery import schedule
                try:
                    recovery = schedule(PRIVATE, context, RUN_SPEC, contract, managed_handoff(context))
                except Exception as revision_error:
                    category = 'test_revision_recovery:' + type(revision_error).__name__ + ':' + str(revision_error)[:160]
                else:
                    status(recovery['stage'], context, owner='cto/independent_reviewer',
                           child_issue_id=recovery['child_issue'])
                    if recovery['stage'] == 'test_revision_child_running':
                        time.sleep(10)
                        continue
                    print(json.dumps(recovery), flush=True)
                    return
            status('escalation_required', context, owner='techlead', category=category)
            print(json.dumps({'stage': 'escalation_required', 'category': category,
                              'issue_id': context['issue_id']}), flush=True)
            return
        except Exception as error:
            category = type(error).__name__ + ':' + str(error)[:180]
            failures[category] = failures.get(category, 0) + 1
            if failures[category] >= 2:
                status('escalation_required', context, owner='techlead', category=category)
                print(json.dumps({'stage': 'escalation_required', 'category': category,
                                  'issue_id': context['issue_id']}), flush=True)
                return
            time.sleep(10)


def main():
    contract = from_environment()
    configure_run(contract)
    lock_dir = PRIVATE / 'controller-locks'
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    lock_path = lock_dir / (LABEL + '.lock')
    with lock_path.open('a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'stage': 'controller_busy', 'label': LABEL}), flush=True)
            raise SystemExit(75)
        run_controller(contract)


if __name__ == '__main__':
    main()
