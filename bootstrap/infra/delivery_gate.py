"""Fail-closed delivery evidence checks for the local Truco board."""
import json
import hashlib
import subprocess
import re
from pathlib import Path
from release_policy import active_release, validate_report


def run(path, *args):
    p = subprocess.run(args, cwd=path, text=True, capture_output=True, timeout=30)
    if p.returncode:
        raise ValueError((p.stderr or p.stdout).strip()[:400])
    return p.stdout.strip()


def read_git_evidence(repo,branch,path):
    relative=Path(path)
    if relative.is_absolute() or '..' in relative.parts or not path:
        raise ValueError('evidence path must be repository-relative')
    ref=f'origin/{branch}:{path}'
    size=int(run(repo,'git','cat-file','-s',ref))
    if not 0<size<=16*1024*1024:
        raise ValueError('evidence must be nonempty and bounded to 16 MiB')
    return subprocess.check_output(['git','show',ref],cwd=repo,timeout=30)


def verify_report_evidence(conn,repo,release,report,evidence):
    """Hash-check committed outputs and independent QA/deploy provenance."""
    artifacts=[]
    for kind,owner,required in [('qa','quality_security',{'unit','integration','e2e','regression','security'}),
                               ('deployment','devops',{'compose','health','rollback'})]:
        item=report[kind]
        event=conn.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='review_requested' ORDER BY id DESC LIMIT 1",(item['card'],)).fetchone()
        provenance=json.loads(event['payload']) if event else {}
        from review_policy import validate_review
        if provenance.get('implementer')!=owner or validate_review(owner,provenance.get('reviewer')):
            raise ValueError(kind+' card lacks independent reviewed authorship')
        raw=read_git_evidence(repo,release['branch'],item['evidence'])
        if hashlib.sha256(raw).hexdigest()!=item.get('evidence_sha256'):
            raise ValueError(kind+' evidence checksum mismatch')
        artifacts.append(evidence.capture_bytes(item['evidence'],raw))
        data=json.loads(raw)
        if data.get('attempt')!=release['attempt'] or data.get('commit')!=report['commit']:
            raise ValueError(kind+' evidence belongs to another attempt/commit')
        checks=data.get('checks',[])
        if not required.issubset({c.get('name') for c in checks}):
            raise ValueError(kind+' is missing required executed checks')
        for check in checks:
            if not check.get('command') or type(check.get('exit_code')) is not int or check['exit_code']!=0:
                raise ValueError(kind+' checks must include successful real commands')
            output=read_git_evidence(repo,release['branch'],check['output_file'])
            if hashlib.sha256(output).hexdigest()!=check.get('output_sha256'):
                raise ValueError(kind+' command output checksum mismatch')
            artifacts.append(evidence.capture_bytes(check['output_file'],output))
    return artifacts


