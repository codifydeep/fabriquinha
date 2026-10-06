"""Controller-only fixed missing-product-delta experiment; no worker endpoint."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
try:
    import portable_snapshot_validate as validator, native, handoffs
except ImportError:
    from broker import portable_snapshot_validate as validator, native, handoffs


def inspect(base,candidate,previous):
    base,candidate,previous=map(Path,(base,candidate,previous))
    old_base,old_delivery=validator.BASE,validator.DELIVERY
    validator.BASE,validator.DELIVERY=Path(base),Path(candidate)
    try:
        try:validator.verify()
        except ValueError as error:
            if not re.fullmatch(r'new product code required; new test files present=[1-9][0-9]*',str(error)):raise
        else:raise ValueError('missing product delta not reproduced')
        raw=validator.regular_within(candidate,'manifest.json')
        prior_raw=validator.regular_within(previous,'manifest.json')
        if raw!=prior_raw:raise ValueError('candidate is not exact frozen Red')
        manifest=json.loads(raw)['files']
        actual={str(p.relative_to(previous)) for p in Path(previous).rglob('*') if p.is_file() or p.is_symlink()}
        if actual!=set(manifest)|{'manifest.json'}:raise ValueError('unexpected prior entry')
        for name,item in manifest.items():
            content=validator.regular_within(previous,name)
            if item!={'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}:
                raise ValueError('previous immutable hash mismatch')
        spec=json.loads(validator.regular_within(base,'contract.json'))
        base_files=json.loads(validator.regular_within(base,'manifest.json'))['files']
        new=sorted(set(manifest)-set(base_files))
        if not new or not set(new)<=set(spec['test_files']):raise ValueError('NEW test only required')
        return dict(operation='structural_missing_delta_v1',category='missing_product_delta',
            candidate_manifest_sha256=hashlib.sha256(raw).hexdigest(),
            base_manifest_sha256=hashlib.sha256(validator.regular_within(base,'manifest.json')).hexdigest(),
            previous_manifest_sha256=hashlib.sha256(prior_raw).hexdigest(),
            changed_product_files=[],new_test_files=new,
            product_read_files=sorted(set(spec['editable_files'])-set(spec['test_files'])),
            baseline_files_verified=len(base_files),suite_executed=False,delivery_approval=False)
    finally:validator.BASE,validator.DELIVERY=old_base,old_delivery


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS structural_diagnoses(source_task TEXT PRIMARY KEY,receipt TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS structural_diagnostic_attempts(source_task TEXT PRIMARY KEY,state TEXT)')


def reconcile(b,row):
    """Auto-run one eligible changed-evidence experiment; persist failures, not loops."""
    data=json.loads(row['data'])
    if (row['stage']!='technical_decision_required' or 'structural_diagnosis' in data
            or data.get('failure_category')!='missing_delivery_artifacts'
            or (data.get('decision') or {}).get('action')!='escalate_cto'
            or not data.get('target')):return False
    source=row['source_task']
    with b.db() as c:
        initialize(c)
        prior=c.execute('SELECT state FROM structural_diagnostic_attempts WHERE source_task=?',(source,)).fetchone()
        state=json.loads(prior[0]) if prior else dict(stage='intent',starts=0,delivery_approval=False)
        if state['stage'] in ('complete','blocked'):return True
        if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return True
        if state['starts']>=2:
            state.update(stage='blocked',failure_category='InterruptedExperiment',required_action='reconcile_structural_experiment_intent_without_identical_retry')
        else:state['starts']+=1
        c.execute('INSERT OR REPLACE INTO structural_diagnostic_attempts VALUES(?,?)',(source,json.dumps(state,sort_keys=True)))
        c.commit()  # durable intent before Docker/native side effects
    if state['stage']=='blocked':return True
    try:
        report=register(b,source)
        state.update(stage='complete',manifest_sha256=report['candidate_manifest_sha256'])
    except Exception as error:
        state.update(stage='blocked',failure_category=type(error).__name__,
            required_action='diagnose_fixed_structural_experiment_without_identical_retry')
    with b.db() as c:
        c.execute('UPDATE structural_diagnostic_attempts SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        if state['stage']=='blocked':
            handoffs.initialize(c);current=handoffs.load(c,source)
            if current and current['stage']=='technical_decision_required':
                visible=json.loads(current['data']);visible['structural_auto_failure']=state
                visible['required_action']=state['required_action']
                handoffs.save(c,source,current['issue_id'],current['stage'],current['owner'],visible,time.time())
    return True


def mounts(b,data,binding):
    report=data.get('structural_diagnosis')
    if not report or data.get('target')!=binding['agent_id']:return []
    with b.db() as c:
        initialize(c)
        saved=c.execute('SELECT receipt FROM structural_diagnoses WHERE source_task=?',(data['source_task'],)).fetchone()
        snap=c.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'",(data['source_task'],)).fetchone()
    if (not saved or json.loads(saved[0])!=report or not snap or snap[0]!=report['candidate_volume']
            or report['issue_id']!=binding['issue_id'] or report['delivery_approval'] is not False):
        raise ValueError('structural diagnosis receipt identity mismatch')
    base=b.issue_base(binding['issue_id'])
    if base['volume']!=report['base_volume'] or base['manifest_sha256']!=report['base_manifest_sha256']:
        raise ValueError('structural diagnosis base drift')
    result=[]
    for target,volume,label,value in (
        ('/evidence/candidate',report['candidate_volume'],'delivery-kit.source-task',data['source_task']),
        ('/evidence/previous',report['base_volume'],'delivery-kit.issue-id',binding['issue_id'])):
        info=b.docker('GET','/volumes/'+volume);labels=info.get('Labels',{}) if info else {}
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get(label)!=value:
            raise ValueError('structural diagnosis volume identity mismatch')
        result.append(dict(Type='volume',Source=volume,Target=target,ReadOnly=True))
    return result


def register(b,source_task):
    """One changed-evidence CTO diagnosis, not an execution retry or approval."""
    settings=json.loads((b.STATE/'native.json').read_text())
    with b.LOCK:
        with b.db() as c:
            initialize(c)
            old=c.execute('SELECT receipt FROM structural_diagnoses WHERE source_task=?',(source_task,)).fetchone()
            if old:return json.loads(old[0])
            row=handoffs.load(c,source_task);data=json.loads(row['data']) if row else {}
            if (not row or row['stage']!='technical_decision_required'
                    or data.get('failure_category')!='missing_delivery_artifacts'
                    or (data.get('decision') or {}).get('action')!='escalate_cto'):
                raise ValueError('exact escalated missing artifact handoff required')
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            if data.get('target')!=route['cto']:raise ValueError('CTO diagnosis required')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle structural experiment required')
            binding=c.execute('SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? ORDER BY n.rowid DESC LIMIT 1',(source_task,)).fetchone()
            if not binding or binding[0]!='closed':raise ValueError('closed author execution required')
            snapshot=c.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'",(source_task,)).fetchone()
            red=json.loads(c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
        author=native.task_record(settings,source_task,route['author'])
        cto=native.task_record(settings,data['recipient_task'],route['cto'])
        if (author['status']!='completed' or author['issue_id']!=row['issue_id']
                or cto['status']!='completed' or cto['issue_id']!=row['issue_id']
                or cto.get('wakeup_id')!=data['wakeup_id']):raise ValueError('actual author and CTO required')
        if any(r['status'] in ('running','queued') for r in native.issue_task_runs(settings,row['issue_id'])):
            raise ValueError('native idle structural experiment required')
        base=b.issue_base(row['issue_id']);name=b.PREFIX+'-structural-'+uuid.uuid4().hex[:12]
        image=b.docker('GET','/containers/'+os.environ['HOSTNAME']+'/json')['Image']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('immutable fixed helper required')
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':source_task,'com.docker.compose.project':b.PREFIX}
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=image,User='10000:10000',WorkingDir='/',
                Entrypoint=['python'],Cmd=['-c','import json;from structural_diagnosis import inspect;print(json.dumps(inspect("/base","/candidate","/previous"),sort_keys=True))'],
                Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'],NetworkDisabled=True,Labels=labels,
                HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=134217728,PidsLimit=32,
                    Mounts=[dict(Type='volume',Source=v,Target=t,ReadOnly=True) for t,v in (
                        ('/base',base['volume']),('/candidate',snapshot[0]),('/previous',red['volume']))])))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+20
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']!=0:raise ValueError('fixed structural experiment rejected')
                    report=json.loads(b.docker_stdout(name));break
                time.sleep(.1)
            else:raise TimeoutError('fixed structural experiment deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and info['Config'].get('Labels')==labels:b.docker('DELETE','/containers/'+info['Id']+'?force=true')
        if (report['base_manifest_sha256']!=base['manifest_sha256']
                or report['candidate_manifest_sha256']!=red['red']['manifest_sha256']):raise ValueError('structural manifest drift')
        report.update(source_task=source_task,issue_id=row['issue_id'],candidate_volume=snapshot[0],base_volume=base['volume'],helper_image=image)
        with b.db() as c:
            current=handoffs.load(c,source_task)
            if current['data']!=row['data'] or current['stage']!=row['stage']:raise ValueError('structural handoff drift')
            c.execute('INSERT INTO structural_diagnoses VALUES(?,?)',(source_task,json.dumps(report,sort_keys=True)))
            data['previous_structural_diagnosis']={k:data.get(k) for k in ('decision','recipient_task','wakeup_id','instruction')}
            data.update(structural_diagnosis=report,trigger_task=cto['id'],diagnostic_revision=report['candidate_manifest_sha256']+':structural-read-v1')
            for key in ('decision','recipient_task','wakeup_id','instruction','dispatch_marker','dispatched_at','target'):data.pop(key,None)
            handoffs.save(c,source_task,row['issue_id'],'diagnose_cto',route['cto'],data,time.time())
        return report
