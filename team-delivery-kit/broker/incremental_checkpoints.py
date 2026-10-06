"""Persistent, fail-closed incremental TDD ledger (no dispatch authority).

This module has NO worker-facing endpoint. A future runtime adapter must resolve
receipt hashes from controller-owned, verified immutable evidence. Text returned
by an agent is never such a receipt. Registration records an accepted plan but
does not bind a workspace, modify an old Red, wake an agent or approve delivery.
"""
import contextlib
import hashlib
import json
import re
import uuid

from portable_contract import safe_path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('immutable evidence digest required')
    return value


def _hashes(value):
    if not isinstance(value, dict) or not value:
        raise ValueError('nonempty test inventory required')
    for path, sha in value.items():
        safe_path(path)
        _hash(sha)
    return value


@contextlib.contextmanager
def _atomic(con):
    # SAVEPOINT works inside an existing broker transaction as well as standalone.
    name = 'checkpoint_' + uuid.uuid4().hex
    con.execute('SAVEPOINT ' + name)
    try:
        yield
        con.execute('RELEASE ' + name)
    except BaseException:
        con.execute('ROLLBACK TO ' + name)
        con.execute('RELEASE ' + name)
        raise


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS incremental_checkpoints('
                'source_task TEXT PRIMARY KEY, config TEXT NOT NULL, state TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS incremental_checkpoint_events('
                'source_task TEXT NOT NULL, receipt_sha256 TEXT NOT NULL, receipt TEXT NOT NULL,'
                'PRIMARY KEY(source_task,receipt_sha256))')


def register(con, source_task, policy):
    """Consume only an already accepted durable proposal; preserve original scope."""
    initialize(con)
    required = {'author', 'test_reviewer', 'delivery_reviewer', 'base_manifest_sha256',
                'baseline_test_sha256', 'baseline_test_count', 'suite_sha256'}
    if not isinstance(policy, dict) or set(policy) != required:
        raise ValueError('exact controller policy required')
    if any(not isinstance(policy[k], str) or not policy[k]
           for k in ('author', 'test_reviewer', 'delivery_reviewer')):
        raise ValueError('named controller roles required')
    if policy['author'] in (policy['test_reviewer'], policy['delivery_reviewer']):
        raise ValueError('independent reviewers required')
    _hash(policy['base_manifest_sha256']); _hash(policy['suite_sha256'])
    _hashes(policy['baseline_test_sha256'])
    if type(policy['baseline_test_count']) is not int or policy['baseline_test_count'] <= 0:
        raise ValueError('controller-observed baseline test count required')
    with _atomic(con):
        row = con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',
                          (source_task,)).fetchone()
        if not row:
            raise ValueError('accepted decomposition missing')
        proposal_config, proposal_state = map(json.loads, row)
        cert = proposal_state.get('certificate', {})
        units = cert.get('normalized_units', [])
        if (proposal_state.get('stage') != 'proposal_ready'
                or cert.get('source_task') != source_task
                or cert.get('decision_task') != proposal_state.get('task_id')
                or not cert.get('decision_task')
                or cert.get('execution_authorized') is not False
                or cert.get('delivery_approval') is not False
                or cert.get('baseline_edits_allowed') is not False
                or policy['author'] != proposal_config['author']
                or not isinstance(units, list) or not 2 <= len(units) <= 4):
            raise ValueError('accepted non-authorizing proposal required')
        _hash(cert.get('proposal_sha256'))
        covered = []
        for index, unit in enumerate(units, 1):
            if (set(unit) != {'id', 'depends_on', 'criteria', 'objective'}
                    or unit['id'] != 'U'+str(index)
                    or unit['depends_on'] != ([] if index == 1 else ['U'+str(index-1)])
                    or not isinstance(unit['criteria'], list) or not unit['criteria']
                    or not isinstance(unit['objective'], str) or not 1 <= len(unit['objective']) <= 300):
                raise ValueError('ordered checkpoint units required')
            covered.extend(unit['criteria'])
        if len(covered) != len(set(covered)) or set(covered) != set(proposal_config['criteria']):
            raise ValueError('complete unchanged criterion coverage required')
        config = dict(source_task=source_task, issue_id=proposal_config['issue_id'],
                      proposal_sha256=cert['proposal_sha256'], units=units, policy=policy,
                      criteria_sha256=digest(proposal_config['criteria']))
        previous = con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',
                               (source_task,)).fetchone()
        if previous:
            if json.loads(previous[0]) != config:
                raise ValueError('checkpoint contract drift')
            return json.loads(previous[1])
        state = dict(stage='awaiting_runtime_binding', execution_authorized=False,
                     delivery_approval=False, units={u['id']: dict(
                         id=u['id'], revision=1,
                         stage='awaiting_red' if i == 0 else 'waiting_dependency',
                         owner=policy['author'],
                         base_manifest_sha256=policy['base_manifest_sha256'] if i == 0 else None,
                         prior_test_count=policy['baseline_test_count'] if i == 0 else None,
                         baseline_test_sha256=policy['baseline_test_sha256'] if i == 0 else None)
                         for i, u in enumerate(units)})
        con.execute('INSERT INTO incremental_checkpoints VALUES(?,?,?)',
                    (source_task, json.dumps(config, sort_keys=True), json.dumps(state, sort_keys=True)))
        return state


