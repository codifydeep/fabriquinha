"""Mandatory first negative-control execution from exact native Green records.

Re-executes the full frozen suite against the reviewed Red volume. No legacy
receipt becomes new evidence. Missing criterion witnesses are a CTO-owned
additional-controls incident, never success or permission to repeat the control.
"""
import json
import time
try:
    from . import quality_green_capture as green,quality_delivery_capture as delivery
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job
except ImportError:
    import quality_green_capture as green,quality_delivery_capture as delivery
    import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job

quality=green.quality
require=green.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_sensitivity_captures('
        'request_id TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')


def load(b,request):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_sensitivity_captures '
            'WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    context,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(context)==row[2] and quality.digest(state)==row[3]
        and context['namespace']==b.PREFIX and context['request_id']==request
        and state['stage'] in ('awaiting_sensitivity','awaiting_independent_delivery_review','technical_blocked')
        and all(state.get(k) is False for k in ('execution_authorized','merge_authorized','delivery_approval')))
    if state['stage']=='awaiting_independent_delivery_review':
        quality.qualify_sensitivity(context['plan'],{**context['evidence'],'sensitivity':state['observation']['sensitivity']})
    return context,state


def provenance(b,request):
    context,state=green.load(b,request);require(state['stage']=='awaiting_sensitivity')
    require(green.provenance(b,request)=={k:v for k,v in context.items() if k!='payload'})
    source,_=delivery.load(b,request);reviewed=delivery.admission.snapshot_identity(b,
        source['admission']['source_task'],context['freeze']['manifest_sha256'])
    require(reviewed==source['reviewed_snapshot'])
    _,binding=green.binding.load(b,request)
    return dict(namespace=b.PREFIX,request_id=request,task_id=context['task_id'],plan=context['plan'],
        green_sha256=quality.digest(state),binding_sha256=context['binding_sha256'],base=context['base'],
        candidate_volume=context['volume'],candidate_identity=context['volume_identity'],reviewed=reviewed,
        manifest_sha256=context['manifest_sha256'],commit_sha=context['commit_sha'],
        owner=context['owner'],cto=context['cto'],changed_product_paths=sorted(
            set(binding['candidate']['git_proof']['changed_paths'])&set(context['plan']['product_files'])),
        evidence=dict(red=context['freeze']['red'],test_review=context['freeze']['test_review'],green=state['observation']['green']))


def payload(b,context):
    image=delivery.image_id(b);info=b.docker('GET','/images/'+image+'/json')
    require('observe_reversion_v2' in info['Config'].get('Labels',{}).get('delivery-kit.quality-operations','').split(','))
    request=dict(operation='observe_reversion_v2',plan=context['plan'],task_id=context['task_id'],
        base_manifest_sha256=context['base']['manifest_sha256'],candidate_manifest_sha256=context['manifest_sha256'],
        reviewed_manifest_sha256=context['evidence']['red']['manifest_sha256'],evidence=context['evidence'])
    encoded=json.dumps(request,sort_keys=True,separators=(',',':'));require(len(encoded.encode())<=65536)
    template=green.payload(b,{**context,'freeze':dict(red=context['evidence']['red'],test_review=context['evidence']['test_review']),
        'volume':context['candidate_volume']})
    template.update(Env=['PYTHONDONTWRITEBYTECODE=1','QUALITY_GREEN_JOB_JSON='+encoded],
        Labels={'delivery-kit.quality-run':context['plan']['run_id'],'delivery-kit.quality-stage':'sensitivity-v2'})
    template['HostConfig']['Mounts']=[dict(Type='volume',Source=volume,Target=path,ReadOnly=True)
        for volume,path in ((context['base']['volume'],'/base'),(context['candidate_volume'],'/candidate'),
            (context['reviewed']['volume'],'/snapshot'))]
    return template


