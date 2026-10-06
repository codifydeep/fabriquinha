"""Controller-only preservation of a lost worker; never a submission or approval.

No worker endpoint. Native completion and a lost lease remain distinct facts.
The immutable diagnostic copy cannot be assigned as a delivery review snapshot.
"""
import hashlib
import json
import re
import time
import uuid


def diagnosis_data(copy, suite, route):
    failure = suite.get('validation_failure') or {}
    if (copy.get('status') != 'complete' or copy.get('lease_status') != 'lost'
            or copy.get('submission') is not False or copy.get('delivery_approval') is not False
            or copy.get('issue_id') != route['issue_id'] or copy.get('author') != route['author']
            or copy.get('inspection', {}).get('frozen_tests_unchanged') is not True
            or suite.get('status') != 'failed' or suite.get('green_checkpoint') is not False
            or suite.get('delivery_approval') is not False or suite.get('task_id') != copy['task_id']
            or suite.get('volume') != copy['volume']
            or suite.get('manifest_sha256') != copy['inspection']['manifest_sha256']
            or failure.get('source_task') != copy['task_id'] or failure.get('volume') != copy['volume']
            or failure.get('category') != 'executed_test_failure'
            or not re.fullmatch(r'[a-f0-9]{64}',failure.get('output_sha256',''))
            or failure.get('exit_code') == 0 or not failure.get('tests_executed')
            or len({route['author'],route['cto'],route['techlead'],route['reviewer']}) != 4):
        raise ValueError('exact lost preservation and executed diagnostic failure required')
    failure = {**failure, 'diagnostic_only':True, 'phase':'lost_execution_diagnostic'}
    receipt = dict(operation='lost_execution_diagnosis_v1', preservation=copy, failure=failure,
                   volume=copy['volume'], source_task=copy['task_id'], delivery_approval=False)
    return dict(source_task=copy['task_id'], contract_sha256=route['contract_sha256'],
                author=route['author'],reviewer=route['reviewer'],source_status='completed',
                attempts=1,error='portable frozen suite failed',artifact_diagnosis=True,
                validation_failure=failure,lost_execution_diagnostic=receipt,
                diagnostic_revision=failure['output_sha256']+':lost-candidate-v1')


def register_diagnosis(b, root, task_id):
    """Redirect the current incident, retaining its evidence; no verdict or retry."""
    try:import native,handoffs
    except ImportError:from broker import native,handoffs
    import inspect
    if "status='closing'" not in inspect.getsource(b.session_operation):
        raise ValueError('installed durable close required')
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS lost_execution_diagnoses(source_task TEXT PRIMARY KEY,receipt TEXT)')
            copy=json.loads(c.execute('SELECT receipt FROM lost_execution_preservations WHERE task_id=?',(task_id,)).fetchone()[0])
            suite=json.loads(c.execute('SELECT receipt FROM lost_preservation_diagnostic_suites WHERE task_id=?',(task_id,)).fetchone()[0])
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(copy['issue_id'],)).fetchone()[0])
            state=json.loads(c.execute('SELECT state FROM incremental_checkpoints WHERE source_task=?',(root,)).fetchone()[0])
            units=[u for u in state['units'].values() if u.get('binding',{}).get('issue_id')==copy['issue_id']]
            row=dict(c.execute('SELECT n.task_id,n.request_id,n.agent_id,n.scope,n.issue_id,g.mode,l.status,l.name '
                               'FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) '
                               'WHERE n.task_id=? ORDER BY g.attempt DESC LIMIT 1',(task_id,)).fetchone())
            active=c.execute("SELECT count(*) FROM leases WHERE status IN ('running','creating','starting','closing')").fetchone()[0]
            incident=c.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(root,)).fetchone()
            old=c.execute('SELECT receipt FROM lost_execution_diagnoses WHERE source_task=?',(task_id,)).fetchone()
        settings=json.loads((b.STATE/'native.json').read_text())
        qualify(native.task_record(settings,task_id,route['author']),native.issue_task_runs(settings,copy['issue_id']),
                row,route,active,b.docker('GET','/containers/'+row['name']+'/json') is not None)
        if (not state['execution_authorized'] or len(units)!=1 or units[0]['stage']!='awaiting_green'
                or not route['enabled'] or row['request_id']!=copy['request_id']):
            raise ValueError('current active incremental failed unit required')
        data=diagnosis_data(copy,suite,route);receipt=data['lost_execution_diagnostic']
        if old:
            if json.loads(old[0])!=receipt:raise ValueError('lost diagnosis lineage drift')
            return receipt
        if not incident or json.loads(incident[0]).get('category')!='ValueError':
            raise ValueError('exact blocked snapshot incident required')
        volume=b.docker('GET','/volumes/'+copy['volume']);labels=(volume or {}).get('Labels',{})
        if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task_id
                or labels.get('delivery-kit.diagnostic-only')!='true'):
            raise ValueError('preserved diagnostic volume identity drift')
        with b.db() as c:
            current=c.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(root,)).fetchone()
            if not current or current[0]!=incident[0]:raise ValueError('runtime incident changed')
            data['previous_runtime_incident']=json.loads(incident[0])
            c.execute('INSERT INTO lost_execution_diagnoses VALUES(?,?)',(task_id,json.dumps(receipt,sort_keys=True)))
            c.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=? AND receipt=?',(root,incident[0]))
            handoffs.save(c,task_id,route['issue_id'],'diagnose_cto',route['cto'],data,time.time())
        return receipt