def status(con, source_task):
    row = con.execute('SELECT state FROM incremental_checkpoints WHERE source_task=?',
                      (source_task,)).fetchone()
    if not row:
        raise ValueError('checkpoint contract missing')
    return json.loads(row[0])


def prepare_revision(con, source_task, unit_id, rejected_review_sha256):
    """Preserve a rejection and prepare one new author revision, without dispatch.

    The runtime must bind a NEW workspace/snapshot and obtain fresh evidence.
    Two rejected revisions stop this local action and remain a technical incident.
    No original Red or reviewer decision is erased or rewritten.
    """
    _hash(rejected_review_sha256)
    with _atomic(con):
        state = status(con, source_task)
        unit = state['units'].get(unit_id)
        if not unit:
            raise ValueError('checkpoint unit missing')
        if unit.get('revision_source') == rejected_review_sha256:
            return state
        row = con.execute('SELECT receipt FROM incremental_checkpoint_events '
                          'WHERE source_task=? AND receipt_sha256=?',
                          (source_task,rejected_review_sha256)).fetchone()
        receipt = json.loads(row[0]) if row else {}
        if (unit['stage']!='blocked' or unit.get('category')!='changes_requested'
                or receipt.get('unit')!=unit_id or receipt.get('decision')!='request_changes'
                or receipt.get('operation') not in ('test_review','delivery_review')
                or unit.get(receipt['operation'])!=rejected_review_sha256):
            raise ValueError('current independently rejected revision required')
        if unit['revision'] >= 2:
            raise ValueError('repeated rejection requires technical diagnosis')
        history=unit.get('history',[])+[{k:v for k,v in unit.items() if k!='history'}]
        replacement = {k:unit[k] for k in ('id','base_manifest_sha256',
                                         'baseline_test_sha256','prior_test_count')}
        replacement.update(stage='awaiting_red',owner=unit['owner'],
            revision=unit['revision']+1,history=history,revision_source=rejected_review_sha256)
        state['units'][unit_id]=replacement
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',
                    (json.dumps(state,sort_keys=True),source_task))
        return state


