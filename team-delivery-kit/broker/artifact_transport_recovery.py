"""One recovery after real ACP qualification of response enforcement.

Operator-only, exact latest author and existing independent CTO sponsorship.
No counter resets, reconstructed Red or product edit permission.
"""
import hashlib
import json
import re
import time
import uuid


def baseline_hash(record):
    # Git base manifests store digest strings; frozen delivery manifests store
    # {bytes, sha256}. Compare actual hashes, not unlike serialized records.
    if not isinstance(record, str) or not re.fullmatch(r'[0-9a-f]{64}', record):
        raise ValueError('invalid base digest record')
    return record


def validate_probe(proof, worker_image):
    from model_policy import MODEL
    if (not isinstance(proof, dict) or proof.get('schema') != 'acp-artifact-probe-v1'
            or proof.get('status') != 'passed' or proof.get('model') != MODEL
            or proof.get('worker_image') != worker_image
            or proof.get('delivery_approval') is not False or proof.get('product_retry') is not False
            or proof.get('prompt_completed') is not True or proof.get('fixture_removed') is not True
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(proof.get('proxy_image', '')))):
        raise ValueError('bound successful actual ACP probe required')
    if str(uuid.UUID(proof['execution_id'])) != proof['execution_id']:
        raise ValueError('invalid probe execution identity')
    inspection = proof.get('inspection') or {}
    if (inspection.get('uid') != 10000 or inspection.get('syntax_valid') is not True
            or inspection.get('baseline_unchanged') is not True
            or inspection.get('credentials_absent') is not True
            or type(inspection.get('bytes')) is not int or not 0 < inspection['bytes'] <= 32768
            or type(inspection.get('test_methods')) is not int or inspection['test_methods'] < 1
            or not re.fullmatch(r'[0-9a-f]{64}', str(inspection.get('sha256', '')))):
        raise ValueError('actual preserved ACP artifact evidence required')


