"""Fixed broker adapter for persistent delivery coordination; no arbitrary commands."""
import hashlib
import json
import re
import time
import uuid
import urllib.request
import urllib.error

try:
    import handoffs
    import native
    import test_first_handoffs
except ImportError:
    from broker import handoffs, native, test_first_handoffs


class BudgetStatusUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('model proxy status unavailable')
        self.incident=dict(category='model_proxy_status_unavailable',version=1,
            endpoint='model_proxy_status',owner='devops',required_action='health_check_only',
            first_observed_at=time.time(),next_check_at=time.time()+10,health_checks=0,
            delivery_approval=False)


def initialize(con):
    handoffs.initialize(con)
    con.execute('CREATE TABLE IF NOT EXISTS contract_revisions('
                'decision_task TEXT PRIMARY KEY, issue_id TEXT, source_task TEXT, '
                'volume TEXT, manifest_sha256 TEXT, contract_sha256 TEXT, body TEXT, at REAL)')
    con.execute('CREATE TABLE IF NOT EXISTS task_contracts(task_id TEXT PRIMARY KEY, decision_task TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS snapshot_diagnostics(task_id TEXT PRIMARY KEY, diagnostic TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS delivery_tdd(task_id TEXT PRIMARY KEY, receipt TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS delivery_tdd_events(task_id TEXT, call_id TEXT, body TEXT, PRIMARY KEY(task_id,call_id))')
    con.execute('CREATE TABLE IF NOT EXISTS handoff_publications(issue_id TEXT PRIMARY KEY, digest TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS handoff_publication_errors(issue_id TEXT PRIMARY KEY, attempts INTEGER, next_at REAL, reason TEXT)')
    con.commit()


def register(broker, route):
    keys = {'issue_id', 'author', 'reviewer', 'techlead', 'cto', 'contract_sha256',
            'review_instruction', 'minimum_calls', 'enabled'}
    test_first_keys = keys | {'test_first', 'test_first_files'}
    if not isinstance(route, dict) or set(route) not in (keys, test_first_keys,
            keys | {'execution_context'}, test_first_keys | {'execution_context'}):
        raise ValueError('invalid handoff route')
    if 'execution_context' in route:
        from execution_context import resolve
        resolve(route['execution_context'], route['review_instruction'], 'review')
    if 'test_first' in route:
        from portable_contract import safe_path
        names = route['test_first_files']
        if (route['test_first'] is not True or not isinstance(names, list)
                or not 0 < len(names) <= 32 or len(set(names)) != len(names)):
            raise ValueError('invalid test-first route mode')
        for name in names:
            safe_path(name)
            if not (name.endswith('.py') and name.rsplit('/', 1)[-1].startswith('test_')
                    or name.endswith(('.test.js', '.spec.js'))):
                raise ValueError('test-first file is not a test')
    for key in ('issue_id', 'author', 'reviewer', 'techlead', 'cto'):
        if str(uuid.UUID(route[key])) != route[key]:
            raise ValueError('invalid route identity')
    settings = json.loads((broker.STATE / 'native.json').read_text())
    roles = {'author': 'implementation', 'reviewer': 'review', 'techlead': 'planning', 'cto': 'planning'}
    if any(settings['agents'].get(route[key]) != role for key, role in roles.items()):
        raise ValueError('handoff role mismatch')
    if len({route[k] for k in roles}) != 4:
        raise ValueError('handoff roles must be independent')
    if (not re.fullmatch(r'[a-f0-9]{64}', route['contract_sha256'])
            or type(route['enabled']) is not bool
            or type(route['minimum_calls']) is not int or not 4 <= route['minimum_calls'] <= 64
            or not isinstance(route['review_instruction'], str)
            or not 1 <= len(route['review_instruction']) <= 2500):
        raise ValueError('invalid route limits')
    broker.issue_base(route['issue_id'])
    with broker.LOCK, broker.db() as con:
        if route.get('test_first'):
            editable = {r[0].removeprefix('/workspace/') for r in con.execute(
                'SELECT path FROM issue_editables WHERE issue_id=?', (route['issue_id'],))}
            if not set(route['test_first_files']) <= editable:
                raise ValueError('test-first files not registered editable')
        prior = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (route['issue_id'],)).fetchone()
        if prior:
            old = json.loads(prior[0])
            if {k:v for k,v in old.items() if k != 'enabled'} != {k:v for k,v in route.items() if k != 'enabled'}:
                raise ValueError('handoff route immutable except pause')
        con.execute('INSERT OR REPLACE INTO delivery_routes VALUES (?,?)',
                    (route['issue_id'], json.dumps(route, sort_keys=True)))
    return {'issue_id': route['issue_id'], 'enabled': route['enabled']}


