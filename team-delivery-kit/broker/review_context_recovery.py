"""Controller-only qualification of one changed pre-model review precondition.

No worker endpoint, author restart, verdict override or retry-counter reset.
"""
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import time
import uuid

FIXED_SERVER_SHA = 'd0b54a10a4b6237c15a622b91ebb67e7aaff3c1001b804bc68342f8b75b1b672'
WATCHDOG_FAULT_SERVER_SHA = 'fbb944964a5dbcb17f2a7b9365ffba8b1364ed7137e5c583989a50afcd11eba6'
VALIDATION_JOBS_SERVER_SHA = 'a8041213f82d7472a170f4206ebe90c312d6f22f0fc084fb5b40a6752d850e86'
PRE_MAINTENANCE_SERVER_SHA = '9a437512a4d612c05161a239c1c57f6c62105dac82eacf494df928dab1ea3b22'
PRE_POLICY_OBSERVATION_SERVER_SHA = '24295d8c77210897a2999223bc45f6a4ae593d1311fbd9a29c2f4679fe74239a'
PRE_RETIREMENT_SERVER_SHA = 'c48fc215017b378b8b6f487d9dae344aa8c9b4d5c75f0da518d0cb251de7fe98'
PRE_TRANSPORT_CLEANUP_SERVER_SHA = '9d77544110ccd83f961697eb25868fc27d8286b41444ac93ab68c6e684a98386'
PRE_GROUPED_STARTUP_SERVER_SHA = '2abcf15543df14b4d92fb469c1f5c363c99accc7bb2ae3e915d6f6eb8c92e81b'
PRE_STARTUP_RESTART_SERVER_SHA = 'fc81c3c22229b9cdc7b7b79b0effea3cb40b2c039ac9fccb1f740497a228f943'
PRE_ASYNC_STARTUP_SERVER_SHA = 'b4ba2b1cd6ea671e1d3388e23e4b07efc41cf9617cb0a357673af9353aed36d9'
PRE_START_INTENT_SERVER_SHA = '7425aac02acf0883602892e675209f5a8b78126400e5f6ad531e5eda4c07bc83'
PRE_UNCERTAIN_CREATION_SERVER_SHA = '9c7721cf1fec6718f5fc249784aba0ca958ccc5c4d6aa8fedb20e1b2f533edb3'
PRE_LINE_TEMPLATE_SERVER_SHA = '938c58f8734bd4b9089c276278f9e21b273795939bc9c151697986890cfacb78'
PRE_TEMPLATE_SERVER_SHA = '4a8a4931ef7de58beea6f0fc353c17e5c1bc3fad33fdc77fd540af36861df819'
R1_GUARDED_SERVER_SHA = 'b9e307bddb51ea281535ae26b8dafb53fccdd3fb16bdc3a00040bd5bb5fe1fbc'
PRE_REMEDIATION_SERVER_SHA = '72bf87e256faad1f7ac04ff373fd10b5aff1c016de2d5be505064a45e6da6ace'
PREVIOUS_FIXED_SERVER_SHA = '9bd24852b561a3f11bb7d1c15baa7e5e572eda530b41a1e82e8f33a9369dae27'
LEGACY_FIXED_SERVER_SHA = 'f51fc9f6edd64b03ba9f0a13920ec544c191e45ca6448d3a81df849dd3287573'
ERROR = 'hermes session/prompt failed: session/prompt: restricted broker stream failed: broker_internal (code=-32000)'
CAPSULE_ERROR = 'hermes session/prompt failed: session/prompt: restricted broker stream failed: native_prompt_bounds (code=-32000)'


def qualified(con, issue, source, data):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='review_context_recoveries'").fetchone():
        return False
    row = con.execute('SELECT source_task,receipt FROM review_context_recoveries WHERE issue_id=?',
                      (issue,)).fetchone()
    return bool(row and row[0] == source and json.loads(row[1]) == data.get('review_context_recovery'))