def prepare_test_repair(con, source_task, unit_id, receipt_sha256, resolve_verified):
    """A CTO diagnosis starts a NEW test revision, never a fake review rejection.

    Controller-only resolver must verify the current native diagnosis and failure.
    Existing approval remains historical; it conveys no authority to revision 2.
    """
    _hash(receipt_sha256)
    receipt = resolve_verified(receipt_sha256)
    if not isinstance(receipt, dict) or digest(receipt) != receipt_sha256:
        raise ValueError('verified repair sponsorship required')
    with _atomic(con):
        config, state = map(json.loads, con.execute(
            'SELECT config,state FROM incremental_checkpoints WHERE source_task=?',
            (source_task,)).fetchone())
        unit = state['units'].get(unit_id)
        if not unit:
            raise ValueError('checkpoint unit missing')
        if unit.get('revision_source') == receipt_sha256:
            return state
        expected = {'operation', 'source_task', 'unit', 'parent_issue', 'decision_task',
                    'cto', 'original_red', 'output_sha256', 'proposal_sha256', 'reason'}
        ids=[u['id'] for u in config['units']]
        if unit_id not in ids:raise ValueError('declared repair unit required')
        index=ids.index(unit_id)
        if index:
            previous=state['units'][ids[index-1]]
            if (previous['stage']!='checkpointed'
                    or previous.get('green_manifest_sha256')!=unit['base_manifest_sha256']):
                raise ValueError('exact approved predecessor base required for repair')
        if (set(receipt) != expected or receipt['operation'] != 'cto_test_repair_v1'
                or receipt['source_task'] != source_task or receipt['unit'] != unit_id
                or receipt['proposal_sha256'] != config['proposal_sha256']
                or unit['revision'] != 1 or unit.get('green') or unit.get('delivery_review')
                or unit['stage'] != 'awaiting_green'
                or receipt['parent_issue'] != unit.get('binding', {}).get('issue_id')
                or receipt['original_red'] != unit.get('red')
                or not receipt['decision_task'] or receipt['cto'] == unit['owner']
                or not isinstance(receipt['reason'], str) or not 1 <= len(receipt['reason']) <= 3000):
            raise ValueError('current same-base CTO test repair required')
        _hash(receipt['output_sha256']); _hash(receipt['original_red'])
        history = unit.get('history', []) + [{k:v for k,v in unit.items() if k!='history'}]
        replacement = {k:unit[k] for k in ('id', 'owner', 'base_manifest_sha256',
                                           'baseline_test_sha256', 'prior_test_count')}
        replacement.update(stage='awaiting_red', revision=2, history=history,
                           revision_source=receipt_sha256, test_repair=receipt)
        state['units'][unit_id] = replacement
        state['execution_authorized'] = False
        state['stage'] = 'awaiting_runtime_binding'
        if 'execution_units' in state:
            state['execution_units']=[uid for uid in state['execution_units'] if uid!=unit_id]
        if state.get('activation'):
            state.setdefault('activation_history', []).append(state.pop('activation'))
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',
                    (source_task, receipt_sha256, json.dumps(receipt, sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',
                    (json.dumps(state, sort_keys=True), source_task))
        return state


def prepare_source_harness_revision(con, source_task, unit_id, receipt_sha256, resolve_verified):
    """One revision-3 transition sponsored against newly verified source facts."""
    _hash(receipt_sha256)
    receipt = resolve_verified(receipt_sha256)
    if not isinstance(receipt, dict) or digest(receipt) != receipt_sha256:
        raise ValueError('verified source harness sponsorship required')
    with _atomic(con):
        config, state = map(json.loads, con.execute(
            'SELECT config,state FROM incremental_checkpoints WHERE source_task=?', (source_task,)).fetchone())
        unit = state['units'][unit_id]
        if unit.get('revision_source') == receipt_sha256:
            return state
        expected = {'operation','source_task','unit','parent_issue','decision_task','cto',
                    'original_red','output_sha256','proposal_sha256','reason','harness_sha256'}
        ids = [u['id'] for u in config['units']]
        index = ids.index(unit_id)
        if index:
            prior = state['units'][ids[index-1]]
            if prior['stage'] != 'checkpointed' or prior.get('green_manifest_sha256') != unit['base_manifest_sha256']:
                raise ValueError('exact approved predecessor base required')
        if (set(receipt) != expected or receipt['operation'] != 'cto_source_harness_revision_v1'
                or receipt['source_task'] != source_task or receipt['unit'] != unit_id
                or receipt['proposal_sha256'] != config['proposal_sha256']
                or unit['revision'] != 2 or not unit.get('test_repair')
                or unit['stage'] != 'awaiting_green' or unit.get('green') or unit.get('delivery_review')
                or receipt['parent_issue'] != unit.get('binding', {}).get('issue_id')
                or receipt['original_red'] != unit.get('red')
                or not receipt['decision_task'] or receipt['cto'] == unit['owner']
                or receipt['decision_task'] == unit['test_repair']['decision_task']
                or not isinstance(receipt['reason'], str) or not 1 <= len(receipt['reason']) <= 3000):
            raise ValueError('current source-bound revision-2 sponsorship required')
        for key in ('original_red','output_sha256','harness_sha256'):
            _hash(receipt[key])
        replacement = {k:unit[k] for k in ('id','owner','base_manifest_sha256','baseline_test_sha256','prior_test_count')}
        replacement.update(stage='awaiting_red', revision=3,
            history=unit.get('history', [])+[{k:v for k,v in unit.items() if k!='history'}],
            revision_source=receipt_sha256, test_repair=receipt)
        state['units'][unit_id] = replacement
        state.update(execution_authorized=False, stage='awaiting_runtime_binding')
        if 'execution_units' in state:
            state['execution_units'] = [uid for uid in state['execution_units'] if uid != unit_id]
        if state.get('activation'):
            state.setdefault('activation_history', []).append(state.pop('activation'))
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',
                    (source_task, receipt_sha256, json.dumps(receipt, sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',
                    (json.dumps(state, sort_keys=True), source_task))
        return state


def prepare_admission_recovery(con,source_task,unit_id,receipt_sha256,resolve_verified):
    """Bounded held3->4, then changed-driver controls completion4->5 only."""
    _hash(receipt_sha256);r=resolve_verified(receipt_sha256)
    if not isinstance(r,dict) or digest(r)!=receipt_sha256:
        raise ValueError('verified admission sponsorship required')
    with _atomic(con):
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source_task,)).fetchone())
        u=state['units'][unit_id]
        if u.get('revision_source')==receipt_sha256:return state
        expected={'operation','source_task','unit','parent_issue','decision_task','cto','original_red',
            'proposal_sha256','reason','admission_sha256','review_task'}
        completion=r.get('operation')=='cto_controls_completion_v1'
        if completion:expected|={'captured_red_sha256','rejected_manifest_sha256'}
        hold=u.get('admission_hold') or {}
        if (set(r)!=expected or r['operation'] not in ('cto_admission_recovery_v1','cto_controls_completion_v1')
                or r['source_task']!=source_task or r['unit']!=unit_id or u['revision']!=(4 if completion else 3)
                or u['stage']!=('awaiting_red' if completion else 'awaiting_green') or u.get('green') or u.get('delivery_review')
                or not u.get('test_repair') or r['decision_task']==u['test_repair']['decision_task']
                or not r['cto'] or r['cto'] in (config['policy']['author'],config['policy']['test_reviewer'])
                or not r['decision_task'] or r['parent_issue']!=u.get('binding',{}).get('issue_id')
                or (not completion and r['original_red']!=u.get('red')) or r['proposal_sha256']!=config['proposal_sha256']
                or hold.get('owner')!='cto' or hold.get('delivery_approval') is not False
                or r['review_task']!=hold.get('review_task') or not r['review_task']
                or not isinstance(r['reason'],str) or not 1<=len(r['reason'])<=1200):
            raise ValueError('current held revision3 admission recovery required')
        if completion:
            if (u['test_repair']['operation']!='cto_admission_recovery_v1' or u.get('red')
                    or r['captured_red_sha256']!=r['original_red']
                    or r['admission_sha256']==u['test_repair']['admission_sha256']):
                raise ValueError('new incomplete-controls captured evidence required')
            _hash(r['captured_red_sha256']);_hash(r['rejected_manifest_sha256'])
        for k in ('original_red','admission_sha256'):_hash(r[k])
        ids=[v['id'] for v in config['units']];i=ids.index(unit_id)
        if i:
            prior=state['units'][ids[i-1]]
            if prior['stage']!='checkpointed' or prior.get('green_manifest_sha256')!=u['base_manifest_sha256']:
                raise ValueError('exact approved predecessor required')
        replacement={k:u[k] for k in ('id','base_manifest_sha256','baseline_test_sha256','prior_test_count')}
        replacement.update(owner=config['policy']['author'],stage='awaiting_red',revision=5 if completion else 4,
            history=u.get('history',[])+[{k:v for k,v in u.items() if k!='history'}],
            revision_source=receipt_sha256,test_repair=r,admission_hold=dict(hold,recovery_state='tests_only'))
        state['units'][unit_id]=replacement
        state.update(execution_authorized=False,stage='awaiting_runtime_binding')
        if 'execution_units' in state:state['execution_units']=[uid for uid in state['execution_units'] if uid!=unit_id]
        if state.get('activation'):state.setdefault('activation_history',[]).append(state.pop('activation'))
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',(source_task,receipt_sha256,json.dumps(r,sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source_task))
        return state


