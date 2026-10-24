"""Evidence-bound product correction handoff. Source-only, not routed/installed.

Preserves the rejected candidate, original test freeze and original implementer.
Dispatch alone cannot admit/launch a worker, edit tests or confer approval.
"""
import json
import time
from execution_context import freeze,validate as validate_capsule
try:
    from . import quality_delivery_review_attestation as attestation
    from . import quality_implementation_admission as implementation
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job
except ImportError:
    import quality_delivery_review_attestation as attestation
    import quality_implementation_admission as implementation
    import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job

review=attestation.review
quality=review.quality
require=review.require
STAGES=('prepared','dispatch_intent','awaiting_product_revision_admission','technical_blocked')


def enabled(b):
    review.enabled(b)
    require(getattr(b,'QUALITY_DELIVERY_REVISION_ENABLED',False) is True)


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_delivery_revisions('
        'review_request TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')


def load(b,request):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_delivery_revisions '
            'WHERE review_request=?',(request,)).fetchone()
    if not row:return None
    context,state=json.loads(row[0]),json.loads(row[1]);validate_capsule(context['capsule'])
    require(quality.digest(context)==row[2] and quality.digest(state)==row[3]
        and context['review_request']==request and context['namespace']==b.PREFIX and state['stage'] in STAGES
        and all(state[k] is False for k in ('execution_authorized','merge_authorized','delivery_approval')))
    return context,state


def provenance(b,request):
    receipt=attestation.load(b,request)
    require(receipt is not None and receipt['stage']=='changes_requested' and receipt['verdict']['action']=='request_changes'
        and not receipt['execution_authorized'] and not receipt['merge_authorized'] and not receipt['delivery_approval'])
    c,assignment,validated=attestation.launch.context_for(b,request);review.fresh(b,assignment)
    require(receipt['owner']==assignment['author'] and receipt['task_id']==c['task_id']
        and receipt['implementation_request']==c['implementation_request']
        and receipt['manifest_sha256']==c['manifest_sha256'] and receipt['commit_sha']==c['commit_sha'])
    frozen,enrolled=implementation.frozen(b,c['source_task'])
    require(frozen['plan']==assignment['plan'] and frozen['red']==assignment['evidence']['red']
        and frozen['test_review']==assignment['evidence']['test_review'] and enrolled['author']==assignment['author'])
    return dict(namespace=b.PREFIX,review_request=request,implementation_request=c['implementation_request'],
        source_task=c['source_task'],issue_id=c['issue_id'],run_id=c['run_id'],author=assignment['author'],
        reviewer=assignment['reviewer'],cto=assignment['cto'],origin_task=c['task_id'],
        plan=assignment['plan'],requirements=assignment['requirements'],seed=assignment['snapshot'],
        seed_manifest_sha256=c['manifest_sha256'],rejected_commit_sha=c['commit_sha'],
        file_inventory=assignment['file_inventory'],frozen_tests=frozen['frozen_tests'],frozen_sha256=quality.digest(frozen),
        enrollment_sha256=quality.digest(enrolled),review_receipt_sha256=quality.digest(receipt),
        validation_state_sha256=quality.digest(validated),findings=receipt['verdict']['findings'],
        findings_sha256=quality.digest(receipt['verdict']['findings']),description=assignment['capsule']['description'])


def fresh(b,context):
    actual=provenance(b,context['review_request']);actual.pop('description')
    require(actual=={k:v for k,v in context.items() if k not in ('capsule','instruction','marker','editable_paths','read_paths')})


