"""Operator-only immutable v2 enrollment; no dispatch or evidence conversion.

The native identities and frozen base are read from the controller, not worker
claims. Enrollment deliberately fences legacy grants until a qualified v2
execution adapter exists. Baseline hashes remain expectations until an isolated
runner verifies the actual bytes. This module has no worker HTTP endpoint.
"""
import json
import re
import time
import uuid

from portable_contract import validate as validate_contract
try:
    from . import controller_maintenance as maintenance, native, quality_lifecycle_v2 as policy
except ImportError:
    import controller_maintenance as maintenance
    import native
    import quality_lifecycle_v2 as policy


def canonical(value):
    if not isinstance(value,str) or str(uuid.UUID(value)) != value:
        raise ValueError('canonical v2 enrollment identity required')


def request(payload):
    if not isinstance(payload,dict) or set(payload)!={'plan','contract','maintenance_operation'}:
        raise ValueError('exact operator v2 enrollment request required')
    canonical(payload['maintenance_operation'])
    plan=policy.validate(payload['plan'])
    for key in ('run_id','issue_id','author','reviewer'):canonical(plan[key])
    contract=validate_contract(payload['contract'])
    tests=set(plan['baseline_tests'])|set(plan['new_tests'])
    if (plan['contract_sha256']!=policy.digest(contract)
            or tests!=set(contract['test_files'])
            or set(plan['product_files'])!=set(contract['editable_files'])-set(plan['new_tests'])
            or set(plan['protected_files'])!=set(contract['files'])-set(plan['product_files'])
            or not set(contract['protected_files'])<=set(plan['protected_files'])
            or not set(plan['new_tests'])<=set(contract['editable_files'])):
        raise ValueError('v2 plan must bind exact portable contract and file partition')
    return plan,contract


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_lifecycle_enrollments('
        'issue_id TEXT PRIMARY KEY,run_id TEXT UNIQUE,config TEXT NOT NULL,'
        'receipt TEXT NOT NULL,receipt_sha256 TEXT NOT NULL)')


def exists(con,table):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())


def lookup(con,issue_id):
    if not exists(con,'quality_lifecycle_enrollments'):return None
    row=con.execute('SELECT run_id,config,receipt,receipt_sha256 FROM quality_lifecycle_enrollments '
        'WHERE issue_id=?',(issue_id,)).fetchone()
    if not row:return None
    try:
        plan,contract=request(json.loads(row[1]));receipt=json.loads(row[2])
        if (receipt.get('operation')!='quality_lifecycle_enrollment_v2'
                or receipt.get('issue_id')!=issue_id or plan['issue_id']!=issue_id
                or receipt.get('run_id')!=row[0] or plan['run_id']!=row[0]
                or receipt.get('plan_sha256')!=policy.digest(plan)
                or receipt.get('contract_sha256')!=policy.digest(contract)
                or receipt.get('stage')!='enrolled_pending_adapter'
                or any(receipt.get(k) is not False for k in
                    ('execution_authorized','merge_authorized','delivery_approval','baseline_bytes_verified'))
                or policy.digest(receipt)!=row[3]):
            raise ValueError('invalid persisted v2 enrollment')
        return receipt
    except (KeyError,TypeError,json.JSONDecodeError) as error:
        raise ValueError('invalid persisted v2 enrollment') from error


def require_legacy_issue(con,issue_id):
    if lookup(con,issue_id) is not None:
        raise ValueError('v2 issue requires its qualified execution adapter; legacy grants forbidden')


def fresh(con,issue_id):
    # Existing holds cannot be adopted, even if every old task is terminal.
    for table in ('native_bindings','delivery_routes','delivery_handoffs','contract_revisions','product_scope_runs'):
        if exists(con,table) and con.execute('SELECT 1 FROM '+table+' WHERE issue_id=? LIMIT 1',(issue_id,)).fetchone():
            raise ValueError('fresh unexecuted issue required; legacy evidence remains unchanged')


def idle(con,b,payload):
    state=maintenance.current(con)
    if (not state or state.get('stage')!='sealed' or state.get('drained') is not True
            or state.get('namespace')!=b.PREFIX
            or state.get('operation_id')!=payload['maintenance_operation']):
        raise ValueError('exact sealed and drained controller maintenance required')
    if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing') LIMIT 1").fetchone():
        raise ValueError('active lease prevents v2 enrollment')
    if con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) '
            'WHERE g.deadline>? AND (g.used=0 OR (g.used=1 AND l.request_id IS NULL)) LIMIT 1',(time.time(),)).fetchone():
        raise ValueError('outstanding capability prevents v2 enrollment')
    if con.execute("SELECT 1 FROM controller_maintenance_cycles WHERE namespace=? AND stage='active' LIMIT 1",
            (b.PREFIX,)).fetchone():
        raise ValueError('active controller cycle prevents v2 enrollment')


