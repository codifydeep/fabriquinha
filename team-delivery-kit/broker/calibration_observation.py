"""Controller-only admission of a separately observed legacy calibration failure.

No job is created, native status changed, or historical receipt overwritten.
The existing CTO/independent-peer gate owns any subsequent author sponsorship.
"""
import hashlib
import json
import uuid


def validate_result(value,manifest):
    from service_mode_harness_qualification import CASES
    facts=value.get('facts') or {}
    counts=('tests','failures','errors','skipped','unexpected_successes','expected_failures')
    import re
    if (value.get('status')!='rejected' or value.get('delivery_approval') is not False
            or value.get('phase') not in ('positive_reference','behavioral_controls','background_control','compile')
            or facts.get('manifest_sha256')!=manifest
            or not re.fullmatch('[a-f0-9]{64}',str(facts.get('test_sha256')))):
        raise ValueError('same immutable nonapproving calibration facts required')
    for key in ('positive','background'):
        if key in facts and (not isinstance(facts[key],dict)
                or any(type(facts[key].get(k)) is not int or not 0<=facts[key][k]<=10000 for k in counts)):
            raise ValueError('bounded measured calibration counts required')
    if value['phase']=='behavioral_controls':
        negatives=facts.get('negative_controls')
        if not isinstance(negatives,dict) or set(negatives)!=set(CASES):raise ValueError('all fixed negative controls required')
        if any(not isinstance(v,dict) or any(type(v.get(k)) is not int or not 0<=v[k]<=10000 for k in counts)
                for v in negatives.values()):raise ValueError('bounded negative counts required')
    return facts


def claim(c,source,sha,proof):
    c.execute('CREATE TABLE IF NOT EXISTS calibration_diagnostic_observations('
        'source_task TEXT PRIMARY KEY,receipt_sha256 TEXT,receipt TEXT)')
    old=c.execute('SELECT receipt_sha256,receipt FROM calibration_diagnostic_observations WHERE source_task=?',(source,)).fetchone()
    if old:
        if old[0]!=sha or json.loads(old[1])!=proof:raise ValueError('calibration observation identity drift')
        return proof
    c.execute('INSERT INTO calibration_diagnostic_observations VALUES(?,?,?)',(source,sha,json.dumps(proof,sort_keys=True)))
    return proof


def capture(b,issue,source):
    try:import harness_qualification as jobs,transport_qualification
    except ImportError:from broker import harness_qualification as jobs,transport_qualification
    config_path=b.STATE/'calibration-diagnostic-observation.json'
    if not config_path.exists():return None
    cfg=transport_qualification.private_json(config_path,2048)
    if set(cfg)!={'source_task','container_id','image','output_sha256','original_output_sha256'}:
        raise ValueError('exact controller observation selector required')
    if cfg['source_task']!=source:return None
    if str(uuid.UUID(source))!=source or cfg['image']!=jobs.BACKGROUND_IMAGE:
        raise ValueError('exact frozen source and qualified diagnostic image required')
    with b.db() as c:
        row=c.execute('SELECT identity,state FROM harness_qualifications WHERE task_id=?',(source,)).fetchone()
        prior=c.execute('SELECT stage FROM delivery_handoffs WHERE issue_id=? AND source_task=?',(issue,source)).fetchone()
        if not row or not prior or prior[0]!='test_first_blocked':return None
        identity,held=map(json.loads,row)
        if (identity['issue_id']!=issue or held.get('stage')!='blocked'
                or held.get('output_sha256')!=cfg['original_output_sha256']
                or held.get('diagnostic') or c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):return None
        info=b.docker('GET','/containers/'+cfg['container_id']+'/json')
        config=info.get('Config',{});host=info.get('HostConfig',{});labels=config.get('Labels',{})
        mounts=host.get('Mounts',[])
        if (info.get('Name')!='/'+b.PREFIX+'-calibration-observation-'+source
                or info.get('Image')!=cfg['image'] or config.get('User')!='10000:10000'
                or config.get('Entrypoint')!=['python']
                or config.get('Cmd')!=['/service_mode_background_qualification.py','/delivery',identity['manifest_sha256']]
                or labels.get('com.docker.compose.project')!=b.PREFIX+'-tests'
                or labels.get('com.docker.compose.service')!='calibration-observation'
                or host.get('NetworkMode')!='none' or host.get('ReadonlyRootfs') is not True
                or host.get('CapDrop')!=['ALL'] or host.get('SecurityOpt')!=['no-new-privileges']
                or host.get('Binds') not in (None,[]) or host.get('Privileged') is True
                or host.get('Memory')!=268435456 or host.get('NanoCpus')!=1000000000 or host.get('PidsLimit')!=96
                or len(mounts)!=1 or mounts[0].get('Source')!=identity['volume']
                or mounts[0].get('Target')!='/delivery' or mounts[0].get('ReadOnly') is not True
                or info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']==0):
            raise ValueError('exact isolated terminal calibration observation required')
        from types import SimpleNamespace
        environment=dict(item.split('=',1) for item in jobs.image_environment(
            SimpleNamespace(IMAGE=cfg['image'],docker=b.docker)))
        environment['PYTHONPATH']='/'
        expected_environment=[key+'='+value for key,value in sorted(environment.items())]
        if sorted(config.get('Env',[]))!=expected_environment:
            raise ValueError('exact credential-free observation environment required')
        volume=b.docker('GET','/volumes/'+identity['volume'])
        owned=volume.get('Labels',{}) if volume else {}
        if owned.get('delivery-kit.owner')!=b.OWNER or owned.get('delivery-kit.test-first-task')!=source:
            raise ValueError('exact owned immutable calibration volume required')
        raw=b.docker_stdout(info['Id'],include_stderr=False,limit=65536)
        sha=hashlib.sha256(raw.encode()).hexdigest()
        if sha!=cfg['output_sha256']:raise ValueError('actual observation output drift')
        value=json.loads(raw);validate_result(value,identity['manifest_sha256'])
        retained=jobs.rejection_state(c,issue,dict(info,Config=dict(config,Labels=dict(labels,
            **{'delivery-kit.harness-manifest':identity['manifest_sha256']}))),raw)
        diagnostic=retained.get('diagnostic')
        if not diagnostic:raise ValueError('bounded calibration diagnostic required')
        proof=dict(status='rejected',delivery_approval=False,**diagnostic)
        claim(c,source,sha,proof)
        return dict(kind='observed_calibration_rejection',category='harness_calibration_rejected',
            issue_id=issue,task_id=source,structured_receipt_sha256=sha,
            **diagnostic,tests_executed=True,red_verified=False,delivery_approval=False)