def prepare_harness_revision(con, source_task, receipt_sha256, resolve_verified):
    """One experiment-qualified revision 3, not a generic retry-limit increase."""
    _hash(receipt_sha256)
    receipt = resolve_verified(receipt_sha256)
    if not isinstance(receipt, dict) or digest(receipt) != receipt_sha256:
        raise ValueError('verified experiment sponsorship required')
    with _atomic(con):
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source_task,)).fetchone())
        unit=state['units']['U1']
        if unit.get('revision_source')==receipt_sha256:return state
        if (set(receipt)!={'operation','source_task','unit','parent_issue','decision_task','cto',
                'original_red','proposal_sha256','reason','experiment_sha256','fixture_volume'}
                or receipt['operation']!='cto_harness_experiment_revision_v1'
                or receipt['source_task']!=source_task or receipt['unit']!='U1'
                or receipt['proposal_sha256']!=config['proposal_sha256']
                or unit['revision']!=2 or not unit.get('test_repair')
                or unit['stage']!='awaiting_green'
                or receipt['parent_issue']!=unit.get('binding',{}).get('issue_id')
                or receipt['original_red']!=unit.get('red')
                or not receipt['decision_task'] or receipt['cto']==unit['owner']
                or not isinstance(receipt['reason'],str) or not 1<=len(receipt['reason'])<=3000):
            raise ValueError('current original-base experiment revision required')
        _hash(receipt['original_red']);_hash(receipt['experiment_sha256'])
        history=unit.get('history',[])+[{k:v for k,v in unit.items() if k!='history'}]
        replacement={k:unit[k] for k in ('id','owner','base_manifest_sha256','baseline_test_sha256','prior_test_count')}
        replacement.update(stage='awaiting_red',revision=3,history=history,
            revision_source=receipt_sha256,test_repair=receipt)
        state['units']['U1']=replacement
        state.update(execution_authorized=False,stage='awaiting_runtime_binding')
        if state.get('activation'):state.setdefault('activation_history',[]).append(state.pop('activation'))
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',(source_task,receipt_sha256,json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source_task))
        return state