def observed(b,context,result):
    receipt=green.fixed_receipt(b,context['task_id'],'sensitivity',context['payload'],result)
    report=json.loads(result['output']);plan=context['plan'];passing=context['evidence']['green']
    require(set(report)=={'operation','sensitivity','coverage_complete','missing_criteria','reviewed_manifest_sha256',
        'captured_output_sha256','snapshot_unchanged','tests_unchanged','execution_authorized','merge_authorized','delivery_approval'}
        and report['operation']=='post_green_reversion_observation_v2'
        and report['reviewed_manifest_sha256']==context['evidence']['red']['manifest_sha256']
        and report['snapshot_unchanged'] is True and report['tests_unchanged'] is True
        and all(report[k] is False for k in ('execution_authorized','merge_authorized','delivery_approval')))
    quality.sha(report['captured_output_sha256']);facts=report['sensitivity']
    quality.envelope(plan,facts,'observed_sensitivity_v2',{'green_sha256','manifest_sha256','commit_sha','positive_sha256','controls'})
    require(facts['green_sha256']==facts['positive_sha256']==quality.digest(passing)
        and facts['manifest_sha256']==context['manifest_sha256'] and facts['commit_sha']==context['commit_sha']
        and isinstance(facts['controls'],list) and len(facts['controls'])==1)
    control=facts['controls'][0]
    require(set(control)==quality.SUITE|{'id','criteria','changed_files'}
        and control['id']=='revert_product_to_reviewed_red' and control['changed_files']==context['changed_product_paths'])
    quality.suite(plan,control,passing=False,minimum=passing['tests_run'],frozen=passing['tests'])
    witnesses={(f['path'],f['method']) for f in control['failures']}
    covered=sorted(c for c,tests in plan['criterion_tests'].items() if any((t['path'],t['method']) in witnesses for t in tests))
    missing=sorted(set(plan['criteria'])-set(covered))
    require(bool(covered) and control['criteria']==covered and report['missing_criteria']==missing
        and report['coverage_complete'] is (not missing))
    if not missing:quality.qualify_sensitivity(plan,{**context['evidence'],'sensitivity':facts})
    return dict(**receipt,sensitivity=facts,missing_criteria=missing,coverage_complete=not missing)


def save(b,request,context,before,after):
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves original sensitivity job')
        changed=con.execute('UPDATE quality_sensitivity_captures SET state=?,state_sha256=? '
            'WHERE request_id=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),request,quality.digest(context),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def observe(b,request):
    delivery.admission.enrollment.canonical(request)
    with delivery.red.observation_lock(b,request):
        old=load(b,request)
        if old and old[1]['stage'] in ('awaiting_independent_delivery_review','technical_blocked'):return old[1]
        delivery.admission.enabled(b)
        with b.db() as con:
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves original negative-control observation')
        if old:context,state=old
        else:
            context=provenance(b,request);context['payload']=payload(b,context)
            now=time.time();state=dict(stage='awaiting_sensitivity',owner=context['owner'],deadline=now+1800,
                observations=0,alert_due=False,execution_authorized=False,merge_authorized=False,delivery_approval=False)
            with b.LOCK,b.db() as con:
                maintenance.transaction(con)
                if maintenance.current(con):raise validation_job.Pending('maintenance pauses new negative control')
                initialize(con);con.execute('INSERT INTO quality_sensitivity_captures VALUES(?,?,?,?,?)',
                    (request,json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(context),quality.digest(state)))
        phase='sensitivity_source_provenance';deadline=state['deadline'];category='Pending'
        try:
            fresh=provenance(b,request);require(fresh=={k:v for k,v in context.items() if k!='payload'})
            with b.db() as con:
                if maintenance.current(con):raise validation_job.Pending('maintenance preserves original negative control')
                deadline=clock.deadline(con,b.PREFIX,state['deadline'],time.time(),budget=1800)
            state=save(b,request,context,state,{**state,'observations':state['observations']+1,'alert_due':time.time()>=deadline-1200})
            phase='sensitivity_fixed_job_receipt'
            result=validation_job.run(b,context['task_id'],'sensitivity',context['payload'])
            facts=observed(b,context,result);require(provenance(b,request)==fresh)
            if facts['coverage_complete']:
                return save(b,request,context,state,{**state,'stage':'awaiting_independent_delivery_review','observation':facts,
                    'next_action':'independent review of the same candidate; PR/CI/deploy/QA gates remain required'})
            return save(b,request,context,state,{**state,'stage':'technical_blocked','owner':context['cto'],'observation':facts,
                'incident':dict(category='additional_mutation_controls_required',automatic_retry=False,
                    missing_criteria=facts['missing_criteria'],next_action='CTO assign QA additional frozen-product controls; never waive coverage or repeat this control')})
        except validation_job.Pending as pending:
            if time.time()<deadline:pending.progress=state;raise
            phase='sensitivity_observation_deadline'
        except (TimeoutError,OSError) as error:
            if time.time()<deadline:
                pending=validation_job.Pending('observe original negative-control handle; no replay');pending.progress=state
                raise pending from error
            phase='sensitivity_source_observation_deadline';category=type(error).__name__
        except (ValueError,KeyError,TypeError) as error:category=type(error).__name__
        return save(b,request,context,state,{**state,'stage':'technical_blocked','incident':dict(category=phase,
            error_type=category,automatic_retry=False,next_action='Tech Lead diagnose preserved control; escalate technical decisions to CTO')})
