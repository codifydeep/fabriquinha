"""Explicitly authorized tests-only recovery, never a route override."""
import hashlib,json,sqlite3
import broker as b
import admission_recovery,incremental_provisioning as provisioning,test_revision_review
ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
CTO='01a107e7-1da4-7ecb-a6a1-fcf7fb1b2ec8'
with b.LOCK,b.db() as con:
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    backup=b.STATE/'u3-before-admission-recovery-20261004.sqlite'
    if not backup.exists():
        with sqlite3.connect(backup) as target:
            con.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
receipt=admission_recovery.prepare(b.handoff_context(),ROOT,'U3',CTO)
settings=json.loads((b.STATE/'native.json').read_text());issues=provisioning.NativeIssues(settings)
with b.LOCK,b.db() as con:
    config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(ROOT,)).fetchone())
    assert state['units']['U3']['revision']==4 and state['units']['U3']['admission_hold']['recovery_state']=='tests_only'
    parent=issues.request('/issues/'+config['issue_id'])
    created=provisioning.ensure_issues(con,ROOT,parent,issues)
binding=provisioning.provision_next(b.handoff_context(),ROOT,'U3','tests/test_incremental_u3.py')
trial=test_revision_review.register(b.handoff_context(),dict(issue_id=binding['issue_id'],parent_issue=receipt['parent_issue']))
assert trial['cto_decision']==CTO and trial['seeded_edit_required'] and trial['source_harness_diagnosis']
activation=provisioning.activate_next(b.handoff_context(),ROOT,'U3')
print(json.dumps(dict(status='activated_tests_only',issue_id=binding['issue_id'],revision=4,
    identifiers=[r.get('identifier') for r in created if r.get('issue_id')==binding['issue_id']],
    delivery_approval=False,backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest())))