def probe(b, issue, failed, recorded, *, route=None):
    """Actual native task_binding shape on minimal in-memory historical state.

    Load an independent copy of the fixed public broker module. Never swap the
    running broker's globals, clone its whole private database, or dispatch.
    """
    spec = importlib.util.spec_from_file_location('isolated_review_context_probe', b.__file__)
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    try:
        con.execute('CREATE TABLE delivery_handoffs(source_task TEXT,issue_id TEXT,stage TEXT,owner TEXT,data TEXT)')
        con.execute('CREATE TABLE snapshots(task_id TEXT,status TEXT)')
        con.execute('INSERT INTO delivery_handoffs VALUES (?,?,?,?,?)',
            (recorded['source_task'], issue['id'], 'awaiting_acceptance', failed['agent_id'], json.dumps(recorded)))
        con.execute('INSERT INTO snapshots VALUES (?,?)', (recorded['source_task'], 'complete'))
        if route and route.get('execution_context'):
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',(issue['id'],json.dumps(route)))
        @contextlib.contextmanager
        def memory_db():
            with con:
                yield con
        isolated.db = memory_db
        binding = dict(task_id=failed['id'], agent_id=failed['agent_id'],
            wakeup_id=failed['wakeup_id'], handoff_note=failed['handoff_note'])
        frame = isolated.native_task_prompt(dict(method='session/prompt', params=dict(prompt=[])),
                                           'review', issue, binding)
        if route and route.get('execution_context'):
            capsule=route['execution_context']; text=frame['params']['prompt'][0]['text']
            if capsule['description'] not in text or capsule['review_instruction'] not in text:
                raise ValueError('complete capsule contexts must survive prompt presentation')
            return dict(operation='registered_capsule_prompt_probe_v1', approval=False,
                source_task=recorded['source_task'], manifest_sha256=recorded['evidence']['manifest_sha256'],
                context_sha256=capsule['sha256'], prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                prompt_characters=len(text), original_characters=len(failed['handoff_note']))
        row = con.execute('SELECT receipt FROM review_context_presentations WHERE task_id=?',
                          (failed['id'],)).fetchone()
        if not row:
            raise ValueError('native receipt presentation not exercised')
        receipt = json.loads(row[0])
        receipt.update(prompt_sha256=hashlib.sha256(frame['params']['prompt'][0]['text'].encode()).hexdigest(),
                       prompt_characters=len(frame['params']['prompt'][0]['text']))
        return receipt
    finally:
        con.close()