def check_delivery(conn, task_id):
    from e2e_boundary import registered
    from planning_flow import registered as planning_registered
    if registered(conn,task_id) or planning_registered(conn,task_id):
        # All live completions pass the controller's approve hook before this
        # native gate. Finished cards must retain that exact receipt.
        state=conn.execute('SELECT status FROM tasks WHERE id=?',(task_id,)).fetchone()
        if state['status']=='done':
            runs=conn.execute('SELECT id,metadata FROM task_runs WHERE task_id=? ORDER BY id DESC',(task_id,)).fetchall()
            proof=next((json.loads(r['metadata'] or '{}').get('immutable_review') for r in runs if json.loads(r['metadata'] or '{}').get('immutable_review')),None)
            if not proof or not proof.get('approved'): return 'E2E completion lacks controller approval'
        return None
    row = conn.execute('SELECT title,status,workspace_kind,workspace_path,branch_name FROM tasks WHERE id=?', (task_id,)).fetchone()
    if row and row['workspace_kind']=='scratch' and row['status']!='done':
        try:
            from scratch_validation import verify_registered
            verify_registered(conn,task_id,row)
            if row['workspace_path']:
                from scratch_evidence import snapshot
                snapshot(conn,task_id,row['workspace_path'])
        except Exception as exc:
            return 'scratch evidence gate: '+str(exc)
    if row and row['title'].startswith('SPIKE-'):
        try:
            root = Path(row['workspace_path']).resolve(strict=True)
            report = json.loads((root / 'spike-result.json').read_text())
            for key in ('hypothesis', 'criterion', 'conclusion', 'decision'):
                if not isinstance(report.get(key), str) or not report[key].strip():
                    return 'SPIKE missing hypothesis/criterion/conclusion/decision'
            if not report.get('commands'):
                return 'SPIKE missing executed command evidence'
            for command in report['commands']:
                if not command.get('command') or type(command.get('exit_code')) is not int:
                    return 'SPIKE command/exit code missing'
                output = (root / command['output_file']).resolve(strict=True)
                if not output.is_relative_to(root) or not output.is_file() or output.stat().st_size == 0:
                    return 'SPIKE command output must be a nonempty file in its workspace'
            return None
        except Exception as exc:
            return 'SPIKE evidence rejected: ' + str(exc)
    if row and row['title'].startswith('RELEASE-'):
        try:
            release = active_release()
            if release['controller'] != task_id:
                return 'controller differs from active release registry'
            path, branch = release['repo'], release['branch']
            run(path, 'git', 'fetch', 'origin', branch)
            raw = run(path, 'git', 'show', f"origin/{branch}:docs/releases/{branch.split('/')[-1]}/homologation.json")
            report = json.loads(raw)
            tasks = {r['id']: r['status'] for r in conn.execute('SELECT id,status FROM tasks')}
            validate_report(report, tasks, release if release.get('attempt') else None)
            artifacts=[]
            if release.get('attempt'):
                from delivery_receipts import EvidenceStore
                evidence=EvidenceStore('/opt/data/governance/evidence',release['attempt'])
                artifacts=verify_report_evidence(conn,path,release,report,evidence)
                artifacts.append(evidence.capture_bytes('homologation.json',raw.encode()))
            run(path, 'git', 'merge-base', '--is-ancestor', report['commit'], 'origin/' + branch)
            checks = json.loads(run(path, 'gh', 'api', 'repos/codifydeep/truco-online/commits/' + report['commit'] + '/check-runs'))['check_runs']
            latest = {}
            for check in sorted(checks, key=lambda c: c['id']):
                latest[check['name']] = check
            if latest.get('governance', {}).get('conclusion') != 'success':
                return 'release commit missing successful governance CI'
            # A report alone is not proof of a live deployment. Exact service
            # identities and revisions are checked against Docker at completion.
            services = report.get('services', [])
            if not services:
                return 'deployed service/container evidence required'
            if release.get('attempt') and (not release.get('expected_services') or set(services)!=set(release['expected_services'])):
                return 'deployed service set differs from reviewed architecture baseline'
            for name in services:
                if not re.fullmatch(r'truco-online-hml-[a-z0-9_-]+', name):
                    return 'invalid homologation container name'
                info = json.loads(run(path, 'docker', 'inspect', name))[0]
                labels = info.get('Config', {}).get('Labels', {}) or {}
                if labels.get('com.codifydeep.project') != 'truco-online' or labels.get('org.opencontainers.image.revision') != report['commit']:
                    return 'deployment project/revision labels do not match report'
                if info['State'].get('Health', {}).get('Status') != 'healthy':
                    return 'deployment service missing healthy healthcheck'
            if release.get('attempt') and row['status']!='done':
                from delivery_receipts import record_verified
                record_verified(release,task_id,dict(kind='homologation',commit=report['commit'],
                    report_sha256=hashlib.sha256(raw.encode()).hexdigest(),report=report,
                    criteria=release['approved_criteria'],services=services,artifacts=artifacts))
            return None
        except Exception as exc:
            return 'release gate: ' + str(exc)
    if row and row['title'].startswith('INCIDENT-'):
        match = re.match(r'INCIDENT-(t_[0-9a-f]+)', row['title'])
        source = conn.execute('SELECT status FROM tasks WHERE id=?', (match[1],)).fetchone() if match else None
        if not source or source['status'] != 'done':
            return 'incident cannot complete: source has not resumed'
        if source['status'] == 'done':
            from incident_completion import completion_error
            return completion_error(conn, match[1], check_delivery)
        return None
    if not row or row['workspace_kind'] != 'worktree':
        return None
    # GRAPH is a Kanban-only artifact: its existing independent review and
    # created-card validation gates apply; it has no implementation PR.
    if row['title'].startswith('GRAPH-'):
        return None
    path, branch = row['workspace_path'], row['branch_name']
    try:
        if not path or not branch:
            return 'delivery has no workspace/branch'
        release = active_release()
        if not Path(path).exists() and release.get('attempt') and row['status']=='done':
            from delivery_receipts import previous_receipt
            receipt=previous_receipt(release,task_id)
            if not receipt or receipt.get('branch')!=branch:
                return 'removed workspace has no matching immutable receipt'
            head=receipt['commit']
            path=release['repo']
        else:
            head = run(path, 'git', 'rev-parse', 'HEAD')
            if run(path, 'git', 'branch', '--show-current') != branch:
                return 'workspace branch differs from assigned branch'
            if run(path, 'git', 'status', '--porcelain'):
                return 'workspace contains uncommitted changes'
        base = release['branch']
        prs = json.loads(run(path, 'gh', 'pr', 'list', '--repo', 'codifydeep/truco-online', '--head', branch, '--state', 'merged', '--json', 'number,headRefOid,baseRefName'))
        match = next((p for p in prs if p['headRefOid'] == head and p['baseRefName'] == base), None)
        if not match:
            return 'assigned branch HEAD has no merged PR into ' + base
        checks = json.loads(run(path, 'gh', 'pr', 'view', str(match['number']), '--repo', 'codifydeep/truco-online', '--json', 'statusCheckRollup'))['statusCheckRollup']
        if not checks or any((c.get('conclusion') or c.get('state')) != 'SUCCESS' for c in checks):
            return 'merged PR has missing or unsuccessful CI checks'
        if release.get('attempt') and not {'governance','hermes-independent-review'}.issubset({c.get('name') or c.get('context') for c in checks}):
            return 'merged PR lacks required governance/independent-review checks'
        run(path, 'git', 'fetch', 'origin', base)
        run(path, 'git', 'merge-base', '--is-ancestor', head, 'origin/' + base)
        if release.get('attempt') and row['status']!='done':
            from delivery_receipts import record_verified
            record_verified(release,task_id,dict(kind='implementation',commit=head,branch=branch,
                release_branch=base,pr=match['number'],checks=checks))
    except Exception as exc:
        return 'delivery verification failed: ' + str(exc)
    return None