def existing(con,b,payload):
    plan=payload['plan'];prior=lookup(con,plan['issue_id'])
    if prior is not None:
        raw=con.execute('SELECT config FROM quality_lifecycle_enrollments WHERE issue_id=?',
            (plan['issue_id'],)).fetchone()[0]
        if json.loads(raw)!=payload or prior['namespace']!=b.PREFIX:
            raise ValueError('v2 enrollment immutable; observe original intent')
        return prior  # Readback, never another admission or external effect.
    if con.execute('SELECT 1 FROM quality_lifecycle_enrollments WHERE run_id=?',(plan['run_id'],)).fetchone():
        raise ValueError('v2 run identity already belongs to another issue')
    idle(con,b,payload)
    fresh(con,plan['issue_id'])
    return None


def enroll(b,payload):
    # Freeze the operator input before observations, including concurrent callers.
    payload=json.loads(json.dumps(payload,allow_nan=False))
    plan,contract=request(payload)
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',b.PREFIX):
        raise ValueError('exact owned controller namespace required')
    with b.LOCK,b.db() as con:
        initialize(con)
        maintenance.transaction(con)
        prior=existing(con,b,payload)
        if prior is not None:return prior
    # Slow evidence reads never own the global admission lock or SQLite writer.
    # Sealed maintenance fences all execution throughout these observations.
    settings=json.loads((b.STATE/'native.json').read_text())
    if (settings['agents'].get(plan['author'])!='implementation'
            or settings['agents'].get(plan['reviewer'])!='review'):
        raise ValueError('independently enrolled implementation and review roles required')
    if maintenance.native_active(b):raise ValueError('native work must drain before enrollment')
    issue=native.issue_record(settings,plan['issue_id'])
    if issue.get('id')!=plan['issue_id'] or issue.get('workspace_id')!=settings['workspace_id']:
        raise ValueError('exact native issue workspace required')
    if native.issue_task_runs(settings,plan['issue_id']):
        raise ValueError('native issue already executed; no retroactive v2 conversion')
    base=b.issue_base(plan['issue_id'])
    if (base.get('issue_id')!=plan['issue_id'] or base.get('base_sha')!=plan['base_sha']
            or not isinstance(base.get('volume'),str) or not base['volume']
            or not isinstance(base.get('manifest_sha256'),str)
            or not re.fullmatch('[a-f0-9]{64}',base['manifest_sha256'])):
        raise ValueError('controller-authenticated frozen base binding required')
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        prior=existing(con,b,payload)
        if prior is not None:return prior
        # Recheck durable ownership after the native/Docker reads. Uncertainty
        # or a concurrent operator change cannot persist a partial enrollment.
        durable=con.execute('SELECT issue_id,base_sha,volume,manifest_sha256 FROM issue_bases WHERE issue_id=?',
            (plan['issue_id'],)).fetchone()
        if (not durable or tuple(durable)!=tuple(base[k] for k in
                ('issue_id','base_sha','volume','manifest_sha256'))
                or json.loads((b.STATE/'native.json').read_text())!=settings):
            raise ValueError('enrollment base or native authority changed during observation')
        receipt=dict(operation='quality_lifecycle_enrollment_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
            namespace=b.PREFIX,workspace_id=settings['workspace_id'],runtime_id=settings['runtime_id'],
            repository=contract['repository'],contract_sha256=plan['contract_sha256'],plan_sha256=policy.digest(plan),
            base_sha=base['base_sha'],base_volume=base['volume'],base_manifest_sha256=base['manifest_sha256'],
            author=plan['author'],reviewer=plan['reviewer'],maintenance_operation=payload['maintenance_operation'],
            stage='enrolled_pending_adapter',execution_authorized=False,merge_authorized=False,
            delivery_approval=False,baseline_bytes_verified=False)
        con.execute('INSERT INTO quality_lifecycle_enrollments VALUES(?,?,?,?,?)',
            (plan['issue_id'],plan['run_id'],json.dumps(payload,sort_keys=True),
                json.dumps(receipt,sort_keys=True),policy.digest(receipt)))
        return receipt