def prepare_seed_transport_revision(con, source_task, receipt_sha256, resolve_verified):
    """One revision 4 for the proven pre-provider read defect, not a retry reset."""
    _hash(receipt_sha256)
    receipt=resolve_verified(receipt_sha256)
    if not isinstance(receipt,dict) or digest(receipt)!=receipt_sha256:
        raise ValueError('verified transport sponsorship required')
    with _atomic(con):
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source_task,)).fetchone())
        unit=state['units']['U1']
        if unit.get('revision_source')==receipt_sha256:return state
        expected={'operation','source_task','unit','parent_issue','decision_task','cto','proposal_sha256',
            'reason','experiment_sha256','fixture_volume','transport_sha256','rejected_manifest_sha256','proxy_image'}
        prior=unit.get('test_repair',{})
        if (set(receipt)!=expected or receipt['operation']!='cto_seed_transport_revision_v1'
                or receipt['source_task']!=source_task or receipt['unit']!='U1'
                or unit['revision']!=3 or unit['stage']!='awaiting_red' or unit.get('red')
                or prior.get('operation')!='cto_harness_experiment_revision_v1'
                or receipt['parent_issue']!=unit.get('binding',{}).get('issue_id')
                or receipt['proposal_sha256']!=config['proposal_sha256']
                or receipt['experiment_sha256']!=prior['experiment_sha256']
                or receipt['fixture_volume']!=prior['fixture_volume']
                or not receipt['decision_task'] or receipt['cto']==unit['owner']
                or not isinstance(receipt['reason'],str) or not 1<=len(receipt['reason'])<=3000):
            raise ValueError('exact sponsored pre-provider revision required')
        for key in ('transport_sha256','rejected_manifest_sha256','experiment_sha256'):_hash(receipt[key])
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',receipt['proxy_image']):raise ValueError('pinned fixed proxy required')
        history=unit.get('history',[])+[{k:v for k,v in unit.items() if k!='history'}]
        replacement={k:unit[k] for k in ('id','owner','base_manifest_sha256','baseline_test_sha256','prior_test_count')}
        replacement.update(stage='awaiting_red',revision=4,history=history,revision_source=receipt_sha256,test_repair=receipt)
        state['units']['U1']=replacement
        state.update(execution_authorized=False,stage='awaiting_runtime_binding')
        if state.get('activation'):state.setdefault('activation_history',[]).append(state.pop('activation'))
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',(source_task,receipt_sha256,json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source_task))
        return state