def register(b, payload):
    try:
        import native, handoffs, handoff_runtime
    except ImportError:
        from broker import native, handoffs, handoff_runtime
    if not isinstance(payload, dict) or set(payload) != {'issue_id','source_task','failed_review'}:
        raise ValueError('exact review context recovery identities required')
    for value in payload.values():
        if str(uuid.UUID(value)) != value:
            raise ValueError('canonical review recovery identity required')
    actual_server_sha=hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest()
    if actual_server_sha not in {
            WATCHDOG_FAULT_SERVER_SHA,VALIDATION_JOBS_SERVER_SHA,FIXED_SERVER_SHA,PRE_MAINTENANCE_SERVER_SHA,PRE_POLICY_OBSERVATION_SERVER_SHA,PRE_RETIREMENT_SERVER_SHA,PRE_TRANSPORT_CLEANUP_SERVER_SHA,PRE_GROUPED_STARTUP_SERVER_SHA,PRE_STARTUP_RESTART_SERVER_SHA,PRE_ASYNC_STARTUP_SERVER_SHA,PRE_START_INTENT_SERVER_SHA,PRE_UNCERTAIN_CREATION_SERVER_SHA,PRE_LINE_TEMPLATE_SERVER_SHA,PRE_TEMPLATE_SERVER_SHA,R1_GUARDED_SERVER_SHA,PRE_REMEDIATION_SERVER_SHA,PREVIOUS_FIXED_SERVER_SHA,LEGACY_FIXED_SERVER_SHA}:
        raise ValueError('fixed native task_id receipt implementation required')
    issue, source = payload['issue_id'], payload['source_task']
    with b.LOCK, b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS review_context_recoveries('
                    'issue_id TEXT PRIMARY KEY,source_task TEXT,receipt TEXT)')
        old = con.execute('SELECT receipt FROM review_context_recoveries WHERE issue_id=?', (issue,)).fetchone()
        if old:
            receipt = json.loads(old[0])
            if receipt['request'] != payload:
                raise ValueError('review context recovery already consumed')
            return receipt
        row = handoffs.load(con, source)
        route_row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
        if not row or row['issue_id'] != issue or not route_row:
            raise ValueError('current review source required')
        data, route = json.loads(row['data']), json.loads(route_row[0])
        capsule_failure = (data.get('recipient_error') == CAPSULE_ERROR
                           and isinstance(route.get('execution_context'),dict))
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (issue,)).fetchone()
        if (latest[0] != source or row['stage'] != 'technical_decision_required'
                or data.get('required_action') != 'diagnose_repeated_review_execution_failure'
                or data.get('review_retries') != 1 or route.get('enabled') is not True
                or data.get('failed_dispatch_stage') != 'ready_review'
                or (data.get('recipient_error') != ERROR and not capsule_failure) or data.get('validation_failure')
                or data.get('error') != 'recipient_execution_failed'
                or data.get('decision',{}).get('action') != 'retry_review'
                or data.get('decision',{}).get('optional_files') != []):
            raise ValueError('exact exhausted pre-model review incident required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('review recovery requires idle workers')
        events = con.execute("SELECT data FROM delivery_handoff_events WHERE source_task=? "
                             "AND stage='awaiting_acceptance' ORDER BY id DESC", (source,)).fetchall()
        settings = json.loads((b.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, issue)
        failed = next((r for r in runs if r['id'] == payload['failed_review']), {})
        recorded = next((json.loads(e[0]) for e in events
            if json.loads(e[0]).get('wakeup_id') == failed.get('wakeup_id')
            and json.loads(e[0]).get('dispatch_stage') == 'ready_review'), {})
        author = next((r for r in runs if r['id'] == source), {})
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        diagnosis = next((r for r in runs if r['id'] == data.get('recipient_task')), {})
        if (any(r.get('status') in ('queued','dispatched','running') for r in runs)
                or failed.get('status') != 'failed' or failed.get('error') != data.get('recipient_error')
                or failed.get('agent_id') != route['reviewer'] or not failed.get('wakeup_id')
                or recorded.get('target') != route['reviewer']
                or recorded.get('snapshot') != data.get('snapshot')
                or recorded.get('evidence') != data.get('evidence')
                or author.get('status') != 'completed' or author.get('agent_id') != route['author']
                or not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id'] != source
                or diagnosis.get('status') != 'completed' or diagnosis.get('wakeup_id') != data.get('wakeup_id')
                or diagnosis.get('agent_id') not in (route['cto'],route['techlead'])):
            raise ValueError('exact independent failed reviewer and current completed diagnosis required')
        bindings = con.execute('SELECT l.request_id,l.status FROM native_bindings n '
                               'JOIN leases l USING(request_id) WHERE n.task_id=?', (failed['id'],)).fetchall()
        if (len(bindings) != 1 or bindings[0]['status'] != 'closed'
                or con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',
                               (bindings[0]['request_id'],)).fetchone()[0] != 0):
            raise ValueError('exact closed zero-tool review required')
        snapshot = con.execute('SELECT status FROM snapshots WHERE task_id=?', (source,)).fetchone()
        if not snapshot or snapshot['status'] != 'complete':
            raise ValueError('complete immutable delivery required')
        presentation = probe(b, native.issue_record(settings, issue), failed, recorded,
                             route=route if capsule_failure else None)
        evidence = data['evidence']
        if (presentation.get('approval') is not False or presentation.get('source_task') != source
                or presentation.get('manifest_sha256') != evidence.get('manifest_sha256')
                or (not capsule_failure and (presentation.get('original_characters',0) <= 4000
                    or not 0 < presentation.get('effective_characters',0) <= 4000
                    or not 0 < presentation.get('prompt_characters',0) <= 10000))
                or (capsule_failure and (presentation.get('operation') != 'registered_capsule_prompt_probe_v1'
                    or presentation.get('context_sha256') != route['execution_context']['sha256']
                    or not 10000 < presentation.get('prompt_characters',0) <= 32000))):
            raise ValueError('exact bounded nonapproving prompt probe required')
        checked = handoff_runtime.Effects(b, settings).validate(data['snapshot'], source)
        if (checked.get('baseline_tests_intact') is not True
                or checked.get('manifest_sha256') != evidence.get('manifest_sha256')
                or checked.get('tests') != evidence.get('tests')
                or checked.get('tdd') != evidence.get('tdd')):
            raise ValueError('frozen delivery or TDD drift')
        receipt = dict(operation='native_review_context_recovery_v1', request=payload,
            fixed_server_sha256=actual_server_sha, presentation=presentation,
            previous_blocker=data, at=time.time(), approval=False, author_restarted=False,
            preserved_review_retries=1, extra_review_limit=1)
        updated = dict(data, review_context_recovery=receipt,
            diagnostic_revision=actual_server_sha + ':native-review-context-v1', trigger_task=failed['id'])
        for key in ('instruction','dispatch_marker','dispatch_stage','target','wakeup_id',
                    'recipient_task','dispatched_at','control_error','control_error_count','decision','required_action','alerted'):
            updated.pop(key,None)
        con.execute('INSERT INTO review_context_recoveries VALUES (?,?,?)',
                    (issue, source, json.dumps(receipt,sort_keys=True)))
        handoffs.save(con, source, issue, 'diagnose_cto', route['cto'], updated, time.time())
        return receipt
