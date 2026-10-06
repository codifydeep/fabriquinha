"""Read-only adapter for controller-captured Red and independent review evidence.

There is no agent payload ingestion, dispatch, legacy evidence upgrade or default
approval. Callers bind each unit to its own issue and execution; old issue-wide
Red records are never reused as a new unit's execution.
"""
import json

try:
    import incremental_checkpoints as ledger
except ImportError:
    from broker import incremental_checkpoints as ledger


def suite_digest(image, command):
    return ledger.digest({'test_image': image, 'test_command': command})


def execution(con, task_id, issue_id, agent_id, mode):
    rows = con.execute('SELECT n.request_id,n.agent_id,n.issue_id,g.mode,g.used,l.status '
        'FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) '
        'WHERE n.task_id=? AND g.attempt=(SELECT max(attempt) FROM grants WHERE task_id=?)',
        (task_id, task_id)).fetchall()
    if (len(rows) != 1 or tuple(rows[0])[1:] != (agent_id, issue_id, mode, 1, 'closed')):
        raise ValueError('exact terminal controller execution required')
    return rows[0][0]


def red(con, config, unit, issue_id, task_id, *, prior_green):
    """Normalize an existing qualified V2 Red, bound to a verified prior suite.

    prior_green is a hash reference to the controller's review-suite RPC table,
    NOT a Boolean or an agent claim. Runtime binding must first run the base's
    fixed suite using an isolated controller capability.
    """
    execution(con, task_id, issue_id, config['policy']['author'], 'implementation')
    row = con.execute('SELECT receipt FROM test_first_red WHERE issue_id=? AND task_id=?',
                      (issue_id, task_id)).fetchone()
    if not row:
        raise ValueError('controller Red unavailable')
    stored = json.loads(row[0]); proof = stored.get('red', {})
    if (stored.get('issue_id') != issue_id or stored.get('task_id') != task_id
            or proof.get('evidence_version') != 2 or proof.get('exit_code') != 1
            or proof.get('base_manifest_sha256') != unit.get('materialized_base_manifest_sha256',unit['base_manifest_sha256'])
            or proof.get('baseline_test_sha256') != unit['baseline_test_sha256']
            or suite_digest(proof.get('test_image'),proof.get('command')) != config['policy']['suite_sha256']):
        raise ValueError('new fully bound controller Red required')
    ledger._hash(proof.get('output_sha256'))
    ledger._hashes(proof.get('test_sha256'))
    _prior_suite(con, prior_green, config, unit)
    return dict(operation='red',source_task=config['source_task'],unit=_unit_id(config,unit),
        proposal_sha256=config['proposal_sha256'],base_manifest_sha256=unit['base_manifest_sha256'],
        suite_sha256=config['policy']['suite_sha256'],task_id=task_id,
        manifest_sha256=proof['manifest_sha256'],author=config['policy']['author'],
        test_sha256=proof['test_sha256'],baseline_test_sha256=proof['baseline_test_sha256'],
        exit_code=1,qualified_new_test_failure=True,previous_checkpoint_green=True,
        test_count=proof['test_count'])


def _unit_id(config, unit):
    if unit.get('id') not in {u['id'] for u in config['units']}:
        raise ValueError('bound unit identity required')
    return unit['id']


def _prior_suite(con, ref, config, unit):
    ledger._hash(ref)
    if unit.get('id')=='U1' and con.execute("SELECT 1 FROM sqlite_master WHERE name='initial_base_validations'").fetchone():
        row=con.execute("SELECT manifest_sha256,receipt FROM initial_base_validations WHERE source_task=? AND status='passed'",
                        (config['source_task'],)).fetchone()
        if row:
            proof=json.loads(row[1])
            if (ledger.digest(proof)!=ref or row[0]!=unit['base_manifest_sha256']
                    or proof.get('manifest_sha256')!=row[0]
                    or proof.get('executed_by')!='controller_original_base_suite'
                    or proof.get('source_task')!=config['source_task']
                    or proof.get('exit_code')!=0 or proof.get('network')!='none'
                    or proof.get('snapshot_mount')!='readonly'
                    or type(proof.get('tests')) is not int or proof['tests']!=unit['prior_test_count']
                    or proof.get('baseline_test_sha256')!=unit['baseline_test_sha256']
                    or suite_digest(proof.get('test_image'),proof.get('test_command'))!=config['policy']['suite_sha256']):
                raise ValueError('original-base suite binding mismatch')
            ledger._hash(proof.get('output_sha256'))
            return
    matches = []
    for row in con.execute("SELECT request_id,source_task,receipt FROM review_suite_rpc WHERE status='passed'"):
        receipt = json.loads(row[2])
        if ledger.digest(receipt) == ref:
            matches.append((row, receipt))
    if len(matches) != 1:
        raise ValueError('unique controller prior-checkpoint suite required')
    row, receipt = matches[0]
    if (receipt.get('executed_by') != 'controller_offline_review_suite'
            or receipt.get('exit_code') != 0 or receipt.get('network') != 'none'
            or receipt.get('snapshot_mount') != 'readonly'
            or receipt.get('manifest_sha256') != unit['base_manifest_sha256']
            or receipt.get('source_task') != row[1]
            or type(receipt.get('tests')) is not int
            or receipt['tests'] != unit['prior_test_count']
            or suite_digest(receipt.get('test_image'), receipt.get('test_command')) != config['policy']['suite_sha256']):
        raise ValueError('prior checkpoint full suite binding mismatch')
    ledger._hash(receipt.get('output_sha256'))
    binding = con.execute('SELECT source_task_id FROM review_bindings WHERE request_id=?',(row[0],)).fetchone()
    if not binding or binding[0] != row[1]:
        raise ValueError('prior suite native binding missing')