def prepare_controls_revision(con, source_task, receipt_sha256, resolve_verified):
    """One evidence-bound revision5; never a retry reset or retroactive Red."""
    _hash(receipt_sha256)
    receipt=resolve_verified(receipt_sha256)
    if not isinstance(receipt,dict) or digest(receipt)!=receipt_sha256:
        raise ValueError('verified controls sponsorship required')
    with _atomic(con):
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source_task,)).fetchone())
        unit=state['units']['U1']
        if unit.get('revision_source')==receipt_sha256:return state
        prior=unit.get('test_repair',{})
        expected={'operation','source_task','unit','parent_issue','decision_task','cto','proposal_sha256',
            'reason','experiment_sha256','fixture_volume','diagnosis_sha256','rejected_manifest_sha256'}
        if (set(receipt)!=expected or receipt['operation']!='cto_negative_controls_revision_v1'
                or receipt['source_task']!=source_task or receipt['unit']!='U1'
                or unit['revision']!=4 or unit['stage']!='awaiting_red' or unit.get('red')
                or prior.get('operation')!='cto_seed_transport_revision_v1'
                or receipt['parent_issue']!=unit.get('binding',{}).get('issue_id')
                or receipt['proposal_sha256']!=config['proposal_sha256']
                or receipt['experiment_sha256']!=prior['experiment_sha256']
                or receipt['fixture_volume']!=prior['fixture_volume']
                or not receipt['decision_task'] or receipt['cto']==unit['owner']
                or not isinstance(receipt['reason'],str) or not 1<=len(receipt['reason'])<=1200):
            raise ValueError('current missing-controls CTO revision required')
        for key in ('diagnosis_sha256','rejected_manifest_sha256','experiment_sha256'):_hash(receipt[key])
        history=unit.get('history',[])+[{k:v for k,v in unit.items() if k!='history'}]
        replacement={k:unit[k] for k in ('id','owner','base_manifest_sha256','baseline_test_sha256','prior_test_count')}
        replacement.update(stage='awaiting_red',revision=5,history=history,revision_source=receipt_sha256,test_repair=receipt)
        state['units']['U1']=replacement
        state.update(execution_authorized=False,stage='awaiting_runtime_binding')
        if state.get('activation'):state.setdefault('activation_history',[]).append(state.pop('activation'))
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',(source_task,receipt_sha256,json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source_task))
        return state


