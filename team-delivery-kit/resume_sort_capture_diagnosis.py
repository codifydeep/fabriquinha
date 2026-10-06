"""Exact, one-shot paused-route CTO challenge; never author or approval recovery."""
import json
import subprocess
import sys

ISSUE = '01a0fa1e-05ca-7bf1-b4e9-423d586d440c'
SOURCE = '01a0fa63-0ea2-7aff-aaa3-8ea66cbdd77c'
PRIOR_CTO = '01a0fa66-b818-7d1c-b6ab-c00c1feaf317'
REVISION = '991ade4c3010493e3c88a39bfa46f901302cbb961aca381e5ae1cde0b4ab4fe9:capture-challenge-v2'
EXPECTED_STAGE = 'test_revision_required'
BACKUP_NAME = 'pre-capture-challenge-20261002.sqlite'
OBSERVATION = (
    'Verify against the complete source, not operator authority: the candidate '
    'oldest_state is captured after creation, yet tests require both the original '
    'four ids and the created id 11 on that same observation. pre_submit is '
    'captured after a successful create, yet expects an initially blank status. '
    'Use distinct capture points without removing assertions or test methods. '
    'The third failure belongs to protected tests/test_feedback_filter_client.py: '
    'its getElementById mock returns null for the newly introduced sort control. '
    'Investigate preserving legacy behavior when the actual control is absent, '
    'rather than modifying baseline expectations. Read the full harness, including '
    'the long line; full-line reads are now available. Quote concrete source '
    'locations in the reason. The prior numeric-sort contradiction claim was '
    'unsupported. This is a diagnosis only; no approval or recursive revision '
    'is authorized by this maintenance operation.'
)


def command(reconcile=False):
    return f'''
import broker as b,json,time
import handoffs,handoff_runtime,native
issue={ISSUE!r};source={SOURCE!r};revision={REVISION!r}
settings=json.loads((b.STATE/'native.json').read_text())
effects=handoff_runtime.Effects(b.handoff_context(),settings)
with b.LOCK,b.db() as con:
 route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
 assert route['enabled'] is False,'maintenance requires paused route'
 row=handoffs.load(con,source);assert row and row['issue_id']==issue
 data=json.loads(row['data'])
 if data.get('diagnostic_revision') not in (revision,revision+':capture-format-v1'):
  assert {reconcile!r} is False,'challenge not yet registered'
  assert row['stage']=={EXPECTED_STAGE!r} and data['recipient_task']=={PRIOR_CTO!r}
  assert con.execute("SELECT COUNT(*) FROM leases WHERE status IN ('creating','running')").fetchone()[0]==0
  assert effects.remaining_calls()>=64
  backup=b.STATE/{BACKUP_NAME!r}
  assert not backup.exists(),'uncertain prior maintenance backup'
  import sqlite3
  with sqlite3.connect(backup) as destination:con.backup(destination)
  data['prior_capture_diagnosis']={{'decision':data['decision'],'proposal':data.get('test_revision_proposal'),'task':data['recipient_task']}}
  data['diagnostic_revision']=revision
  data['diagnostic_challenge']={{'observation':{OBSERVATION!r},'assisted':True}}
  data['validation_failure']['diagnostic_read_files']=sorted(set(data['validation_failure']['diagnostic_read_files'])|{{'tests/test_feedback_filter_client.py'}})
  data['trigger_task']={PRIOR_CTO!r}
  for key in ('wakeup_id','recipient_task','dispatched_at','dispatch_marker','instruction','control_error','control_error_count','test_revision_proposal','required_action'):data.pop(key,None)
  handoffs.save(con,source,issue,'diagnose_cto',route['cto'],data,time.time())
 row=handoffs.load(con,source)
 if row['stage']=='dispatch_intent' and not data.get('wakeup_id') and len(data.get('instruction',''))>3900:
  # Native rejects the size before any POST. Preserve the rejected instruction;
  # compact duplicated phase metadata, keeping the underlying receipt intact.
  data['unsubmitted_oversized_instruction']=data['instruction']
  data['phase_evidence']={{'phase':'implementation','red_exit_code':1,'independent_test_review':'blocked_incomplete_source_lines','instruction':'Historical Red is immutable; a fresh independent review is required.'}}
  data['diagnostic_challenge']['observation']='Verify source: oldest_state is captured after create but reused for original-four and created-id-11 assertions. pre_submit is captured after success but expects blank initial status. Protected filter-client mock lacks sort-control: investigate compatibility when control is absent. Preserve all assertions and baseline tests. Read the full long harness line. Cite source locations; prior numeric contradiction claim is unsupported. Diagnosis only, no approval or recursive revision.'
  for key in ('instruction','dispatch_marker'):data.pop(key,None)
  handoffs.save(con,source,issue,'diagnose_cto',route['cto'],data,time.time())
  row=handoffs.load(con,source)
 if row['stage'] in ('diagnose_cto','dispatch_intent','awaiting_acceptance','accepted'):
  runs=native.issue_task_runs(settings,issue)
  latest=max((r for r in runs if r.get('agent_id')==route['author']),key=lambda r:(r.get('created_at') or '',r['id']))
  assert latest['id']==source,'author identity changed'
  stage=handoffs.reconcile(con,{{**route,'enabled':True}},runs,effects)
 else:stage=row['stage']
 row=handoffs.load(con,source);data=json.loads(row['data'])
 print(json.dumps({{'stage':stage,'issue_id':issue,'recipient_task':data.get('recipient_task'),'wakeup_id':data.get('wakeup_id'),'decision':data.get('decision') if stage=='test_revision_required' else None,'route_paused':True,'assisted':True}}))
'''


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--reconcile']):
        raise SystemExit('only --reconcile is supported')
    result = subprocess.run(['docker', 'exec', '-e', 'PYTHONPATH=/',
        'delivery-kit-port2-execution-broker-1', 'python', '-c',
        command(bool(sys.argv[1:]))], text=True, capture_output=True)
    if result.returncode:
        raise SystemExit(result.stderr.strip())
    print(result.stdout.strip())