def bind_contract(broker, task_id, issue_id):
    with broker.db() as con:
        row = con.execute('SELECT decision_task FROM contract_revisions WHERE issue_id=? ORDER BY at DESC LIMIT 1',
                          (issue_id,)).fetchone()
        # An explicit legacy binding prevents retroactive contract replacement.
        con.execute('INSERT OR IGNORE INTO task_contracts VALUES (?,?)', (task_id, row[0] if row else None))


def task_base(broker, issue_id, task_id):
    original = broker.issue_base(issue_id)
    with broker.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='task_contracts'").fetchone():
            return original
        row = con.execute('SELECT r.* FROM task_contracts t JOIN contract_revisions r '
                          'USING(decision_task) WHERE t.task_id=? AND r.issue_id=?',
                          (task_id, issue_id)).fetchone()
    if not row:
        return original
    volume = broker.docker('GET', '/volumes/' + row['volume'])
    if not volume or volume.get('Labels', {}).get('delivery-kit.decision-task') != row['decision_task']:
        raise ValueError('contract revision volume identity mismatch')
    return {**original, 'volume': row['volume'], 'manifest_sha256': row['manifest_sha256']}


class Effects:
    def sponsor_inherited_test_replan(self,route,data,task,decision):
        try:import inherited_test_replan
        except ImportError:from broker import inherited_test_replan
        return inherited_test_replan.sponsor(self,route,data,task,decision)

    def pre_red_format_rejection(self, route, recipient):
        """Exact native binding plus a sanitized receipt from the pinned proxy."""
        b=self.b
        with b.db() as con:
            rows=con.execute('SELECT request_id,agent_id,issue_id FROM native_bindings WHERE task_id=?',
                             (recipient['id'],)).fetchall()
        if (len(rows)!=1 or rows[0]['agent_id']!=route['cto']
                or rows[0]['issue_id']!=route['issue_id']):
            raise ValueError('independent CTO execution binding required')
        try:import execution_diagnosis_recovery
        except ImportError:from broker import execution_diagnosis_recovery
        return execution_diagnosis_recovery.format_rejection(b,rows[0]['request_id'],
            expected_image='sha256:ae1f1d76281235060a5001b07d63c701d79ba420055df3f6b809b7072f8c5734')

    def capture_report(self, issue):
        try: import capture_diagnosis
        except ImportError: from broker import capture_diagnosis
        report = capture_diagnosis.load(self.b, issue)
        return report if report and report['witnesses'] else None

    def validate_capture_decision(self, route, data, recipient, decision):
        try: import capture_diagnosis
        except ImportError: from broker import capture_diagnosis
        report = self.capture_report(route['issue_id'])
        if not report or capture_diagnosis.summary(report) != data['capture_constraints']:
            raise ValueError('capture report identity drift')
        proof = capture_diagnosis.validate(decision, report, self.read_evidence(recipient))
        return {**proof, 'version': 'complete-source-replan-v1',
                'issue_id': route['issue_id'], 'source_task': data['source_task'],
                'decision_task': recipient['id'], 'baseline_edits_allowed': False,
                'output_sha256': data['validation_failure']['output_sha256']}

    def test_review_report(self, issue, red, previous):
        try: import test_review_report
        except ImportError: from broker import test_review_report
        return test_review_report.create(self.b, issue, red, previous)

    def read_evidence(self, recipient):
        from artifact_read_evidence import observations
        try:import read_stream_receipts
        except ImportError:from broker import read_stream_receipts
        with self.b.db() as con:
            durable=read_stream_receipts.load(con,recipient['id'])
        return read_stream_receipts.observed(native.task_messages(self.settings, recipient['id']),durable)

    def __init__(self, broker, settings):
        self.b = broker
        self.settings = settings

    def freeze(self, task):
        if self.test_first_red(task):
            # In this route the controller already executed and froze Red.
            # Freeze the final delivery now; Green is run by validate().
            return self.b.snapshot_submission({'task_id': task})
        tdd_error = None
        try:
            self.tdd_receipt(task)
        except ValueError as error:
            tdd_error = str(error)
        with self.b.db() as con:
            failure = con.execute('SELECT diagnostic FROM snapshot_diagnostics WHERE task_id=?', (task,)).fetchone()
        if failure:
            raise ValueError(failure[0] + ('; ' + tdd_error if tdd_error else ''))
        try:
            snapshot = self.b.snapshot_submission({'task_id': task})
        except ValueError as error:
            raise ValueError(str(error) + ('; ' + tdd_error if tdd_error else '')) from None
        if tdd_error:
            raise ValueError(tdd_error)
        return snapshot

    def phase_evidence(self, task):
        red = self.test_first_red(task)
        if not red:
            return None
        with self.b.db() as con:
            row = con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',
                              (red['issue_id'],)).fetchone()
        state = json.loads(row[0]) if row else {}
        return {'phase': 'implementation', 'red_manifest': red['red']['manifest_sha256'],
                'red_exit_code': red['red']['exit_code'],
                'frozen_test_hashes': red['red']['test_sha256'],
                'independent_test_review': state.get('status'),
                'instruction': 'Red exists. Never recreate Red or edit frozen tests.'}

    def validate(self, snapshot, task):
        red = self.test_first_red(task)
        if red:
            result = self.b.validate_frozen_delivery(snapshot['volume'], task)
            self.b.verify_test_first_green(snapshot['volume'], task, red)
            receipt = {'mode': 'controller_test_first', 'red': red['red'],
                       'green': {'manifest_sha256': result['manifest_sha256'],
                                 'tests': result['tests'], 'executed_by_controller': True},
                       'test_task': red['task_id'], 'implementation_task': task}
            if red.get('issue_id'):
                receipt['red_origin_issue'] = red['issue_id']
                receipt['red_origin_scope'] = red['scope']
            with self.b.db() as con:
                con.execute('INSERT OR IGNORE INTO delivery_tdd VALUES (?,?)',
                            (task, json.dumps(receipt, sort_keys=True)))
            return {**result, 'tdd': receipt}
        receipt = self.tdd_receipt(task)
        result = self.b.validate_frozen_delivery(snapshot['volume'], task)
        return {**result, 'tdd': receipt}

    def test_first_red(self, task, *, diagnostic=False):
        try:
            import remediation_red_reference
        except ImportError:
            from broker import remediation_red_reference
        dependent = remediation_red_reference.task_red(self.b, task,diagnostic=diagnostic)
        if dependent is not None:
            return dependent
        with self.b.db() as con:
            binding = con.execute('SELECT issue_id,scope FROM native_bindings WHERE task_id=? '
                                  'ORDER BY rowid DESC LIMIT 1', (task,)).fetchone()
            if not binding:
                return None
            row = con.execute('SELECT task_id,scope,volume,receipt FROM test_first_red '
                              'WHERE issue_id=?', (binding['issue_id'],)).fetchone()
        if not row:
            return None
        if row['task_id'] == task or row['scope'] != binding['scope']:
            raise ValueError('test-first implementation scope or task mismatch')
        volume = self.b.docker('GET', '/volumes/' + row['volume'])
        if (not volume or volume.get('Labels', {}).get('delivery-kit.owner') != self.b.OWNER
                or volume.get('Labels', {}).get('delivery-kit.test-first-task') != row['task_id']):
            raise ValueError('test-first Red volume identity mismatch')
        return json.loads(row['receipt'])

    def tdd_receipt(self, task):
        try:
            from tdd_evidence import collect
        except ImportError:
            from broker.tdd_evidence import collect
        with self.b.db() as con:
            binding = con.execute('SELECT issue_id,agent_id FROM native_bindings WHERE task_id=? LIMIT 1', (task,)).fetchone()
            command = con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?', (binding['issue_id'],)).fetchone()[0]
        runs = sorted([r for r in native.issue_task_runs(self.settings, binding['issue_id'])
                       if r.get('agent_id') == binding['agent_id']],
                      key=lambda r: (r.get('created_at') or '', r['id']))
        messages = []
        for order, run in enumerate(runs):
            messages.extend({**m, '_run_order': order} for m in native.task_messages(self.settings, run['id']))
            if run['id'] == task:
                break
        receipt = collect(messages, command)
        with self.b.db() as con:
            con.execute('INSERT OR IGNORE INTO delivery_tdd VALUES (?,?)', (task, json.dumps(receipt, sort_keys=True)))
            for phase in ('red', 'green'):
                item = receipt[phase]
                events = [m for m in messages if m.get('task_id') == item['task_id']
                          and m.get('call_id') == item['call_id'] and m.get('type') in ('tool_use', 'tool_result')]
                con.execute('INSERT OR IGNORE INTO delivery_tdd_events VALUES (?,?,?)',
                            (item['task_id'], item['call_id'], json.dumps(events, sort_keys=True)))
        return receipt

    def assign(self, task, reviewer):
        with self.b.db() as con:
            rows = con.execute('SELECT h.* ,r.config FROM delivery_handoffs h JOIN delivery_routes r USING(issue_id)').fetchall()
            current = next((json.loads(r['data']) for r in rows if r['source_task'] == task), {})
            for row in rows:
                data = json.loads(row['data'])
                if row['source_task'] == task or not json.loads(row['config'])['enabled']:
                    continue
                if (data.get('target') == reviewer and data.get('dispatch_stage') == 'ready_review'
                        and row['stage'] in ('dispatch_intent', 'awaiting_acceptance', 'accepted')):
                    return False
                if (row['stage'] == 'ready_review' and data.get('reviewer') == reviewer
                        and (data.get('review_ready_at', 0), row['source_task'])
                        < (current.get('review_ready_at', 0), task)):
                    return False
            busy = con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                               "WHERE n.agent_id=? AND l.status IN ('creating','running')", (reviewer,)).fetchone()
            if busy:
                return False
        return self.b.assign_review({'source_task_id': task, 'review_agent_id': reviewer})

    def remaining_calls(self):
        try:
            with urllib.request.urlopen('http://model-proxy:8080/status', timeout=5) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (502,503,504):raise
            raise BudgetStatusUnavailable() from None
        except (urllib.error.URLError,TimeoutError):
            raise BudgetStatusUnavailable() from None
        if (set(result) != {'calls', 'max_calls', 'remaining'}
                or any(type(v) is not int or v < 0 for v in result.values())
                or result['calls'] + result['remaining'] != result['max_calls']):
            raise ValueError('invalid budget status')
        return result['remaining']

    def implementation_available(self, issue, author):
        with self.b.db() as con:
            busy = con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                               "WHERE n.issue_id=? AND n.agent_id=? AND l.status IN ('creating','running') LIMIT 1",
                               (issue, author)).fetchone()
        return not busy

    def ensure_wakeup(self, *args, **kwargs):
        return native.ensure_task_handoff(self.settings, *args, **kwargs)

    def ensure_unit_start(self, *args, **kwargs):
        return native.ensure_unit_start(self.settings, *args, **kwargs)

    def ensure_planning_start(self, *args, **kwargs):
        return native.ensure_planning_start(self.settings, *args, **kwargs)

    def capture_test_first_red(self, payload):
        return self.b.capture_test_first_red(payload)

    def capture_failed_test_checkpoint(self, issue, task):
        try:
            import failed_test_checkpoint
        except ImportError:
            from broker import failed_test_checkpoint
        return failed_test_checkpoint.capture(self.b, issue, task)

    def transport_qualification(self, issue_id, task_id):
        try:import transport_qualification
        except ImportError:from broker import transport_qualification
        return transport_qualification.capture(self.b,issue_id,task_id)

    def verified_tool_incident(self, issue_id, task_id):
        try:import verified_tool_incident
        except ImportError:from broker import verified_tool_incident
        return verified_tool_incident.capture(self.b,issue_id,task_id)

    def test_first_failure(self, issue_id, task_id):
        import uuid
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError('invalid test-first diagnostic task')
        path = self.b.STATE / 'test-first-incidents' / (task_id + '.json')
        if not path.exists():
            try:import artifact_rejection_evidence
            except ImportError:from broker import artifact_rejection_evidence
            diagnostic=artifact_rejection_evidence.fetch(self.b,issue_id,task_id)
            if diagnostic:return diagnostic
            try:import unchanged_seed_diagnosis
            except ImportError:from broker import unchanged_seed_diagnosis
            return unchanged_seed_diagnosis.capture(self.b,issue_id,task_id)
        diagnostic = json.loads(path.read_text())
        if (diagnostic.get('kind') not in ('rejected_red','rejected_snapshot')
                or diagnostic.get('issue_id') != issue_id or diagnostic.get('task_id') != task_id):
            raise ValueError('test-first diagnostic identity mismatch')
        return diagnostic

    def review_result(self, review, source):
        with self.b.db() as con:
            row = con.execute('SELECT * FROM reviews WHERE review_task_id=? AND source_task_id=?',
                              (review, source)).fetchone()
            if not row:
                incident = con.execute('SELECT reason FROM review_incidents WHERE review_task_id=?', (review,)).fetchone()
                if incident:
                    raise ValueError('review_protocol_failure: ' + incident[0])
                return None
            result = dict(row)
            if result['status'] == 'changes_requested':
                finding = con.execute('SELECT finding FROM review_findings WHERE review_task_id=?', (review,)).fetchone()
                if finding:
                    result['finding'] = finding[0]
                else:
                    messages = native.task_messages(self.settings, review)
                    texts = '\n'.join(m.get('content') or '' for m in messages if m.get('type') == 'text')
                    matches = re.findall(r'Reason:\s*([^\n]+)', texts)
                    if not matches:
                        raise ValueError('review correction lacks concrete finding')
                    result['finding'] = matches[-1][:600]
            return result

    def decomposition_proposal(self,recipient):
        try:import test_decomposition
        except ImportError:from broker import test_decomposition
        return test_decomposition.parse_proposal(recipient,native.task_messages(self.settings,recipient['id']))

    def decision(self, recipient):
        # A completed native task's result is the authoritative final response.
        # Its message stream may include other text and can be absent after restart.
        output = (recipient.get('result') or {}).get('output')
        if isinstance(output, str) and output.strip():
            text = output.strip()
        else:
            messages = native.task_messages(self.settings, recipient['id'])
            text = ''.join(m.get('content') or '' for m in messages if m.get('type') == 'text').strip()
        fenced = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', text, re.IGNORECASE | re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        if len(text) > 5000:
            raise ValueError('technical decision too large')
        decision = json.loads(text)
        test_review = decision.get('action') in ('approve_test_revision', 'reject_test_revision')
        expected_keys = {'action', 'reason', 'optional_files'} | ({'manifest_sha256'} if test_review else set())
        if re.search(r'^DELIVERY_TEST_FINDINGS_V1$', recipient.get('handoff_note') or '', re.MULTILINE):
            expected_keys.add('findings')
        if re.search(r'^DELIVERY_CAPTURE_CONSTRAINTS_V1$', recipient.get('handoff_note') or '', re.MULTILINE):
            expected_keys.add('capture_resolutions')
        if re.search(r'^DELIVERY_SEMANTIC_CHECKS_V1$', recipient.get('handoff_note') or '', re.MULTILINE):
            expected_keys |= {'experiment_sha256', 'semantic_checks'}
        if (set(decision) != expected_keys
                or decision['action'] not in ('request_correction', 'retry_author', 'retry_review', 'revise_contract', 'request_test_revision', 'escalate_cto', 'approve_test_revision', 'reject_test_revision')
                or not isinstance(decision['reason'], str) or not 1 <= len(decision['reason']) <= 3000
                or not isinstance(decision['optional_files'], list)):
            raise ValueError('invalid technical decision')
        if test_review and (decision['optional_files'] or not isinstance(decision['manifest_sha256'], str)
                            or not re.fullmatch(r'[a-f0-9]{64}', decision['manifest_sha256'])):
            raise ValueError('invalid exact-snapshot test review')
        if decision['action'] == 'request_test_revision' and decision['optional_files']:
            raise ValueError('test revision cannot relax contract files')
        return decision

    def revise_contract(self, route, source, decision_task, decision):
        b = self.b
        with b.db() as con:
            existing = con.execute('SELECT * FROM contract_revisions WHERE decision_task=?', (decision_task,)).fetchone()
        if existing:
            return {'contract_sha256': existing['contract_sha256']}
        base = task_base(b, route['issue_id'], source)
        volume = b.PREFIX + '-contract-' + decision_task
        labels = {'delivery-kit.owner': b.OWNER, 'delivery-kit.decision-task': decision_task}
        existing_volume = b.docker('GET', '/volumes/' + volume)
        if existing_volume and any(existing_volume.get('Labels', {}).get(k) != v for k,v in labels.items()):
            raise ValueError('foreign contract volume')
        if not existing_volume:
            b.docker('POST', '/volumes/create', {'Name': volume, 'Labels': labels})
        name = volume + '-job'
        old = b.docker('GET', '/containers/' + name + '/json')
        if old:
            if old['Config'].get('Labels', {}).get('delivery-kit.decision-task') != decision_task:
                raise ValueError('foreign contract job')
            b.docker('DELETE', '/containers/' + old['Id'] + '?force=true')
        b.docker('POST', '/containers/create?name=' + name, {
            'Image': b.IMAGE, 'User': '10000:10000', 'Entrypoint': ['python'],
            'Cmd': ['/contract_revision.py'], 'NetworkDisabled': True, 'Labels': labels,
            'Env': ['OPTIONAL_FILES=' + json.dumps(decision['optional_files'])],
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges'], 'Memory': 67108864, 'PidsLimit': 16,
                'Mounts': [{'Type': 'volume', 'Source': base['volume'], 'Target': '/base', 'ReadOnly': True},
                           {'Type': 'volume', 'Source': volume, 'Target': '/revision'}]}})
        try:
            b.docker('POST', '/containers/' + name + '/start')
            deadline = time.time() + 20
            while time.time() < deadline:
                state = b.docker('GET', '/containers/' + name + '/json')['State']
                if not state['Running']:
                    if state['ExitCode']:
                        raise ValueError('technical replan violates contract policy')
                    result = json.loads(b.docker_stdout(name))
                    with b.db() as con:
                        con.execute('INSERT INTO contract_revisions VALUES (?,?,?,?,?,?,?,?,?)',
                            (decision_task, route['issue_id'], source, volume, result['manifest_sha256'],
                             result['contract_sha256'], json.dumps(result['contract'], sort_keys=True), time.time()))
                    return {'contract_sha256': result['contract_sha256']}
                time.sleep(.2)
            raise TimeoutError('contract revision timeout')
        finally:
            b.docker('DELETE', '/containers/' + name + '?force=true')