def prepare_negative_spike_revision(con,source,sha,resolve_verified):
    _hash(sha);r=resolve_verified(sha)
    if not isinstance(r,dict) or digest(r)!=sha:raise ValueError('verified spike sponsorship required')
    with _atomic(con):
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        u=state['units']['U1']
        if u.get('revision_source')==sha:return state
        expected={'operation','source_task','unit','parent_issue','decision_task','cto','proposal_sha256','reason',
            'experiment_sha256','fixture_volume','negative_spike_sha256','original_red','rejected_manifest_sha256'}
        if (set(r)!=expected or r['operation']!='cto_negative_spike_revision_v1' or r['source_task']!=source
                or r['unit']!='U1' or u['revision']!=5 or u['stage']!='awaiting_green'
                or not u.get('test_review') or u.get('green') or r['original_red']!=u.get('red')
                or u.get('test_repair',{}).get('operation')!='cto_negative_controls_revision_v1'
                or r['parent_issue']!=u.get('binding',{}).get('issue_id')
                or r['proposal_sha256']!=config['proposal_sha256'] or r['cto']==u['owner'] or not r['decision_task']
                or r['experiment_sha256']!=u['test_repair']['experiment_sha256']
                or r['fixture_volume']!=u['test_repair']['fixture_volume']
                or not isinstance(r['reason'],str) or not 1<=len(r['reason'])<=1200):
            raise ValueError('current spike-backed revision5 required')
        for key in ('negative_spike_sha256','original_red','rejected_manifest_sha256'):_hash(r[key])
        replacement={k:u[k] for k in ('id','owner','base_manifest_sha256','baseline_test_sha256','prior_test_count')}
        replacement.update(stage='awaiting_red',revision=6,history=u.get('history',[])+[{k:v for k,v in u.items() if k!='history'}],revision_source=sha,test_repair=r)
        state['units']['U1']=replacement;state.update(execution_authorized=False,stage='awaiting_runtime_binding')
        if state.get('activation'):state.setdefault('activation_history',[]).append(state.pop('activation'))
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',(source,sha,json.dumps(r,sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return state