def reopen(b, payload):
    try:
        import handoffs, native, handoff_runtime
    except ImportError:
        from broker import handoffs, native, handoff_runtime
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'source_task', 'probe'}:
        raise ValueError('exact transport recovery identity required')
    for key in ('issue_id', 'source_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('invalid transport recovery identity')
    validate_probe(payload['probe'], b.IMAGE)
    with b.LOCK:
        with b.db() as con:
            prior = handoffs.load(con, payload['source_task'])
            if not prior or prior['issue_id'] != payload['issue_id']:
                raise ValueError('blocked transport source missing')
            data = json.loads(prior['data'])
            if data.get('transport_recovery'):
                if data['transport_recovery']['request'] != payload:
                    raise ValueError('transport recovery identity drift')
                return data['transport_recovery']
            history = [json.loads(r[0]) for r in con.execute(
                'SELECT data FROM delivery_handoffs WHERE issue_id=?', (payload['issue_id'],))]
            if any(h.get('transport_recovery') for h in history):
                raise ValueError('transport recovery already consumed for issue')
            row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (payload['issue_id'],)).fetchone()
            route = json.loads(row[0]) if row else {}
            if (prior['stage'] != 'test_first_blocked' or not route.get('enabled')
                    or not route.get('test_first') or route.get('author') == route.get('cto')):
                raise ValueError('blocked independent tests-only route required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?', (payload['issue_id'],)).fetchone():
                raise ValueError('Red already exists; transport recovery forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
                raise ValueError('transport recovery requires idle workers')
        if not b.test_artifact_phase_context(payload['issue_id'], route['author']):
            raise ValueError('artifact gate must be enabled')
        proxy = b.docker('GET', '/containers/' + b.PREFIX + '-model-proxy-1/json')
        if (not proxy or proxy.get('Image') != payload['probe']['proxy_image']
                or not proxy.get('State', {}).get('Running')
                or proxy.get('Config', {}).get('Labels', {}).get('com.docker.compose.project') != b.PREFIX):
            raise ValueError('qualified installed scoped proxy required')
        settings = json.loads((b.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        source = next((r for r in authors if r['id'] == payload['source_task']), {})
        if (not authors or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source.get('id')
                or source.get('status') != 'completed'
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('latest idle completed author required')
        sponsors = [h for h in history if h.get('structural_replan')
                    and h.get('test_first_correction_wakeup') == source.get('wakeup_id')]
        if len(sponsors) != 1:
            raise ValueError('existing structural CTO sponsorship required')
        sponsor = sponsors[0]
        cto = next((r for r in runs if r['id'] == sponsor.get('cto_task')), {})
        effects = handoff_runtime.Effects(b, settings)
        if (cto.get('status') != 'completed' or cto.get('agent_id') != route['cto']
                or effects.decision(cto) != sponsor.get('decision')
                or sponsor['decision'].get('action') != 'request_correction'
                or sponsor['decision'].get('optional_files') != []):
            raise ValueError('exact independent CTO decision required')
        try:
            b.capture_test_first_red({'task_id': source['id']})
        except ValueError as error:
            if str(error) != 'test-first NEW test has no executable test methods':
                raise
        else:
            raise ValueError('valid Red now exists; transport recovery forbidden')
        diagnostic = json.loads((b.STATE / 'test-first-incidents' / (source['id'] + '.json')).read_text())
        if (diagnostic != data.get('diagnostic') or diagnostic.get('category') != 'new_test_no_methods'
                or diagnostic.get('task_id') != source['id'] or diagnostic.get('issue_id') != payload['issue_id']
                or diagnostic.get('kind') != 'rejected_snapshot'
                or len(diagnostic.get('files', {})) != 1
                or set(diagnostic['files']) != set(route['test_first_files'])):
            raise ValueError('preserved exact no-methods diagnostic required')
        receipt = {'kind': 'qualified_acp_response_enforcement_v1', 'request': payload,
            'at': time.time(), 'previous_blocker': data.copy(), 'diagnostic': diagnostic,
            'diagnostic_sha256': hashlib.sha256(json.dumps(diagnostic, sort_keys=True).encode()).hexdigest(),
            'decision': sponsor['decision'], 'cto_task': cto['id']}
        data['transport_recovery'] = receipt
        with b.db() as con:
            handoffs.save(con, source['id'], payload['issue_id'], 'test_first_transport_recovery_pending',
                          route['author'], data, time.time())
        return receipt


def verify_preserved_failure(b, task, diagnostic, *, failed=True, framework=False):
    """Inspect a NEW diagnostic snapshot of the latest failed task, never stale Red."""
    frozen = b.snapshot_submission({'task_id': task}, diagnostic=failed)
    with b.db() as con:
        row = con.execute('SELECT issue_id FROM native_bindings WHERE task_id=?', (task,)).fetchone()
    try:
        import handoff_runtime
    except ImportError:
        from broker import handoff_runtime
    base = handoff_runtime.task_base(b, row['issue_id'], task)
    name = b.PREFIX + '-integration-verify-' + task
    import inspect
    script = 'import re\n' + inspect.getsource(baseline_hash) + '''
import hashlib,json,os
from pathlib import Path
from portable_contract import safe_path
p=Path('/delivery'); base=json.loads(Path('/base/manifest.json').read_text())['files']
raw=(p/'manifest.json').read_bytes(); current=json.loads(raw)['files']; expected=json.loads(os.environ['EXPECTED_TEST_FILES'])
for name,record in current.items():
 safe_path(name); f=p/name
 assert not f.is_symlink() and not any(x.is_symlink() for x in list(f.parents)[:len(Path(name).parts)-1])
 data=f.read_bytes(); assert len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256']
for name,record in base.items():
 if name=='contract.json':continue
 assert name in current and current[name]['sha256']==baseline_hash(record)
for name,record in expected.items():
 assert (current.get(name,{}).get('sha256')==record if isinstance(record,str) else current.get(name)==record)
framework_mismatch=False
if os.environ.get('VERIFY_FRAMEWORK')=='1':
 import ast
 contract=json.loads(Path('/base/contract.json').read_text())
 assert contract['test_command'][1:3]==['-m','unittest'] and len(expected)==1
 for name in expected:
  modules=[]
  for node in ast.walk(ast.parse((p/name).read_bytes(),filename=name)):
   if isinstance(node,ast.Import):modules.extend(alias.name.split('.')[0] for alias in node.names)
   elif isinstance(node,ast.ImportFrom) and node.level==0 and node.module:modules.append(node.module.split('.')[0])
  framework_mismatch=any(module in ('pytest','_pytest') for module in modules)
 assert framework_mismatch
print(json.dumps({'verified':True,'baseline_unchanged':True,'framework_mismatch':framework_mismatch,'manifest_sha256':hashlib.sha256(raw).hexdigest()}))
'''
    owner = b.PREFIX + '-integration-verifier-v1'
    created = False
    try:
        b.docker('POST','/containers/create?name='+name,{'Image':b.IMAGE,'User':'10000:10000',
            'Entrypoint':['python'],'Cmd':['-c',script], 'WorkingDir':'/', 'NetworkDisabled':True,
            'Env':['EXPECTED_TEST_FILES='+json.dumps(diagnostic['files']),
                   'VERIFY_FRAMEWORK='+('1' if framework else '0')],
            'Labels':{'delivery-kit.owner':owner,'delivery-kit.source-task':task},
            'HostConfig':{'ReadonlyRootfs':True,'NetworkMode':'none','CapDrop':['ALL'],
                'SecurityOpt':['no-new-privileges'],'Memory':67108864,'PidsLimit':16,
                'Mounts':[{'Type':'volume','Source':frozen['volume'],'Target':'/delivery','ReadOnly':True},
                          {'Type':'volume','Source':base['volume'],'Target':'/base','ReadOnly':True}]}})
        created = True
        b.docker('POST','/containers/'+name+'/start')
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if not info['State']['Running']:
                if info['State']['ExitCode'] != 0:raise ValueError('preserved failed workspace verification rejected')
                result=json.loads(b.docker_stdout(name,limit=2048))
                if result.get('verified') is not True or result.get('baseline_unchanged') is not True:
                    raise ValueError('preserved failed workspace verification rejected')
                return {**result,'task_id':task,'volume':frozen['volume']}
            time.sleep(.2)
        raise TimeoutError('integration verifier deadline')
    finally:
        if created:
            info=b.docker('GET','/containers/'+name+'/json')
            if info['Config'].get('Labels',{}).get('delivery-kit.owner') != owner:
                raise RuntimeError('integration verifier cleanup identity mismatch')
            b.docker('DELETE','/containers/'+name+'?force=true')


def reopen_integration(b, payload):
    """Bound changed-contract repair per measured failure class, never a reset.

At most one pre-tool read repair and one post-read compact-write replan per
issue. A changed image alone cannot authorize another attempt of either kind.
"""
    try:
        import handoffs, native, handoff_runtime
    except ImportError:
        from broker import handoffs, native, handoff_runtime
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'source_task', 'probe', 'failure'}:
        raise ValueError('exact integration repair identity required')
    for key in ('issue_id', 'source_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('invalid integration identity')
    validate_probe(payload['probe'], b.IMAGE)
    failure = payload['failure']
    compact = isinstance(failure, dict) and failure.get('selected_tool') == 'write_file'
    repair_kind = 'post_read_compact_write_replan_v1' if compact else 'pre_tool_read_schema_repair_v1'
    fields = {'origin', 'execution_id', 'call_number', 'status', 'category', 'selected_tool'}
    if compact:
        fields |= {'completion_tokens', 'output_limit', 'finish_reason'}
    # Historical metadata was inspected by the operator before proxy replacement.
    # Preserve its provenance; never pretend it is a retroactive proxy receipt.
    if (not isinstance(failure, dict) or set(failure) != fields
            or failure['origin'] != 'operator_verified_historical_proxy_metadata'
            or failure['status'] != 502
            or (failure['category'] not in ('invalid_response_encoding', 'invalid_tool_argument_json') if compact
                else failure['category'] != 'wrong_forced_arguments')
            or failure['selected_tool'] != ('write_file' if compact else 'read_file')
            or type(failure['call_number']) is not int or failure['call_number'] < 1
            or str(uuid.UUID(failure['execution_id'])) != failure['execution_id']):
        raise ValueError('exact historical integration rejection required')
    if compact and (type(failure['output_limit']) is not int or failure['output_limit'] != 8192
            or type(failure['completion_tokens']) is not int
            or failure['completion_tokens'] != failure['output_limit']
            or failure['finish_reason'] != 'tool_calls'):
        raise ValueError('observed write output budget boundary required; truncation not inferred')
    with b.LOCK:
        with b.db() as con:
            prior = handoffs.load(con, payload['source_task'])
            if not prior or prior['issue_id'] != payload['issue_id']:
                raise ValueError('failed integration handoff missing')
            data = json.loads(prior['data'])
            if data.get('integration_recovery'):
                if data['integration_recovery']['request'] != payload:
                    raise ValueError('integration recovery identity drift')
                return data['integration_recovery']
            history = [json.loads(r[0]) for r in con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?', (payload['issue_id'],))]
            if any(h.get('integration_recovery', {}).get('repair_kind') == repair_kind for h in history):
                raise ValueError('integration failure class repair already consumed for issue')
            row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (payload['issue_id'],)).fetchone()
            route = json.loads(row[0]) if row else {}
            if (prior['stage'] != 'test_first_blocked' or not route.get('enabled') or not route.get('test_first')
                    or route.get('author') == route.get('cto')):
                raise ValueError('blocked tests-only integration route required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?', (payload['issue_id'],)).fetchone():
                raise ValueError('Red exists; integration repair forbidden')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
                raise ValueError('integration repair requires idle workers')
            binding = con.execute('SELECT request_id,scope,agent_id FROM native_bindings WHERE task_id=?', (payload['source_task'],)).fetchall()
            if (len(binding) != 1 or binding[0]['request_id'] != failure['execution_id']
                    or binding[0]['agent_id'] != route['author']):
                raise ValueError('exact failed ACP execution binding required')
        settings = json.loads((b.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, payload['issue_id'])
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        failed = next((r for r in authors if r['id'] == payload['source_task']), {})
        if (not authors or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != failed.get('id')
                or failed.get('status') != 'failed'
                or failed.get('error') != 'hermes provider error: API call failed after 1 retries'
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('latest idle pre-tool provider failure required')
        messages = native.task_messages(settings, failed['id'])
        activity = None
        if compact:
            try:
                from test_author_activity import summarize
            except ImportError:
                from broker.test_author_activity import summarize
            targets = route.get('test_first_files', [])
            if len(targets) != 1:
                raise ValueError('one declared new test required for compact recovery')
            activity = summarize(messages, '/workspace/' + targets[0])
            counts = activity['tool_result_counts']
            if (counts.get('read_file:read_returned', 0) < 1
                    or activity['write_file_call_count'] != 0
                    or set(counts) != {'read_file:read_returned'}
                    or any(m.get('tool_calls') or m.get('type') in ('tool_use','tool_result')
                           and m.get('tool') != 'read_file' for m in messages)):
                raise ValueError('verified reads without writes or other tool effects required')
        elif not messages or any(m.get('type') in ('tool_use', 'tool_result') or m.get('tool_calls') for m in messages):
            raise ValueError('integration repair forbidden after tool activity')
        lineage_key = 'integration_recovery' if compact else 'transport_recovery'
        sponsors = [h for h in history if h.get(lineage_key) and h.get('artifact_recovery_wakeup') == failed.get('wakeup_id')]
        if len(sponsors) != 1:
            raise ValueError('exact failed transport recovery lineage required')
        old = sponsors[0][lineage_key]
        if compact and old.get('repair_kind') != 'pre_tool_read_schema_repair_v1':
            raise ValueError('compact replan cannot chain identical recovery')
        original = old['original_source'] if compact else old['request']['source_task']
        if payload['probe']['proxy_image'] == old['request']['probe']['proxy_image']:
            raise ValueError('changed qualified proxy required')
        proxy = b.docker('GET', '/containers/' + b.PREFIX + '-model-proxy-1/json')
        if (not proxy or proxy.get('Image') != payload['probe']['proxy_image']
                or not proxy.get('State', {}).get('Running')
                or proxy.get('Config', {}).get('Labels', {}).get('com.docker.compose.project') != b.PREFIX):
            raise ValueError('qualified installed scoped proxy required')
        if not b.test_artifact_phase_context(payload['issue_id'], route['author']):
            raise ValueError('artifact phase contract required')
        with b.db() as con:
            origin_binding = con.execute('SELECT scope,agent_id FROM native_bindings WHERE task_id=?', (original,)).fetchall()
        if (len(origin_binding) != 1 or origin_binding[0]['scope'] != binding[0]['scope']
                or origin_binding[0]['agent_id'] != route['author']):
            raise ValueError('preserved exact author workspace required')
        cto = next((r for r in runs if r['id'] == old['cto_task']), {})
        if (cto.get('status') != 'completed' or cto.get('agent_id') != route['cto']
                or handoff_runtime.Effects(b, settings).decision(cto) != old['decision']):
            raise ValueError('preserved independent CTO sponsorship required')
        diagnostic = json.loads((b.STATE / 'test-first-incidents' / (original + '.json')).read_text())
        if diagnostic != old['diagnostic']:
            raise ValueError('preserved incident changed')
        inspection = verify_preserved_failure(b, failed['id'], diagnostic)
        receipt = {'kind': 'qualified_acp_response_enforcement_v1', 'repair_kind': repair_kind,
            'request': payload, 'at': time.time(), 'original_source': original,
            'previous_transport': old, 'previous_blocker': data.copy(), 'decision': old['decision'],
            'cto_task': old['cto_task'], 'diagnostic': diagnostic, 'diagnostic_sha256': old['diagnostic_sha256'],
            'pretool_verified': not compact, 'failed_snapshot':inspection}
        if compact:
            receipt.update(postread_verified=True, activity=activity,
                recovery_policy={'first_write_max_characters':6144, 'incremental_full_coverage':True,
                                 'truncation_proven':False, 'same_class_attempt_limit':1})
        data['integration_recovery'] = receipt
        with b.db() as con:
            handoffs.save(con, failed['id'], payload['issue_id'], 'test_first_integration_recovery_pending', route['author'], data, time.time())
        return receipt