def qualify(task, runs, binding, route, active, worker_exists):
    authors = [r for r in runs if r.get('agent_id') == route['author']]
    latest = max(authors, key=lambda r: (r.get('created_at') or '', r['id'])) if authors else None
    if (task.get('status') != 'completed' or task.get('agent_id') != route['author']
            or task.get('issue_id') != route['issue_id'] or not latest
            or latest['id'] != task['id'] or binding['task_id'] != task['id']
            or binding['agent_id'] != route['author'] or binding['issue_id'] != route['issue_id']
            or binding['mode'] != 'implementation' or binding['status'] != 'lost'
            or active or worker_exists
            or any(r.get('status') in ('queued', 'dispatched', 'running') for r in runs)):
        raise ValueError('exact latest completed author, lost absent worker and idle scope required')


def preserve(b, task_id):
    if str(uuid.UUID(task_id)) != task_id:
        raise ValueError('canonical task identity required')
    try:
        import native
    except ImportError:
        from broker import native
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS lost_execution_preservations('
                      'task_id TEXT PRIMARY KEY,receipt TEXT)')
            row = c.execute('SELECT n.task_id,n.request_id,n.agent_id,n.scope,n.issue_id,'
                            'g.mode,l.status,l.name FROM native_bindings n '
                            'JOIN grants g USING(request_id) JOIN leases l USING(request_id) '
                            'WHERE n.task_id=? ORDER BY g.attempt DESC LIMIT 1', (task_id,)).fetchone()
            if not row:
                raise ValueError('native binding missing')
            row = dict(row)
            route = json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                         (row['issue_id'],)).fetchone()[0])
            red = json.loads(c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',
                                       (row['issue_id'],)).fetchone()[0])
            active = c.execute("SELECT count(*) FROM leases WHERE status IN "
                               "('creating','running','starting','closing')").fetchone()[0]
            prior = c.execute('SELECT receipt FROM lost_execution_preservations WHERE task_id=?',
                              (task_id,)).fetchone()
        settings = json.loads((b.STATE / 'native.json').read_text())
        task = native.task_record(settings, task_id, row['agent_id'])
        runs = native.issue_task_runs(settings, row['issue_id'])
        qualify(task, runs, row, route, active,
                b.docker('GET', '/containers/' + row['name'] + '/json') is not None)
        work = b.PREFIX + '-work-' + hashlib.sha256(row['scope'].encode()).hexdigest()[:32]
        workspace = b.docker('GET', '/volumes/' + work)
        if (not workspace or workspace.get('Labels', {}).get('delivery-kit.owner') != b.OWNER
                or workspace.get('Labels', {}).get('delivery-kit.scope') != row['scope']):
            raise ValueError('lost workspace identity drift')
        base = b.handoff_runtime.task_base(b.handoff_context(), row['issue_id'], task_id)
        controller = b.docker('GET', '/containers/' + b.PREFIX + '-execution-broker-1/json')
        labels = (controller or {}).get('Config', {}).get('Labels', {})
        image = (controller or {}).get('Image', '')
        if (labels.get('com.docker.compose.project') != b.PREFIX
                or labels.get('com.docker.compose.service') != 'execution-broker'
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', image)):
            raise ValueError('exact installed controller helper image required')
        volume = b.PREFIX + '-lost-preservation-' + task_id
        receipt = dict(operation='lost_execution_preservation_v1', task_id=task_id,
                       request_id=row['request_id'], issue_id=row['issue_id'], author=row['agent_id'],
                       lease_status='lost', native_status='completed', workspace=work,
                       base_volume=base['volume'], volume=volume, helper_image=image,
                       frozen_test_sha256=red['red']['test_sha256'],
                       status='creating', delivery_approval=False, submission=False)
        if prior:
            previous = json.loads(prior[0])
            if any(previous.get(k) != v for k, v in receipt.items() if k != 'status'):
                raise ValueError('lost preservation lineage drift')
            receipt = previous
        existing = b.docker('GET', '/volumes/' + volume)
        if existing and (not prior or existing.get('Labels', {}).get('delivery-kit.source-task') != task_id
                         or existing.get('Labels', {}).get('delivery-kit.owner') != b.OWNER
                         or existing.get('Labels', {}).get('delivery-kit.diagnostic-only') != 'true'):
            raise ValueError('untracked preservation volume')
        with b.db() as c:
            c.execute('INSERT OR IGNORE INTO lost_execution_preservations VALUES(?,?)',
                      (task_id, json.dumps(receipt, sort_keys=True)))
        b.docker('POST', '/volumes/create', {'Name': volume, 'Labels': {
            'delivery-kit.owner': b.OWNER, 'delivery-kit.source-task': task_id,
            'delivery-kit.diagnostic-only': 'true'}})
        init = b.PREFIX + '-lost-volume-init-' + uuid.uuid4().hex
        b.docker('POST', '/containers/create?name=' + init, {
            'Image': image, 'User': '0:0', 'WorkingDir': '/', 'Entrypoint': ['python'],
            'Cmd': ['-c', 'import os;os.chown("/snapshot",10000,10000)'],
            'NetworkDisabled': True,
            'Labels': {'delivery-kit.owner': b.OWNER, 'delivery-kit.source-task': task_id},
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
                          'CapAdd': ['CHOWN'], 'SecurityOpt': ['no-new-privileges'],
                          'Memory': 67108864, 'PidsLimit': 16,
                          'Mounts': [{'Type': 'volume', 'Source': volume, 'Target': '/snapshot'}]}})
        try:
            b.docker('POST', '/containers/' + init + '/start')
            end = time.monotonic() + 15
            while time.monotonic() < end:
                info = b.docker('GET', '/containers/' + init + '/json')
                if info and not info['State']['Running']:
                    if info['State']['ExitCode']:
                        raise ValueError('preservation destination ownership initialization failed')
                    break
                time.sleep(.2)
            else:
                raise TimeoutError('preservation destination initialization deadline')
        finally:
            b.docker('DELETE', '/containers/' + init + '?force=true')
        name = b.PREFIX + '-lost-copy-' + uuid.uuid4().hex
        # Fixed operation, no shell or supplied command. Source/base are read-only.
        command = '''import json,os
from pathlib import Path
try:
 from recovery_snapshot_inspect import copy_for_recovery,inspect
 r=json.loads(os.environ["FROZEN_HASHES"]);p=Path("/snapshot")
 proof=inspect("/base",p,r) if (p/"manifest.json").exists() else copy_for_recovery("/base","/workspace",p,r)
 print(json.dumps(proof))
except Exception as e:
 print(json.dumps(dict(error=type(e).__name__,guard=str(e) if type(e) is ValueError else 'fixed_copy_failed')))
 raise SystemExit(1)
'''
        b.docker('POST', '/containers/create?name=' + name, {
            'Image': image, 'User': '10000:10000', 'WorkingDir': '/',
            'Entrypoint': ['python'], 'Cmd': ['-c', command],
            'NetworkDisabled': True, 'Env': ['FROZEN_HASHES=' + json.dumps(receipt['frozen_test_sha256'])],
            'Labels': {'delivery-kit.owner': b.OWNER, 'delivery-kit.source-task': task_id},
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
                          'SecurityOpt': ['no-new-privileges'], 'Memory': 134217728,
                          'PidsLimit': 16, 'NanoCpus': 500000000,
                          'Mounts': [{'Type': 'volume', 'Source': work, 'Target': '/workspace', 'ReadOnly': True},
                                     {'Type': 'volume', 'Source': base['volume'], 'Target': '/base', 'ReadOnly': True},
                                     {'Type': 'volume', 'Source': volume, 'Target': '/snapshot'}]}})
        try:
            b.docker('POST', '/containers/' + name + '/start')
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                info = b.docker('GET', '/containers/' + name + '/json')
                if info and not info['State']['Running']:
                    if info['State']['ExitCode']:
                        failure = json.loads(b.docker_stdout(name))
                        receipt['copy_failure'] = failure
                        with b.db() as c:
                            c.execute('UPDATE lost_execution_preservations SET receipt=? WHERE task_id=?',
                                      (json.dumps(receipt, sort_keys=True), task_id))
                        raise ValueError('lost workspace preservation rejected: ' + failure.get('guard', 'unknown'))
                    proof = json.loads(b.docker_stdout(name))
                    if (proof.get('frozen_tests_unchanged') is not True
                            or proof.get('delivery_approval') is not False
                            or proof.get('provenance') != 'controller_recovery_snapshot_preservation_v1'
                            or not re.fullmatch(r'[a-f0-9]{64}', proof.get('manifest_sha256', ''))):
                        raise ValueError('invalid preservation proof')
                    if receipt.get('status') == 'complete' and proof != receipt.get('inspection'):
                        raise ValueError('preserved snapshot proof drift')
                    receipt.update(status='complete', inspection=proof)
                    with b.db() as c:
                        c.execute('UPDATE lost_execution_preservations SET receipt=? WHERE task_id=?',
                                  (json.dumps(receipt, sort_keys=True), task_id))
                    return receipt
                time.sleep(.2)
            raise TimeoutError('lost workspace preservation deadline')
        finally:
            b.docker('DELETE', '/containers/' + name + '?force=true')