def tick(broker):
    try: import adapted_test_review
    except ImportError: from broker import adapted_test_review
    adapted_test_review.tick(broker)
    settings = json.loads((broker.STATE / 'native.json').read_text())
    effects = Effects(broker, settings)
    with broker.db() as con:
        routes = [json.loads(r[0]) for r in con.execute('SELECT config FROM delivery_routes')]
    for route in routes:
        try:import incremental_dispatch
        except ImportError:from broker import incremental_dispatch
        with broker.db() as con:
            if incremental_dispatch.owns(con,route['issue_id']):continue
        if not route['enabled']:
            safe_publish(broker, route, None)
            continue
        try:
            issue = native.issue_record(settings, route['issue_id'])
            if issue.get('status') in ('cancelled', 'done'):
                continue
            runs = native.issue_task_runs(settings, route['issue_id'])
            if route.get('test_first'):
                runs = test_first_handoffs.reconcile(broker, route, runs, effects)
                if runs is None:
                    with broker.db() as con:
                        state = con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? '
                                            'ORDER BY updated DESC LIMIT 1',
                                            (route['issue_id'],)).fetchone()
                    safe_publish(broker, route, dict(state) if state else None)
                    continue
            with broker.db() as con:
                handoffs.reconcile(con, route, runs, effects)
                state = con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',
                                    (route['issue_id'],)).fetchone()
            safe_publish(broker, route, dict(state) if state else None)
        except Exception as error:
            # Durable operational incident, without converting failure into success.
            with broker.db() as con:
                row = con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',
                                  (route['issue_id'],)).fetchone()
                if row:
                    data = json.loads(row['data'])
                    reason = type(error).__name__ + ':' + str(error)[:240]
                    count = data.get('control_error_count', 0) + 1 if data.get('control_error') == reason else 1
                    data.update(control_error=reason, control_error_count=count)
                    stage = row['stage'] if count < 2 else (
                        'technical_decision_required' if data.get('target') == route['cto'] else 'diagnose_cto')
                    handoffs.save(con, row['source_task'], route['issue_id'], stage, route['cto'], data, time.time())
                else:
                    con.execute('INSERT INTO delivery_handoff_events(source_task,stage,data,at) VALUES (?,?,?,?)',
                        (route['issue_id'], 'controller_error', json.dumps({'error': type(error).__name__,
                        'reason': str(error)[:240], 'owner': route['cto']}), time.time()))


