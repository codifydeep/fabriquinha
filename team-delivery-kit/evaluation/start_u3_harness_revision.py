"""Controller-only provisioning of the authentic CTO-sponsored U3 revision."""
import json

import broker as b
import incremental_provisioning as provisioning
import test_revision_review

ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
settings=json.loads((b.STATE/'native.json').read_text())
issues=provisioning.NativeIssues(settings)
with b.LOCK,b.db() as con:
    config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(ROOT,)).fetchone())
    unit=state['units']['U3']
    assert unit['revision']==3 and unit['test_repair']['operation']=='cto_source_harness_revision_v1'
    assert unit['test_repair']['decision_task']=='01a107b9-cc53-77a5-88f4-f2a725d2966b'
    assert not state['execution_authorized']
    parent=issues.request('/issues/'+config['issue_id'])
    created=provisioning.ensure_issues(con,ROOT,parent,issues)
binding=provisioning.provision_next(b.handoff_context(),ROOT,'U3','tests/test_incremental_u3.py')
trial=test_revision_review.register(b.handoff_context(),dict(issue_id=binding['issue_id'],parent_issue=unit['test_repair']['parent_issue']))
assert trial['cto_decision']==unit['test_repair']['decision_task']
activation=provisioning.activate_next(b.handoff_context(),ROOT,'U3')
print(json.dumps(dict(issue_id=binding['issue_id'],revision=3,status='activated_tests_only',
    identifiers=[r.get('identifier') for r in created if r.get('issue_id')==binding['issue_id']],
    delivery_approval=False)))
