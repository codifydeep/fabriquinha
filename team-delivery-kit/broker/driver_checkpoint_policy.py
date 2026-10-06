"""Opt-in V3 capability: one exact maintenance wakeup, never an issue-wide grant."""
import hashlib
import json
import re

PATH = '/workspace/tests/test_incremental_u3.py'


def select(config, state, issue, task):
    guard = state.get('staged', {}).get('driver_guard')
    if not guard or state.get('issue_id') != issue:
        return None
    if task.get('agent_id') != config.get('author'):
        return None
    identity=task.get('id') or task.get('task_id')
    if task.get('id') and task.get('task_id') and task['id']!=task['task_id']:
        raise ValueError('conflicting native task identity')
    if (state.get('stage') != 'awaiting_author' or task.get('issue_id') != issue
            or not identity or task.get('wakeup_id') != state.get('wakeup_id')):
        raise ValueError('exact active driver checkpoint wakeup required')
    if state.get('c10_decomposition'):
        if state.get('c10_checkpoints'):
            try:import c10_checkpoint_contract as gates
            except ImportError:from broker import c10_checkpoint_contract as gates
            return gates.admission(state).select(config,state,task)
        raise ValueError('decomposed C10 requires a new phase-specific author capability; legacy grant forbidden')
    flags = ('actual_registry', 'actual_default_selection', 'actual_acp_selection',
             'readless_edit_denied', 'generic_write_and_terminal_denied', 'direct_handler_fenced',
             'invalid_syntax_preserves_bytes', 'outside_driver_change_preserves_bytes',
             'test_weakening_preserves_bytes', 'stale_edit_denied', 'fixed_node_check', 'credentials_absent')
    proof = guard.get('qualification', {})
    image = guard.get('worker_image')
    if (not isinstance(image, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image)
            or proof.get('worker_image') != image or proof.get('status') != 'passed'
            or proof.get('schema') != 'surgical-driver-registry-probe-v3'
            or proof.get('network') != 'none' or proof.get('uid') != 10000
            or proof.get('delivery_approval') is not False
            or any(proof.get(key) is not True for key in flags)):
        raise ValueError('qualified immutable V3 worker required')
    recovery=state.get('c10_syntax_recovery')
    if recovery:
        try:import c10_syntax_recovery as syntax
        except ImportError:from broker import c10_syntax_recovery as syntax
        if (recovery.get('attempt_limit')!=1 or recovery.get('qualification')!=proof
                or guard.get('syntax_feedback') is not True
                or any(proof.get(k) is not True for k in syntax.FLAGS)
                or state.get('functional_fragment_recovery',{}).get('scope')!='response_envelope_c10_syntax_feedback'
                or recovery.get('cto_certificate')!=state.get('functional_diagnosis_receipt',{}).get('certificate')
                or hashlib.sha256(syntax.delivery.functional_correction_note(state).encode()).hexdigest()!=recovery.get('note_sha256')):
            raise ValueError('exact changed-contract syntax recovery capability required')
    staged = state['staged']
    number = staged.get('current')
    if type(number) is not int or number not in (1, 2):
        raise ValueError('exact maintenance checkpoint required')
    if number == 1:
        if staged.get('history'):
            raise ValueError('syntax checkpoint lineage drift')
        digest = config['file_sha256']['tests/test_incremental_u3.py']
    else:
        history = staged.get('history', [])
        try:
            import harness_repair_task
        except ImportError:
            from broker import harness_repair_task
        if len(history) != 1 or history[0].get('checkpoint') != 1 or not harness_repair_task.checkpoint_passed(history[0]['validation']):
            raise ValueError('verified syntax checkpoint receipt required')
        digest = history[0]['validation']['test_sha256']
        correction=state.get('functional_correction')
        if correction:
            seed=correction['seed'];report=state.get('functional_diagnosis_receipt',{})
            if (seed.get('checkpoint')!=2 or not harness_repair_task.checkpoint_passed(seed['validation'])
                    or correction.get('attempt_limit')!=1 or correction.get('certificate')!=report.get('certificate')
                    or report.get('classification')!='DRIVER_OBSERVATION'
                    or seed['snapshot']!=state['functional_diagnosis']['snapshot']
                    or seed['validation']!=state['functional_diagnosis']['validation']):
                raise ValueError('exact functional correction seed and CTO certificate required')
            digest=seed['validation']['test_sha256']
            if state.get('functional_fragment_recovery'):
                try:import maintenance_delivery
                except ImportError:from broker import maintenance_delivery
                seed=maintenance_delivery.fragment_seed(state)
                if not harness_repair_task.checkpoint_passed(seed['validation']):raise ValueError('valid fragment seed required')
                digest=seed['validation']['test_sha256']
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('exact immutable seed hash required')
    protocol='typed_driver_v3'
    if guard.get('line_ranges'):
        if guard['line_ranges'] is not True or proof.get('line_range_registry_qualified') is not True:
            raise ValueError('qualified line-range worker required')
        protocol='typed_driver_lines_v4'
    return {'worker_image': image, 'surgical': {
        'path': PATH, 'expected_sha256': digest, 'protocol': protocol}}


def for_task(b, issue, task):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='harness_repair_tasks'").fetchone():
            return None
        rows = con.execute('SELECT config,state FROM harness_repair_tasks').fetchall()
    selected = [grant for row in rows if (grant := select(json.loads(row[0]), json.loads(row[1]), issue, task))]
    if len(selected) > 1:
        raise ValueError('conflicting driver checkpoint grants')
    return selected[0] if selected else None


def worker_config(b, request_id, issue):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='harness_repair_tasks'").fetchone():
            return None
        rows = con.execute('SELECT state FROM harness_repair_tasks').fetchall()
        if not any(json.loads(r[0]).get('issue_id') == issue and
                   json.loads(r[0]).get('staged', {}).get('driver_guard') for r in rows):
            return None
        bound = con.execute('SELECT task_id,agent_id FROM native_bindings WHERE request_id=?', (request_id,)).fetchone()
    if not bound:
        raise ValueError('driver checkpoint native binding required')
    try:
        import native
    except ImportError:
        from broker import native
    settings = json.loads((b.STATE / 'native.json').read_text())
    return for_task(b, issue, native.task_record(settings, bound['task_id'], bound['agent_id']))