def record(con, source_task, receipt_sha256, resolve_verified):
    """Atomic transition using a trusted controller resolver, never agent payloads.

    Resolver must verify immutable manifests, native execution identities, pinned
    full-suite execution, existing baseline assertions and read-only review before
    returning the normalized receipt. The runtime adapter is intentionally not
    installed yet; this ledger cannot independently prove those external facts.
    """
    _hash(receipt_sha256)
    receipt = resolve_verified(receipt_sha256)
    if not isinstance(receipt, dict) or digest(receipt) != receipt_sha256:
        raise ValueError('verified receipt unavailable or digest drift')
    with _atomic(con):
        row = con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',
                          (source_task,)).fetchone()
        if not row:
            raise ValueError('checkpoint contract missing')
        config, state = map(json.loads, row)
        previous = con.execute('SELECT receipt FROM incremental_checkpoint_events '
                               'WHERE source_task=? AND receipt_sha256=?',
                               (source_task, receipt_sha256)).fetchone()
        if previous:
            if json.loads(previous[0]) != receipt:
                raise ValueError('historical receipt drift')
            return state
        for prior in con.execute('SELECT receipt FROM incremental_checkpoint_events WHERE source_task=?',
                                 (source_task,)):
            if json.loads(prior[0]).get('task_id') == receipt.get('task_id'):
                raise ValueError('native execution cannot certify two checkpoint events')
        _transition(config, state, receipt_sha256, receipt)
        con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',
                    (source_task, receipt_sha256, json.dumps(receipt, sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',
                    (json.dumps(state, sort_keys=True), source_task))
        return state


def _transition(config, state, sha, receipt):
    common = {'source_task', 'unit', 'proposal_sha256', 'base_manifest_sha256',
              'suite_sha256', 'operation', 'task_id', 'manifest_sha256'}
    op = receipt.get('operation')
    extra = {
        'red': {'author','test_sha256','baseline_test_sha256','exit_code',
                'qualified_new_test_failure','previous_checkpoint_green','test_count'},
        'test_review': {'reviewer','red_receipt_sha256','decision'},
        'green': {'author','red_manifest_sha256','test_sha256','baseline_test_sha256',
                  'exit_code','full_suite','test_count'},
        'delivery_review': {'reviewer','green_receipt_sha256','decision'},
    }
    unit = state['units'].get(receipt.get('unit'))
    policy = config['policy']
    if (op not in extra or set(receipt) != common | extra[op] or not unit
            or receipt['source_task'] != config['source_task']
            or receipt['proposal_sha256'] != config['proposal_sha256']
            or receipt['suite_sha256'] != policy['suite_sha256']
            or receipt['base_manifest_sha256'] != unit['base_manifest_sha256']
            or not isinstance(receipt['task_id'], str) or not receipt['task_id']):
        raise ValueError('unit receipt identity or contract mismatch')
    _hash(receipt['manifest_sha256'])
    expected_stage = dict(red='awaiting_red',test_review='awaiting_test_review',
                          green='awaiting_green',delivery_review='awaiting_delivery_review')[op]
    if unit['stage'] != expected_stage:
        raise ValueError('checkpoint phase or dependency mismatch')
    if op in ('red','green'):
        _hashes(receipt['test_sha256']); _hashes(receipt['baseline_test_sha256'])
        if (receipt['author'] != policy['author']
                or receipt['baseline_test_sha256'] != unit['baseline_test_sha256']
                or set(receipt['test_sha256']) & set(unit['baseline_test_sha256'])
                or type(receipt['test_count']) is not int or receipt['test_count'] <= 0):
            raise ValueError('baseline tests immutable and new tests required')
        if op == 'red':
            if (type(receipt['exit_code']) is not int or receipt['exit_code'] != 1
                    or receipt['qualified_new_test_failure'] is not True
                    or receipt['previous_checkpoint_green'] is not True
                    or receipt['test_count'] <= unit.get('prior_test_count', 0)):
                raise ValueError('new qualified Red with prior checkpoint green required')
            unit.update(stage='awaiting_test_review', owner=policy['test_reviewer'],
                        red=sha, red_manifest_sha256=receipt['manifest_sha256'],
                        new_test_sha256=receipt['test_sha256'], red_test_count=receipt['test_count'])
        else:
            if (type(receipt['exit_code']) is not int or receipt['exit_code'] != 0
                    or receipt['full_suite'] is not True
                    or receipt['red_manifest_sha256'] != unit['red_manifest_sha256']
                    or receipt['test_sha256'] != unit['new_test_sha256']
                    or receipt['test_count'] < unit['red_test_count']):
                raise ValueError('full Green with frozen Red tests required')
            unit.update(stage='awaiting_delivery_review',owner=policy['delivery_reviewer'],
                        green=sha, green_manifest_sha256=receipt['manifest_sha256'],
                        green_test_count=receipt['test_count'])
    else:
        test_review = op == 'test_review'
        if (receipt['reviewer'] != policy['test_reviewer' if test_review else 'delivery_reviewer']
                or receipt['reviewer'] == policy['author']
                or receipt['manifest_sha256'] != unit['red_manifest_sha256' if test_review else 'green_manifest_sha256']
                or receipt['red_receipt_sha256' if test_review else 'green_receipt_sha256'] != unit['red' if test_review else 'green']
                or receipt['decision'] not in ('approve','request_changes')):
            raise ValueError('independent current-snapshot review required')
        unit[op] = sha
        if receipt['decision'] == 'request_changes':
            unit.update(stage='blocked',owner=policy['author'],category='changes_requested',
                        required_action='new_preserved_revision_contract')
            return
        if test_review:
            if unit.get('admission_hold'):
                if unit.get('test_repair',{}).get('operation') not in ('cto_admission_recovery_v1','cto_controls_completion_v1'):
                    raise ValueError('explicit admission recovery required before product handoff')
                unit.setdefault('admission_hold_history',[]).append(dict(unit.pop('admission_hold'),
                    release_test_review_sha256=sha,delivery_approval=False))
            unit.update(stage='awaiting_green',owner=policy['author'])
        else:
            unit.update(stage='checkpointed',owner='controller',checkpoint_sha256=sha)
            index = next(i for i,u in enumerate(config['units']) if u['id'] == receipt['unit'])
            if index+1 < len(config['units']):
                next_unit = state['units'][config['units'][index+1]['id']]
                if next_unit['stage'] != 'waiting_dependency':
                    raise ValueError('next checkpoint dependency drift')
                next_unit.update(stage='awaiting_red',base_manifest_sha256=unit['green_manifest_sha256'],
                    baseline_test_sha256={**unit['baseline_test_sha256'],**unit['new_test_sha256']},
                    prior_test_count=unit['green_test_count'])
            else:
                state['stage'] = 'awaiting_integration_qa'