def test_review(con, config, unit, issue_id):
    row=con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue_id,)).fetchone()
    if not row:
        raise ValueError('independent test review unavailable')
    state=json.loads(row[0]); decision=state.get('decision',{})
    reviewer=config['policy']['test_reviewer']; task=state.get('review_task')
    execution(con,task,issue_id,reviewer,'planning')
    if (state.get('status') not in ('approved','blocked')
            or state.get('manifest_sha256') != unit['red_manifest_sha256']
            or decision.get('manifest_sha256') != unit['red_manifest_sha256']
            or decision.get('optional_files') != []
            or decision.get('action') not in ('approve_test_revision','reject_test_revision')):
        raise ValueError('exact independent test decision required')
    if (state['status']=='approved') != (decision['action']=='approve_test_revision'):
        raise ValueError('revalidated or invalidated decision cannot be reused')
    if decision['action']=='approve_test_revision' and (state['status']!='approved'
            or state.get('read_contract')!='complete-lines-v2'):
        raise ValueError('new complete observed-read review required')
    reads=state.get('read_evidence',{})
    for name in unit['new_test_sha256']:
        observed=reads.get('/evidence/candidate/'+name,{})
        if (type(observed.get('lines')) is not int or observed['lines']<=0
                or observed['lines']!=observed.get('total_lines')):
            raise ValueError('complete real new-test inspection required')
    return dict(operation='test_review',source_task=config['source_task'],unit=_unit_id(config,unit),
        proposal_sha256=config['proposal_sha256'],base_manifest_sha256=unit['base_manifest_sha256'],
        suite_sha256=config['policy']['suite_sha256'],task_id=task,
        manifest_sha256=unit['red_manifest_sha256'],reviewer=reviewer,
        red_receipt_sha256=unit['red'],decision='approve' if state['status']=='approved' else 'request_changes')


def green(con, config, unit, issue_id, source_task, review_task):
    execution(con,source_task,issue_id,config['policy']['author'],'implementation')
    request=execution(con,review_task,issue_id,config['policy']['delivery_reviewer'],'review')
    row=con.execute("SELECT source_task,volume,receipt FROM review_suite_rpc WHERE request_id=? AND status='passed'",
                    (request,)).fetchone()
    snapshot=con.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'",(source_task,)).fetchone()
    if not row or row[0]!=source_task or not snapshot or snapshot[0]!=row[1]:
        raise ValueError('current complete delivery snapshot and independent suite required')
    proof=json.loads(row[2])
    if (proof.get('evidence_version')!=2 or proof.get('source_task')!=source_task
            or proof.get('review_task')!=review_task
            or proof.get('executed_by')!='controller_offline_review_suite'
            or proof.get('network')!='none' or proof.get('snapshot_mount')!='readonly'
            or proof.get('exit_code')!=0
            or proof.get('base_manifest_sha256')!=unit.get('materialized_base_manifest_sha256',unit['base_manifest_sha256'])
            or proof.get('baseline_test_sha256')!=unit['baseline_test_sha256']
            or proof.get('new_test_sha256')!=unit['new_test_sha256']
            or suite_digest(proof.get('test_image'),proof.get('test_command'))!=config['policy']['suite_sha256']):
        raise ValueError('new full-suite Green with frozen tests required')
    ledger._hash(proof.get('output_sha256'));ledger._hash(proof.get('manifest_sha256'))
    return dict(operation='green',source_task=config['source_task'],unit=_unit_id(config,unit),
        proposal_sha256=config['proposal_sha256'],base_manifest_sha256=unit['base_manifest_sha256'],
        suite_sha256=config['policy']['suite_sha256'],task_id=source_task,
        manifest_sha256=proof['manifest_sha256'],author=config['policy']['author'],
        red_manifest_sha256=unit['red_manifest_sha256'],test_sha256=proof['new_test_sha256'],
        baseline_test_sha256=proof['baseline_test_sha256'],exit_code=0,full_suite=True,test_count=proof['tests'])


def delivery_review(con, config, unit, issue_id, source_task, review_task):
    # Also requires an exact V2 suite receipt; no legacy optional-proof approval.
    proof=green(con,config,unit,issue_id,source_task,review_task)
    row=con.execute('SELECT reviewer_agent_id,manifest_sha256,status FROM reviews '
        'WHERE review_task_id=? AND source_task_id=?',(review_task,source_task)).fetchone()
    if (not row or row[0]!=config['policy']['delivery_reviewer']
            or row[1]!=unit['green_manifest_sha256'] or row[1]!=proof['manifest_sha256']
            or row[2] not in ('approved','changes_requested')):
        raise ValueError('independent current delivery decision required')
    return dict(operation='delivery_review',source_task=config['source_task'],unit=_unit_id(config,unit),
        proposal_sha256=config['proposal_sha256'],base_manifest_sha256=unit['base_manifest_sha256'],
        suite_sha256=config['policy']['suite_sha256'],task_id=review_task,
        manifest_sha256=unit['green_manifest_sha256'],reviewer=row[0],
        green_receipt_sha256=unit['green'],decision='approve' if row[2]=='approved' else 'request_changes')
