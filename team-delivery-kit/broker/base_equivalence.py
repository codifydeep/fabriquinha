"""Prove full original-base equality across different owned phase copies."""
import hashlib
import json
import time
from types import SimpleNamespace
try:import harness_qualification as jobs
except ImportError:from broker import harness_qualification as jobs

IMAGE='sha256:3cd0a9b7b96878f81e80463147d78ee69c7c94236bf01c4de43e38a18b083bd1'


def resume_format(b,source):
    """Maintenance only: preserve the failed snapshot-format probe and approval."""
    with b.LOCK,b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS original_base_format_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
        saved=con.execute('SELECT receipt FROM original_base_format_recoveries WHERE source_task=?',(source,)).fetchone()
        if saved:return json.loads(saved[0])
        row=con.execute('SELECT identity,state FROM original_base_equivalences WHERE source_task=?',(source,)).fetchone()
        identity,old=map(json.loads,row)
        scope=con.execute('SELECT state FROM request_scope_experiments WHERE source_task=?',(source,)).fetchone()
        held=json.loads(scope[0]);cfg,state=map(json.loads,con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone())
        if old['stage']!='blocked' or held['stage']!='blocked' or state['stage']!='plan_approved':
            raise ValueError('exact blocked probe with preserved independent plan approval required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
            raise ValueError('idle recovery required')
    current=b.issue_base(cfg['source_issue']);validate_bindings(cfg,current)
    if identity['approved']!=cfg['base'] or identity['current']!=current:
        raise ValueError('unchanged original base bindings required')
    info=b.docker('GET','/containers/'+old['container_id']+'/json');jobs.verify_job(info,identity['payload'])
    if (identity['payload']['Image']!='sha256:e5c5b7cbf4c99852e762bf5f36496c59dc8c147b7aeb55e1f05ccbcea03b3513'
            or info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']!=1):
        raise ValueError('exact stopped old probe required')
    raw=b.docker_stdout(info['Id'],include_stderr=True,limit=16384)
    if 'ValueError: bounded frozen file inventory required' not in raw:
        raise ValueError('observed snapshot-versus-base schema rejection required')
    receipt=dict(operation='original_base_probe_format_recovery_v1',previous_identity=identity,
        previous_state=old,previous_scope_state=held,output_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        corrected_image=IMAGE,approved_plan_unchanged=True,execution_authorized=False)
    with b.db() as con:
        if json.loads(con.execute('SELECT state FROM request_scope_experiments WHERE source_task=?',(source,)).fetchone()[0])!=held:
            raise ValueError('recovery hold drift')
        con.execute('INSERT INTO original_base_format_recoveries VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE request_scope_experiments SET state=? WHERE source_task=?',
            (json.dumps({**held,'stage':'plan_registered','base_probe_format_recovery':receipt},sort_keys=True),source))
        row=con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(source,)).fetchone()
        data=json.loads(row[0]);data.update(base_probe_format_recovery=receipt,
            request_scope_experiment_state=dict(stage='plan_registered'),
            required_action='verify original-base copies then provision independently approved plan')
        con.execute('UPDATE delivery_handoffs SET data=? WHERE source_task=?',(json.dumps(data,sort_keys=True),source))
    return receipt


def validate_bindings(config,current):
    approved=config['base']
    if (config.get('amendment',{}).get('kind') not in ('request_scope','timer_provenance','inherited_frozen_suite')
            or config.get('diagnostic_snapshot_kind')!='completed_frozen_validation'
            or set(approved)!=set(current) or approved==current
            or any(approved[k]!=current[k] for k in approved if k not in ('issue_id','volume'))
            or current['issue_id']!=config['source_issue'] or approved['issue_id']==current['issue_id']
            or approved['volume']==current['volume']):
        raise ValueError('only exact cross-phase original-base copy bindings allowed')


def validate_result(result,manifest):
    if (result.get('operation')!='immutable_original_base_equivalence_v1'
            or result.get('manifest_sha256')!=manifest or result.get('files_identical') is not True
            or type(result.get('file_count')) is not int or not 1<=result['file_count']<=2048
            or type(result.get('total_bytes')) is not int or not 0<=result['total_bytes']<=134217728
            or any(result.get(k) is not False for k in ('source_modified','execution_authorized','delivery_approval'))):
        raise ValueError('actual complete immutable inventory equivalence required')


def qualify(b,config,current):
    validate_bindings(config,current);source=config['source_task'];approved=config['base']
    for value in (approved,current):
        labels=(b.docker('GET','/volumes/'+value['volume']) or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or not value['volume'].startswith(b.PREFIX+'-base-'):
            raise ValueError('both exact controller-owned base copies required')
    image=SimpleNamespace(IMAGE=IMAGE,docker=b.docker)
    expected=dict(Image=IMAGE,User='10000:10000',Entrypoint=['python'],
        Cmd=['/base_equivalence_probe.py','/approved','/current',approved['manifest_sha256']],
        Env=jobs.image_environment(image),NetworkDisabled=True,
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':source},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=32,
            Mounts=[dict(Type='volume',Source=v['volume'],Target=t,ReadOnly=True)
                for v,t in ((approved,'/approved'),(current,'/current'))]))
    identity=dict(approved=approved,current=current,payload=expected);name=b.PREFIX+'-base-equivalence-v2-'+source
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS original_base_equivalences_v2(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        legacy=con.execute("SELECT 1 FROM sqlite_master WHERE name='original_base_equivalences'").fetchone()
        if legacy and con.execute('SELECT 1 FROM original_base_equivalences WHERE source_task=?',(source,)).fetchone():
            recovery=con.execute('SELECT receipt FROM original_base_format_recoveries WHERE source_task=?',(source,)).fetchone()
            if not recovery or json.loads(recovery[0])['corrected_image']!=IMAGE:raise ValueError('explicit changed-format recovery required')
        row=con.execute('SELECT identity,state FROM original_base_equivalences_v2 WHERE source_task=?',(source,)).fetchone()
        if row:
            if json.loads(row[0])!=identity:raise ValueError('immutable base equivalence identity drift')
            state=json.loads(row[1]);create=False
        else:
            state=dict(stage='create_intent',at=time.time());create=True
            con.execute('INSERT INTO original_base_equivalences_v2 VALUES(?,?,?)',(source,json.dumps(identity,sort_keys=True),json.dumps(state)))
    def save(new):
        with b.db() as con:con.execute('UPDATE original_base_equivalences_v2 SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new
    if state['stage']=='blocked':raise ValueError('base equivalence blocked; no identical retry')
    info=b.docker('GET','/containers/'+name+'/json')
    if state['stage']=='create_intent':
        if not info and create:
            b.docker('POST','/containers/create?name='+name,expected);info=b.docker('GET','/containers/'+name+'/json')
        if not info:
            if time.time()-state['at']>=600:
                save({**state,'stage':'blocked'});raise ValueError('uncertain equivalence creation deadline')
            raise TimeoutError('observe uncertain equivalence creation; no repeated POST')
        jobs.verify_job(info,expected)
        if info['State']['Status']!='created':raise ValueError('unexpected equivalence job before start intent')
        state=save(dict(stage='start_intent',container_id=info['Id'],at=time.time()))
        b.docker('POST','/containers/'+info['Id']+'/start')
    deadline=time.time()+20
    while time.time()<deadline:
        info=b.docker('GET','/containers/'+state['container_id']+'/json');jobs.verify_job(info,expected)
        if info['State']['Status']=='exited':
            if info['State']['ExitCode']!=0:
                save({**state,'stage':'blocked'});raise ValueError('complete base inventories differ')
            raw=b.docker_stdout(info['Id'],include_stderr=False,limit=16384);result=json.loads(raw)
            validate_result(result,approved['manifest_sha256'])
            if state['stage']=='passed':
                if state['result']!=result or state['output_sha256']!=hashlib.sha256(raw.encode()).hexdigest():
                    raise ValueError('preserved equivalence evidence drift')
            else:save({**state,'stage':'passed','result':result,'output_sha256':hashlib.sha256(raw.encode()).hexdigest()})
            return dict(operation='original_base_binding_equivalence_v1',approved=approved,current=current,
                container_id=info['Id'],result=result,config_unchanged=True,execution_authorized=False)
        if not info['State']['Running']:
            if time.time()-state['at']>=600:
                save({**state,'stage':'blocked'});raise ValueError('uncertain equivalence start deadline')
            raise TimeoutError('observe uncertain equivalence start; no repeated POST')
        time.sleep(.2)
    if time.time()-state['at']>=600:
        save({**state,'stage':'blocked'});raise ValueError('equivalence execution deadline; exact job retained')
    raise TimeoutError('original-base equivalence still running; preserve exact job')
