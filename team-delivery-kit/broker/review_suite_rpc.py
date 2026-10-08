"""Execution-scoped capability for one fixed offline suite; never accepts argv."""
import hashlib
import hmac
import json
import time


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS review_suite_rpc('
                'request_id TEXT PRIMARY KEY, digest TEXT UNIQUE, source_task TEXT, '
                'volume TEXT, status TEXT, receipt TEXT)')


def binding(broker, con, request_id):
    row = con.execute('SELECT g.mode,g.deadline AS grant_deadline,g.used,g.attempt,'
        'g.task_id,n.agent_id,n.scope,n.issue_id,l.status,l.deadline AS lease_deadline,'
        'b.source_task_id,b.volume FROM grants g JOIN native_bindings n USING(request_id) '
        'JOIN leases l USING(request_id) JOIN review_bindings b USING(request_id) '
        'WHERE g.request_id=?', (request_id,)).fetchone()
    if (not row or row['mode'] != 'review' or row['status'] != 'running'
            or not row['used'] or min(row['grant_deadline'], row['lease_deadline']) <= time.time()
            or row['attempt'] != con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',
                                            (row['task_id'],)).fetchone()[0]):
        raise ValueError('review suite requires current active review lease')
    assignment = con.execute('SELECT source_task_id,volume FROM review_assignments '
                             'WHERE review_agent_id=?', (row['agent_id'],)).fetchone()
    snapshot = con.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'",
                           (row['source_task_id'],)).fetchone()
    source = con.execute('SELECT agent_id FROM native_bindings WHERE task_id=? '
                         'ORDER BY rowid DESC LIMIT 1', (row['source_task_id'],)).fetchone()
    if (not assignment or tuple(assignment) != (row['source_task_id'], row['volume'])
            or not snapshot or snapshot['volume'] != row['volume']
            or not source or source['agent_id'] == row['agent_id']):
        raise ValueError('review suite snapshot or independence drift')
    return row


def issue(broker, request_id):
    with broker.LOCK, broker.db() as con:
        initialize(con)
        row = binding(broker, con, request_id)
        token = hmac.new(broker.TOKEN.encode(), ('review-suite-v1:' + request_id).encode(),
                         hashlib.sha256).hexdigest()
        prior = con.execute('SELECT source_task,volume FROM review_suite_rpc WHERE request_id=?',
                            (request_id,)).fetchone()
        if prior and tuple(prior) != (row['source_task_id'], row['volume']):
            raise ValueError('review suite capability binding changed')
        con.execute('INSERT OR IGNORE INTO review_suite_rpc VALUES (?,?,?,?,?,?)',
                    (request_id, hashlib.sha256(token.encode()).hexdigest(),
                     row['source_task_id'], row['volume'], 'issued', '{}'))
    return token


def execute(broker, token, payload):
    if payload != {} or not isinstance(token, str) or len(token) != 64:
        raise ValueError('review suite parameters are controller-owned')
    with broker.LOCK, broker.db() as con:
        initialize(con)
        capability = con.execute('SELECT * FROM review_suite_rpc WHERE digest=?',
            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not capability:
            raise ValueError('invalid review suite capability')
        row = binding(broker, con, capability['request_id'])
        if (row['source_task_id'], row['volume']) != (capability['source_task'], capability['volume']):
            raise ValueError('review suite capability identity drift')
        broker.assert_review_task_running(row)
        if capability['status'] == 'passed':
            return json.loads(capability['receipt'])
        if capability['status'] not in ('issued','observing','running'):
            raise ValueError('review suite failed or interrupted; diagnosis required')
        if capability['status']!='issued' and json.loads(capability['receipt']).get('durable_validation')!=1:
            raise ValueError('historical interrupted review cannot be upgraded; diagnosis required')
        con.execute("UPDATE review_suite_rpc SET status='running',receipt=? WHERE request_id=?",
                    (json.dumps({'durable_validation':1}),capability['request_id']))
        con.commit()  # An interrupted execution must not be silently repeated.
        try:
            try: from validation_job import Pending
            except ImportError: from broker.validation_job import Pending
            deadline=time.monotonic()+25
            while True:
                try:
                    result = broker.validate_frozen_delivery(row['volume'], row['source_task_id'],
                        suite_evidence=True, review_request_id=capability['request_id'])
                    break
                except Pending:
                    if time.monotonic()>=deadline:raise
                    binding(broker,con,capability['request_id'])
                    broker.assert_review_task_running(row)
                    time.sleep(.2)
            # Legacy fixture validators execute their own suite and cannot claim
            # this new isolation qualification; require the portable runner.
            if not result.get('portable') or not result.get('suite'):
                raise ValueError('isolated review requires portable suite evidence')
            binding(broker, con, capability['request_id'])
            broker.assert_review_task_running(row)
            suite = result['suite']
            receipt = {'output': suite['output'], 'exit_code': 0,
                'executed_by': 'controller_offline_review_suite', 'cwd': '/delivery',
                'review_task': row['task_id'], 'source_task': row['source_task_id'],
                'manifest_sha256': result['manifest_sha256'], 'tests': result['tests'],
                'test_image': suite['test_image'], 'test_command': suite['test_command'],
                'output_sha256': suite['output_sha256'], 'network': 'none',
                'snapshot_mount': 'readonly', 'finished_at': time.time()}
            if result.get('checkpoint_evidence'):
                receipt.update(evidence_version=2, **result['checkpoint_evidence'])
            if suite.get('validation_job_key'):
                receipt.update(validation_job_key=suite['validation_job_key'],
                               validation_contract_sha256=suite['validation_contract_sha256'])
            con.execute("UPDATE review_suite_rpc SET status='passed',receipt=? WHERE request_id=?",
                        (json.dumps(receipt, sort_keys=True), capability['request_id']))
            return receipt
        except Exception as error:
            if isinstance(error,Pending):
                con.execute("UPDATE review_suite_rpc SET status='observing',receipt=? WHERE request_id=?",
                    (json.dumps({'durable_validation':1,'next_action':'observe_same_validation_job'}),capability['request_id']))
                con.commit()
                return {'status':'pending','executed_by':'controller_offline_review_suite',
                        'next_action':'observe_same_validation_job'}
            con.execute("UPDATE review_suite_rpc SET status='failed',receipt=? WHERE request_id=?",
                (json.dumps({'error_type': type(error).__name__, 'operation':getattr(error,'operation',None),
                             'next_action': 'technical_diagnosis'}),
                 capability['request_id']))
            con.commit()
            raise


def require_approval_proof(con, request_id, source_task, manifest):
    """New RPC-bound reviews cannot approve without their own successful run."""
    initialize(con)
    row = con.execute('SELECT source_task,status,receipt FROM review_suite_rpc WHERE request_id=?',
                      (request_id,)).fetchone()
    if not row:
        return  # Historical reviews are not retroactively upgraded to this contract.
    receipt = json.loads(row['receipt'])
    if (row['status'] != 'passed' or row['source_task'] != source_task
            or receipt.get('source_task') != source_task
            or receipt.get('manifest_sha256') != manifest
            or receipt.get('executed_by') != 'controller_offline_review_suite'
            or receipt.get('exit_code') != 0):
        raise ValueError('review approval requires exact offline suite receipt')
