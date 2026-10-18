"""Persistent, separately reviewed maintenance of one frozen test literal.

No original task or release is reset. A maintenance approval is an artifact
handoff only; product admission, full calibration and TDD remain separate gates.
Effects are controller-owned and are never selected by a model command.
"""
import json
import time
import urllib.error
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from generic_harness_calibration import digest,require
import calibration_objection_contract as wire

PHASES=('triage','plan','permit','author','review')
TERMINAL=('blocked','maintenance_approved')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS literal_maintenance_workflows(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def register(con,cfg):
    initialize(con);require(len({cfg['author'],cfg['cto'],cfg['reviewer']})==3)
    source=cfg['source']['author_task'];row=con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone()
    if row:require(json.loads(row[0])==cfg);return json.loads(row[1])
    state=dict(stage='issue_pending',owner=cfg['reviewer'],revision=0,decisions={},history=[],
        source_reset=False,functional_red=False,delivery_approval=False,
        required_action='Create source-bound maintenance proposal, preserving the original technical hold')
    con.execute('INSERT INTO literal_maintenance_workflows VALUES(?,?,?)',(source,json.dumps(cfg,sort_keys=True),json.dumps(state,sort_keys=True)));con.commit();return state


def actor(cfg,phase):return cfg['author'] if phase=='author' else cfg['cto'] if phase=='plan' else cfg['reviewer']


def review_context(cfg,s,phase):
    require(phase in ('triage','permit'))
    evidence=cfg['counterexample'] if phase=='triage' else s['decisions']['plan']['receipt']
    return wire.context(digest(cfg['source']),digest(cfg),digest(evidence))


def instruction(cfg,s,phase):
    path=cfg['test_path'];scope='Only the '+cfg['literal']+' literal in '+path+' may change. '
    scope+='Every byte outside that literal, every method/assertion and every product/baseline file must remain identical. '
    if phase in ('triage','permit'):
        note=wire.capsule(review_context(cfg,s,phase))
        note+=('TECH LEAD TRIAGE OF EXECUTED HARNESS COUNTEREXAMPLE. '
            'The frozen Node harness accepted a deliberately unguarded driver; a real pending out-of-order race '
            'made the same driver render the stale result. This is measured test insensitivity, not a claim that '
            'missing product behavior makes positive references impossible. '
            if phase=='triage' else 'INDEPENDENT TECH LEAD REVIEW OF CTO MAINTENANCE PROPOSAL. '
                'This permits only a separately isolated author draft, not editing the original snapshot or delivering product. '
                'CTO proposal: '+s['decisions']['plan']['receipt']['value']['reason']+' ')
        note+=scope+('No tools. refer_to_cto means refer the measured defect / permit this bounded maintenance draft; '
            'retain_technical_hold requires a concrete restriction. All approval/execution flags remain false. reason<=200 chars. '
            'No source retry, contract weakening, product implementation or CEO technical question. '
            'All acceptance IDs and normal calibration/TDD/review/delivery gates remain. ')
        if phase=='triage':note+='Counterexample digest: '+digest(cfg['counterexample'])
    elif phase=='plan':
        note=('CTO MAINTENANCE SCOPE PROPOSAL, NOT IMPLEMENTATION OR PRODUCT APPROVAL. '
            'Independent Lead referred an executed counterexample: an unguarded driver passed the frozen stale-response '
            'comparison but failed a real pending race. Propose a harness-only test repair, not an app implementation. '+scope+
            'The target is a NEW test, absent from the product baseline. Preserve all accepted criteria and historical tests. '
            'Make stale/current requests genuinely pending before resolving current then stale. Keep polling expectations '
            'aligned with explicitly driven polling cycles. Absence of the new feature should yield measured assertion '
            'failures, not fabricated success or a setup crash. No tools. '
            'Return request_test_revision with a concise concrete scope, or escalate_cto with a concrete restriction; '
            'optional_files=[]. reason<=300 chars. No release approval or resetting prior attempts.\n'
            'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\n'
            'Source binding: '+digest(cfg))
    elif phase=='author':
        note=('ISOLATED HARNESS MAINTENANCE. Repair the controller-seeded NEW test, not the product. '+scope+
            'Read the existing file and readonly product sources completely. Repair measured stale-response sensitivity '
            'using genuinely overlapping pending requests; do not re-resolve an already completed Promise. '
            'Drive enough polling cycles explicitly; do not change the asserted threshold. Missing new behavior should '
            'produce actual observations and functional assertion failures, not a setup exception or fabricated report. '
            'Do not run shell/compiler/tests: the controller freezes and validates the result, including both guarded '
            'and unguarded diagnostic drivers and unchanged baseline hashes. Final file<=32768 UTF-8 bytes. '
            'No changes to Python assertions, methods, other literals, discovery, timers in product, or acceptance. '
            'A textual promise is not a submission. Deliver the real edited test only.\nDELIVERY_DRIVER_CHECKPOINT_V3\n')
        if s['revision']:note+='Independent change request: '+s['history'][-1]['review']['value']['reason']
    else:
        require(phase=='review');manifest=s['inspection']['candidate_manifest_sha256']
        note=('INDEPENDENT HARNESS LITERAL MAINTENANCE REVIEW, NOT PRODUCT OR TDD APPROVAL. '
            'Read both original and revised tests completely. '+scope+
            'Controller inspection preserved every outside byte and non-target file, compiled the Node template, '
            'and measured that the guarded driver passes the stale comparison while the unguarded driver fails. '
            'These witnesses are diagnostic, not full regression or product Green. Reject fabricated observations, '
            'hardcoded reports, weakened timing, skipped behavior or anything outside scope. '
            'Return approve_test_revision/reject_test_revision, reason<=600 chars, optional_files=[], exact manifest.\n'
            'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+manifest+'\nDELIVERY_TYPED_REVIEW_V1:'+manifest+'\n'
            'DELIVERY_DETERMINISTIC_READ_V1\n'+''.join('DELIVERY_REVIEW_READ_PATH:/evidence/'+role+'/'+path+'\n' for role in ('candidate','previous')))
    require(len(note)<=3800);return note


def authenticate(cfg,s,fx):
    """Native authority stays bound to the exact reviewed source after restarts."""
    runs=fx.runs(cfg,s) if s.get('issue_id') else []
    for phase,record in s['decisions'].items():
        expected=record['receipt'];matches=[t for t in runs if t.get('id')==expected['task_id']]
        require(len(matches)==1 and matches[0].get('status')=='completed' and matches[0].get('agent_id')==actor(cfg,phase))
        shadow={**s,'wakeup_id':record['wakeup_id'],'marker':record['marker']}
        require(fx.decision(cfg,shadow,phase,matches[0])==expected)


def advance(con,source,fx,*,now=None):
    now=time.time() if now is None else now
    cfg,s=map(json.loads,con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone())
    if s['stage'] in TERMINAL:return s
    def save(**updates):
        s.update(updates);con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',
            (json.dumps(s,sort_keys=True),source));con.commit();return s
    def hold(category):return save(stage='blocked',category=category,owner=cfg['cto'],
        required_action='CTO diagnose '+category+' using preserved evidence; no source reset or identical retry')
    try:
        fx.verify(cfg);authenticate(cfg,s,fx)
        if s['stage'] in ('issue_pending','issue_observe'):
            first=s['stage']=='issue_pending'
            if first:save(stage='issue_observe',phase_started=now)
            try:issue=fx.issue(cfg,first)
            except (TimeoutError,urllib.error.URLError):issue=None
            if issue is None:return hold('maintenance_issue_unobserved') if now-s['phase_started']>=600 else s
            return save(stage='triage_dispatch',issue_id=issue['id'],identifier=issue.get('identifier'),
                required_action='Lead review measured counterexample, not an identical unsupported-seam question')
        if s['stage']=='prepare':
            prepared=fx.prepare(cfg,s);require(isinstance(prepared,dict) and prepared)
            return save(stage='author_dispatch',prepared=prepared,owner=cfg['author'],
                required_action='Original author prepare isolated literal-only maintenance submission')
        if s['stage']=='snapshot':return save(stage='inspect',snapshot=fx.snapshot(cfg,s,{'id':s['author_task']}))
        if s['stage']=='inspect':
            result=fx.inspect(cfg,s);fx.validate_inspection(cfg,s,result)
            if not result['stale_witness_selectivity_passed']:return save(stage='blocked',category='maintenance_sensitivity_failed',
                inspection=result,owner=cfg['cto'],required_action='Diagnose non-selective revised harness; preserve artifacts, no identical retry')
            return save(stage='review_dispatch',inspection=result,owner=cfg['reviewer'],
                required_action='Independent review exact new artifact; no TDD/product approval')
        if s['stage']=='reseed':
            seeded=fx.reseed(cfg,s);return save(stage='author_dispatch',prepared=seeded,owner=cfg['author'])
        phase=next((p for p in PHASES if s['stage'].startswith(p+'_')),None);require(phase)
        if s['stage'].endswith(('_dispatch','_observe')):
            first=s['stage'].endswith('_dispatch')
            if first and not fx.reserve():return save(required_action='Await maintenance model reserve; no wakeup created')
            if first:save(stage=phase+'_observe',phase_started=now,marker=digest(dict(config=cfg,phase=phase,
                instruction=instruction(cfg,s,phase),revision=s['revision'] if phase in ('author','review') else 0)))
            try:wake=fx.wake(cfg,s,phase,first)
            except (TimeoutError,urllib.error.URLError):wake=None
            if wake is None:return hold('maintenance_'+phase+'_wakeup_unobserved') if now-s['phase_started']>=600 else s
            return save(stage=phase+'_wait',wakeup_id=wake['id'],owner=actor(cfg,phase),
                required_action='Observe exact native '+phase+' task; never repeat an uncertain wakeup')
        require(s['stage']==phase+'_wait')
        matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==s['wakeup_id']];require(len(matches)<=1)
        if not matches or matches[0].get('status') in ('queued','dispatched','running'):
            return hold('native_'+phase+'_deadline') if now-s['phase_started']>=1800 else s
        task=matches[0];require(task.get('agent_id')==actor(cfg,phase) and task.get('issue_id')==s['issue_id'] and task['id']!=source)
        if task.get('status')!='completed':return hold('native_'+phase+'_failed')
        if phase=='author':return save(stage='snapshot',author_task=task['id'],author_wakeup=s['wakeup_id'],
            required_action='Freeze completed maintenance author; original source remains immutable')
        decision=fx.decision(cfg,s,phase,task);require(decision['task_id']==task['id'] and decision['agent_id']==actor(cfg,phase))
        value=decision['value']
        if phase in ('triage','permit'):
            Draft202012Validator(wire.schema(review_context(cfg,s,phase))).validate(value)
            if value['action']=='retain_technical_hold':return save(stage='blocked',category='maintenance_'+phase+'_hold',
                held_decision=decision,owner=cfg['cto'],required_action='CTO address concrete independently retained restriction; no identical retry')
        elif phase=='plan':
            require(set(value)=={'action','reason','optional_files'} and value['optional_files']==[] and isinstance(value['reason'],str)
                and 1<=len(value['reason'])<=1200 and value['action'] in ('request_test_revision','escalate_cto'))
            if value['action']=='escalate_cto':return save(stage='blocked',category='maintenance_scope_hold',held_decision=decision,owner=cfg['cto'])
        else:
            require(set(value)=={'action','reason','optional_files','manifest_sha256'} and value['optional_files']==[]
                and value['manifest_sha256']==s['inspection']['candidate_manifest_sha256'] and isinstance(value['reason'],str)
                and 1<=len(value['reason'])<=1200 and value['action'] in ('approve_test_revision','reject_test_revision'))
            if value['action']=='approve_test_revision':return save(stage='maintenance_approved',review=decision,
                review_wakeup=s['wakeup_id'],review_marker=s['marker'],
                owner=cfg['reviewer'],required_action='Hand off immutable maintenance artifact to normal test-first admission; no product approval')
            history=[*s['history'],dict(snapshot=s['snapshot'],inspection=s['inspection'],author_task=s['author_task'],
                review=decision,wakeup_id=s['wakeup_id'],marker=s['marker'],revision=s['revision'])]
            if s['revision']>=1:return save(stage='blocked',category='maintenance_review_revision_exhausted',history=history,
                owner=cfg['cto'],required_action='Diagnose second independent rejection; no source reset or identical retry')
            return save(stage='reseed',history=history,revision=s['revision']+1,owner=cfg['author'],
                required_action='Return measured change request to original maintenance author, preserving both revisions')
        decisions={**s['decisions'],phase:dict(receipt=decision,wakeup_id=s['wakeup_id'],marker=s['marker'])}
        next_stage={'triage':'plan_dispatch','plan':'permit_dispatch','permit':'prepare'}[phase]
        return save(stage=next_stage,decisions=decisions,owner=cfg['cto'] if phase=='triage' else cfg['reviewer'])
    except (TimeoutError,urllib.error.URLError):
        return hold('maintenance_evidence_deadline') if now-s.get('phase_started',now)>=1800 else s
    except (ValueError,KeyError,TypeError,ValidationError):return hold('maintenance_evidence_rejected')