def safe_publish(broker, route, state):
    with broker.db() as con:
        failure = con.execute('SELECT * FROM handoff_publication_errors WHERE issue_id=?', (route['issue_id'],)).fetchone()
    if failure and failure['next_at'] > time.time():
        return
    try:
        publish(broker, route, state)
        with broker.db() as con:
            con.execute('DELETE FROM handoff_publication_errors WHERE issue_id=?', (route['issue_id'],))
    except Exception as error:
        attempts = min((failure['attempts'] if failure else 0) + 1, 6)
        with broker.db() as con:
            con.execute('INSERT OR REPLACE INTO handoff_publication_errors VALUES (?,?,?,?)',
                (route['issue_id'], attempts, time.time() + min(10 * 2**attempts, 300), type(error).__name__))


def publish(broker, route, state):
    """Idempotent card metadata; publishing failures never change delivery state."""
    details = json.loads(state['data']) if state else {}
    value = {'stage': (state['stage'] if state else 'waiting_author') if route['enabled'] else 'paused',
             'owner': state['owner'] if state else route['techlead'],
             'source_task': state['source_task'] if state else None,
             'next_action': details.get('required_action') or details.get('resume_stage')
                            or details.get('dispatch_stage') or 'technical_preflight',
             'reason': details.get('control_error') or details.get('error') or details.get('reason') or ''}
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    with broker.db() as con:
        old = con.execute('SELECT digest FROM handoff_publications WHERE issue_id=?', (route['issue_id'],)).fetchone()
    if old and old[0] == digest:
        return
    runtime = broker.PREFIX + '-runtime-1'
    info = broker.docker('GET', '/containers/' + runtime + '/json')
    labels = info.get('Config', {}).get('Labels', {}) if info else {}
    if labels.get('com.docker.compose.project') != broker.PREFIX or labels.get('com.docker.compose.service') != 'runtime':
        raise ValueError('handoff status runtime identity mismatch')
    execution = broker.docker('POST', '/containers/' + runtime + '/exec', {
        'User': '10000:10000', 'AttachStdout': False, 'AttachStderr': False,
        'Cmd': ['multica', 'issue', 'metadata', 'set', route['issue_id'], '--key', 'delivery_handoff',
                '--value', encoded, '--type', 'string']})
    broker.docker('POST', '/exec/' + execution['Id'] + '/start', {'Detach': True, 'Tty': False})
    deadline = time.time() + 10
    while time.time() < deadline:
        outcome = broker.docker('GET', '/exec/' + execution['Id'] + '/json')
        if not outcome['Running']:
            if outcome['ExitCode']:
                raise RuntimeError('handoff status publication failed')
            with broker.db() as con:
                con.execute('INSERT OR REPLACE INTO handoff_publications VALUES (?,?)', (route['issue_id'], digest))
            return
        time.sleep(.1)
    raise TimeoutError('handoff status publication timeout')
