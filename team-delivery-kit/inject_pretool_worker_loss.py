"""One-shot controlled fault, executed inside the controller (not a worker).

Arm before assignment. A paused container and absence of an ACP session prove
that session/prompt could not have started; persisted tool counts alone do not.
Never retries an uncertain kill or creates recovery/approval authority.
"""
import argparse
import json
import time
import uuid
import broker as b


def write_once(path, value):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('unsafe fault evidence')
    with path.open('x') as out:
        json.dump(value, out, sort_keys=True)
        out.write('\n')
    path.chmod(0o600)


def candidate(issue):
    with b.db() as c:
        route = c.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
        if not route:
            return None
        route = json.loads(route[0])
        if not route.get('test_first') or not route.get('enabled'):
            return None
        red = c.execute('SELECT task_id,scope,receipt FROM test_first_red WHERE issue_id=?', (issue,)).fetchone()
        reviewed = c.execute('SELECT state FROM test_revision_trials WHERE issue_id=?', (issue,)).fetchone()
        if not red or not reviewed or json.loads(reviewed[0]).get('status') != 'approved':
            return None
        proof = json.loads(red['receipt'])
        if proof['red']['exit_code'] != 1 or not proof['red']['test_sha256']:
            return None
        rows = c.execute("SELECT n.*,l.name,l.status FROM native_bindings n JOIN leases l USING(request_id) "
                         "JOIN grants g USING(request_id) WHERE n.issue_id=? AND n.agent_id=? "
                         "AND g.mode='implementation' AND l.status='running'",
                         (issue, route['author'])).fetchall()
        rows = [dict(r) for r in rows if r['task_id'] != red['task_id'] and r['scope'] == red['scope']]
        if len(rows) != 1:
            return None
        return rows[0]


def pretool(row):
    with b.db() as c:
        return (c.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',
                          (row['request_id'],)).fetchone()[0] == 0
                # The test-first worker legitimately used the same scope.
                # Check this execution, not historical sessions in that scope.
                # No completed ACP operation means the native runtime cannot
                # have received session/new or session/resume and begun prompt.
                and not c.execute('SELECT 1 FROM acp_events WHERE request_id=?',
                                  (row['request_id'],)).fetchone())


def owned(row, info):
    labels = (info or {}).get('Config', {}).get('Labels', {})
    return (info and info['State']['Running'] and labels.get('delivery-kit.owner') == b.OWNER
            and labels.get('delivery-kit.request') == row['request_id']
            and labels.get('com.docker.compose.project') == b.PREFIX + '-tests'
            and row['name'] == b.PREFIX + '-job-' + row['request_id'])


def inject(issue, timeout=900):
    if str(uuid.UUID(issue)) != issue or not 1 <= timeout <= 1800:
        raise ValueError('canonical issue and bounded deadline required')
    folder = b.STATE / 'fault-injection'
    if folder.is_symlink():
        raise ValueError('unsafe evidence directory')
    folder.mkdir(mode=0o700, exist_ok=True)
    arm = folder / (issue + '.armed.json')
    write_once(arm, dict(issue_id=issue, operation='controlled_pretool_sigkill', at=time.time()))
    print(json.dumps(dict(stage='armed', issue_id=issue)), flush=True)
    until = time.monotonic() + timeout
    seen = set()
    while time.monotonic() < until:
        row = candidate(issue)
        if not row or row['request_id'] in seen or not pretool(row):
            time.sleep(0.05)
            continue
        info = b.docker('GET', '/containers/' + row['name'] + '/json')
        if not owned(row, info):
            time.sleep(0.05)
            continue
        exact = info['Id']
        seen.add(row['request_id'])
        b.docker('POST', '/containers/' + exact + '/pause')
        checked = b.docker('GET', '/containers/' + exact + '/json')
        if not owned(row, checked) or not checked['State'].get('Paused') or not pretool(row):
            if owned(row, checked) and checked['State'].get('Paused'):
                b.docker('POST', '/containers/' + exact + '/unpause')
            continue
        # No ACP session exists while the process is paused: no prompt or tool
        # can be in flight. Identity is checked again immediately before kill.
        intent = dict(issue_id=issue, task_id=row['task_id'], request_id=row['request_id'],
                      container_id=exact, signal='SIGKILL', accepted_tools_before=0,
                      ownership_revalidated=True, paused_pretool_check=True,
                      acp_operation_absent_for_request=True, at=time.time())
        write_once(folder / (row['task_id'] + '.intent.json'), intent)
        checked = b.docker('GET', '/containers/' + exact + '/json')
        if not owned(row, checked) or not checked['State'].get('Paused') or not pretool(row):
            raise ValueError('identity changed after fault intent; inspect without repeat')
        # An uncertain acknowledgement must leave the intent, never repeat kill.
        b.docker('POST', '/containers/' + exact + '/kill?signal=SIGKILL')
        stop_deadline = time.monotonic() + 5
        while time.monotonic() < stop_deadline:
            stopped = b.docker('GET', '/containers/' + exact + '/json')
            if stopped and not stopped['State']['Running']:
                if stopped['State']['ExitCode'] != 137:
                    raise ValueError('unexpected exit after interruption')
                write_once(folder / (row['task_id'] + '.json'), dict(intent, exit_code=137,
                           operation='verified_pretool_worker_interruption'))
                print(json.dumps(dict(stage='fault_injected', **intent, exit_code=137)), flush=True)
                return
            if not stopped:
                raise ValueError('container retired before exit evidence; no recovery receipt fabricated')
            time.sleep(0.05)
        raise TimeoutError('fault exit unresolved; do not repeat kill')
    print(json.dumps(dict(stage='not_injected', issue_id=issue,
                         reason='safe_pretool_window_not_observed')), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--issue', required=True)
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    inject(args.issue, args.timeout)