def register(b,request):
    enabled(b);review.enrollment.canonical(request)
    with review.delivery.red.observation_lock(b,request):
        old=load(b,request)
        if old:return old
        context=provenance(b,request);description=context.pop('description')
        # A reviewer may identify a defect in a frozen test, but a product
        # correction must never silently turn that finding into test authority.
        products=set(context['plan']['product_files'])
        editable=['/workspace/'+p for p in sorted(products)]
        instruction=('PRODUCT CORRECTION V2. Address only the independently observed delivery findings. '
            'Start from the rejected immutable candidate, preserving every frozen test byte. '
            'Write only declared product files. No tests/configuration changes, shell, patch, delegation or administration. '
            'Do not recreate Red, claim Green or reuse a previous approval. The controller must capture a NEW candidate, '
            'run the full frozen suite and negative controls, and obtain a NEW independent delivery review. '
            'A finding requiring frozen-test/contract changes belongs to CTO diagnosis, not a permission to edit tests. '
            'Rejected snapshot: '+context['seed_manifest_sha256']+'\nFindings: '+json.dumps(context['findings'],sort_keys=True))
        context.update(editable_paths=editable,read_paths=['/workspace/'+p for p in sorted(context['file_inventory'])],
            instruction=instruction,capsule=freeze(description,instruction))
        context['marker']=quality.digest(context)
        state=dict(stage='prepared',owner=context['author'],execution_authorized=False,merge_authorized=False,delivery_approval=False)
        if any(f['path'] not in products for f in context['findings']):
            state.update(stage='technical_blocked',owner=context['cto'],incident=dict(category='frozen_contract_finding',
                automatic_retry=False,next_action='CTO diagnose test/contract finding; no silent exception or test weakening'))
        with b.LOCK,b.db() as con:
            maintenance.transaction(con)
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves product revision registration')
            initialize(con)
            receipt=con.execute('SELECT receipt,receipt_sha256 FROM quality_delivery_review_attestations WHERE request_id=?',(request,)).fetchone()
            require(receipt is not None and quality.digest(json.loads(receipt[0]))==receipt[1]==context['review_receipt_sha256']
                and quality.digest(review.enrollment.lookup(con,context['issue_id']))==context['enrollment_sha256'])
            con.execute('INSERT INTO quality_delivery_revisions VALUES(?,?,?,?,?)',
                (request,json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(context),quality.digest(state)))
        return context,state


def save(b,request,context,before,after):
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves product revision intent')
        if before['stage']=='prepared' and after['stage']=='dispatch_intent':
            if not review.available(con,context['author'],time.time(),own=request):
                raise validation_job.Pending('product revision waits for reserved capacity; no wakeup issued')
        changed=con.execute('UPDATE quality_delivery_revisions SET state=?,state_sha256=? '
            'WHERE review_request=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),request,quality.digest(context),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def hold(b,request,context,state,category):
    return save(b,request,context,state,{**state,'stage':'technical_blocked','owner':context['cto'],
        'incident':dict(category=category,automatic_retry=False,
            next_action='CTO diagnose original correction handoff; never repeat unknown wakeup or waive frozen tests')})


def dispatch(b,request):
    enabled(b);context,_=register(b,request)
    with review.delivery.red.observation_lock(b,request):
        context,state=load(b,request)
        if state['stage'] in ('awaiting_product_revision_admission','technical_blocked'):return state
        fresh(b,context)
        with b.db() as con:
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves product correction')
            enrolled=review.enrollment.lookup(con,context['issue_id'])
            require(enrolled is not None and quality.digest(enrolled)==context['enrollment_sha256'])
            now=time.time();available=review.available(con,context['author'],now,own=request)
            deadline=clock.deadline(con,b.PREFIX,state.get('capacity_since',now)+1800,now,budget=1800)
        settings=json.loads((b.STATE/'native.json').read_bytes())
        require(settings['workspace_id']==enrolled['workspace_id'] and settings['runtime_id']==enrolled['runtime_id']
            and settings['agents'].get(context['author'])=='implementation')
        allow=state['stage']=='prepared'
        if allow and not available:
            if now>=deadline:return hold(b,request,context,state,'product_revision_capacity_starvation')
            state=save(b,request,context,state,{**state,'capacity_since':state.get('capacity_since',now),'alert_due':now>=deadline-1200})
            pending=validation_job.Pending('product correction queued for capacity; no wakeup issued');pending.progress=state;raise pending
        if allow:state=save(b,request,context,state,{**state,'stage':'dispatch_intent','deadline':now+600})
        require(state['stage']=='dispatch_intent')
        with b.db() as con:deadline=clock.deadline(con,b.PREFIX,state['deadline'],time.time())
        try:
            row=review.native.ensure_scope_author_start(settings,context['issue_id'],context['author'],context['origin_task'],
                context['marker'],context['instruction'],allow_create=allow)
            if row is not None:
                review.enrollment.canonical(row['id'])
                require(row.get('agent_id')==context['author'] and row.get('issue_id')==context['issue_id'])
        except (TimeoutError,OSError):row=None
        except (ValueError,KeyError,TypeError):return hold(b,request,context,state,'product_revision_wakeup_rejected')
        if row is None:
            if time.time()>=deadline:return hold(b,request,context,state,'product_revision_wakeup_unobserved')
            pending=validation_job.Pending('observe original product correction wakeup; never repeat POST');pending.progress=state;raise pending
        return save(b,request,context,state,{**state,'stage':'awaiting_product_revision_admission','wakeup_id':row['id']})
