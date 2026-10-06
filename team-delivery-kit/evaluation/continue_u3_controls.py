"""Evidence-qualified diagnosis and NEW tests-only controls completion."""
import hashlib,json,sqlite3,sys
import broker as b
import admission_diagnosis,admission_recovery,native,incremental_provisioning as provisioning,test_revision_review
ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
action=sys.argv[1]
assert action in ('diagnose','prepare')
with b.LOCK,b.db() as con:
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    backup=b.STATE/'u3-before-controls-completion-20261004.sqlite'
    if not backup.exists():
        with sqlite3.connect(backup) as target:
            con.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
if action=='diagnose':
    result=admission_diagnosis.dispatch(b.handoff_context(),ROOT,'U3',['app/static/app.js','app/static/index.html'])
else:
    settings=json.loads((b.STATE/'native.json').read_text())
    with b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(ROOT,)).fetchone())
        u=state['units']['U3']
        if u['revision']==5:
            decision_task=u['test_repair']['decision_task']
        else:
            assert u['revision']==4
            row=con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(u['binding']['issue_id'],)).fetchone()
            data=json.loads(row[0]);route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(u['binding']['issue_id'],)).fetchone()[0])
            runs=[r for r in native.issue_task_runs(settings,route['issue_id']) if r.get('agent_id')==route['cto'] and r.get('wakeup_id')==data.get('wakeup_id')]
            if len(runs)!=1 or runs[0]['status']!='completed':
                print(json.dumps(dict(status='awaiting_exact_cto',delivery_approval=False)));sys.exit(0)
            decision_task=runs[0]['id']
    receipt=admission_recovery.prepare(b.handoff_context(),ROOT,'U3',decision_task)
    assert receipt['operation']=='cto_controls_completion_v1'
    issues=provisioning.NativeIssues(settings)
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(ROOT,)).fetchone())
        assert state['units']['U3']['revision']==5 and state['units']['U3']['admission_hold']
        created=provisioning.ensure_issues(con,ROOT,issues.request('/issues/'+config['issue_id']),issues)
    binding=provisioning.provision_next(b.handoff_context(),ROOT,'U3','tests/test_incremental_u3.py')
    trial=test_revision_review.register(b.handoff_context(),dict(issue_id=binding['issue_id'],parent_issue=receipt['parent_issue']))
    assert trial['cto_decision']==decision_task and trial['seeded_edit_required']
    provisioning.activate_next(b.handoff_context(),ROOT,'U3')
    result=dict(status='activated_controls_tests_only',revision=5,issue_id=binding['issue_id'],cto_task=decision_task,
        identifiers=[r.get('identifier') for r in created if r.get('issue_id')==binding['issue_id']],delivery_approval=False)
result['backup_sha256']=hashlib.sha256(backup.read_bytes()).hexdigest()
print(json.dumps(result))
