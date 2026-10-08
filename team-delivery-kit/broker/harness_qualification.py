"""Controller-only, durable offline calibration before admitting amended Red."""
import hashlib
import json
import time
import re
from types import SimpleNamespace
BACKGROUND_IMAGE='sha256:58f78524c522e3a30ce80a2a8f943c2429d740fb931adfc9385e219f1a8b70a5'
LEGACY_BACKGROUND_IMAGE='sha256:e5c5b7cbf4c99852e762bf5f36496c59dc8c147b7aeb55e1f05ccbcea03b3513'
TIMER_BACKGROUND_IMAGE='sha256:c1eba170920d10bf56a6279035a11c781416b711aed8875af5f47e99fb08be62'

IMAGE_ENV_KEYS={'PATH','PYTHONUNBUFFERED','PYTHONDONTWRITEBYTECODE','PLAYWRIGHT_BROWSERS_PATH',
    'npm_config_install_links','HERMES_WEB_DIST','HERMES_TUI_DIR','HERMES_HOME','HERMES_WRITE_SAFE_ROOT',
    'HERMES_DISABLE_LAZY_INSTALLS','HERMES_LAZY_INSTALL_TARGET','HOME','MULTICA_WORKSPACES_ROOT',
    'MULTICA_DAEMON_MAX_CONCURRENT_TASKS','MULTICA_AGENT_TIMEOUT','MULTICA_AGENT_IDLE_WATCHDOG',
    'MULTICA_AGENT_TOOL_WATCHDOG','MULTICA_GC_ENABLED','MULTICA_DAEMON_AUTO_RELOAD'}


def image_environment(b):
    info=b.docker('GET','/images/'+b.IMAGE+'/json')
    if not info or info.get('Id')!=b.IMAGE:raise ValueError('exact pinned calibration image required')
    values=info.get('Config',{}).get('Env',[]);environment={}
    if not isinstance(values,list) or len(values)>32:raise ValueError('bounded image environment required')
    for item in values:
        if not isinstance(item,str) or '=' not in item or len(item)>2048:raise ValueError('invalid image environment')
        key,value=item.split('=',1)
        if key not in IMAGE_ENV_KEYS or key in environment:raise ValueError('unknown or credential image environment')
        environment[key]=value
    environment['PYTHONDONTWRITEBYTECODE']='1'
    return [key+'='+value for key,value in sorted(environment.items())]


def payload(b,task,volume,manifest,*,background=False,timers=False):
    return dict(Image=b.IMAGE,User='10000:10000',Entrypoint=['python'],
        Cmd=['/service_mode_timer_background_qualification.py' if timers else
             '/service_mode_background_qualification.py' if background else '/service_mode_harness_qualification.py','/delivery',manifest],
        NetworkDisabled=True,Env=image_environment(b),
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.harness-task':task,
                'delivery-kit.harness-manifest':manifest},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges'],Memory=268435456,NanoCpus=1000000000,PidsLimit=96,
            Mounts=[dict(Type='volume',Source=volume,Target='/delivery',ReadOnly=True)],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'}))


def verify_job(info,expected):
    if not isinstance(info,dict):raise ValueError('harness observation handle unavailable')
    c=info.get('Config',{});h=info.get('HostConfig',{})
    if (any(c.get(k)!=expected[k] for k in ('Image','User','Entrypoint','Cmd'))
            or sorted(c.get('Env',[]))!=sorted(expected['Env'])
            or any(c.get('Labels',{}).get(k)!=v for k,v in expected['Labels'].items())
            or c.get('NetworkDisabled') is not True
            or any(h.get(k)!=v for k,v in expected['HostConfig'].items())):
        raise ValueError('offline harness job identity or isolation drift')


def validate_result(result,prepared,*,require_background=False,require_timers=False):
    from service_mode_harness_qualification import TEST,CASES,validate_controls,fixture
    if (result.get('operation')!='service_mode_harness_calibration_v1' or result.get('status')!='passed'
            or result.get('manifest_sha256')!=prepared['manifest_sha256']
            or result.get('test_sha256')!=prepared['test_sha256'].get(TEST)
            or any(result.get(k) is not False for k in ('product_green','red_approved','delivery_approval'))):
        raise ValueError('exact nonauthorizing candidate harness proof required')
    compiled=result.get('compile',{})
    if (compiled.get('manifest_sha256')!=prepared['manifest_sha256']
            or compiled.get('test_sha256')!=result['test_sha256']
            or any(compiled.get(k,{}).get('exit_code')!=0 for k in ('control','harness','product'))):
        raise ValueError('compiled immutable harness required')
    hashes={case:hashlib.sha256(fixture(case).encode()).hexdigest() for case in ['positive',*CASES]}
    if result.get('control_fixture_sha256')!=hashes:raise ValueError('controller fixtures drift')
    validate_controls(result.get('positive',{}),result.get('negative_controls',{}))
    if require_background:
        from service_mode_background_qualification import BACKGROUND,validate
        validate(result.get('background_control',{}),result['positive'])
        expected=hashlib.sha256((BACKGROUND+fixture('positive')).encode()).hexdigest()
        if result.get('background_fixture_sha256')!=expected:raise ValueError('fixed background fixture proof required')
    if require_timers:
        from service_mode_timer_background_qualification import validate,BACKGROUND,POLL,INDICATOR_TIMERS
        validate(result.get('timer_background_control',{}),result.get('timer_negative_controls',{}))
        if result.get('timer_background_policy')!='behavioral_timer_attribution_v1':
            raise ValueError('new behavioral timer attribution policy required')
        positive=BACKGROUND+fixture('positive')+POLL
        negatives={case:hashlib.sha256((BACKGROUND+INDICATOR_TIMERS.get(case,'')+
            fixture(case if case in CASES else 'positive')+POLL).encode()).hexdigest()
            for case in set(CASES)|set(INDICATOR_TIMERS)}
        if (result.get('timer_positive_fixture_sha256')!=hashlib.sha256(positive.encode()).hexdigest()
                or result.get('timer_negative_fixture_sha256')!=negatives):
            raise ValueError('fixed legitimate polling and all timer-defect fixtures required')


def rejection_state(con,issue,info,raw):
    row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
    owner=json.loads(row[0]).get('cto') if row else None
    if not isinstance(owner,str) or not owner:raise ValueError('persistent CTO route required')
    state=dict(stage='blocked',container_id=info['Id'],output_sha256=hashlib.sha256(raw.encode()).hexdigest(),
               category='harness_calibration_rejected',owner=owner,delivery_approval=False)
    # Retain only diagnostic facts tied to the actual job manifest. Submitted
    # prose, tool requests and success claims cannot expand this receipt.
    try:
        value=json.loads(raw);facts=value['facts'];phase=value['phase']
        expected=info['Config']['Labels']['delivery-kit.harness-manifest']
        if (value.get('status')!='rejected' or value.get('delivery_approval') is not False
                or phase not in ('compile','positive_reference','behavioral_controls','background_control','background_timer_control')
                or facts.get('manifest_sha256')!=expected
                or not re.fullmatch(r'[a-f0-9]{64}',facts.get('test_sha256',''))):return state
        diagnostic=dict(phase=phase,manifest_sha256=expected,test_sha256=facts['test_sha256'])
        counts=('tests','failures','errors','skipped','unexpected_successes','expected_failures')
        def summarize(observed):
            if not isinstance(observed,dict) or not all(type(observed.get(k)) is int and 0<=observed[k]<=10000 for k in counts):return None
            summary={k:observed[k] for k in counts}
            for key in ('failed_methods','errored_methods'):
                names=observed.get(key,[])
                if (isinstance(names,list) and len(names)<=1000 and all(isinstance(n,str)
                        and re.fullmatch(r'(?:test_[A-Za-z0-9_]{1,120}|__fixture__)',n) for n in names)):
                    summary[key]=names
            if re.fullmatch(r'[a-f0-9]{64}',observed.get('output_sha256','')):summary['output_sha256']=observed['output_sha256']
            return summary
        for key in ('positive','background'):
            summary=summarize(facts.get(key))
            if summary is not None:diagnostic[key]=summary
        negatives=facts.get('negative_controls')
        if isinstance(negatives,dict):
            from service_mode_harness_qualification import CASES
            from service_mode_timer_background_qualification import INDICATOR_TIMERS
            if set(negatives)<=set(CASES)|set(INDICATOR_TIMERS):
                summaries={key:summarize(value) for key,value in negatives.items()}
                if all(value is not None for value in summaries.values()):diagnostic['negative_controls']=summaries
        state['diagnostic']=diagnostic
    except (ValueError,TypeError,KeyError):pass
    return state


def retain_missing(con,identity,state):
    route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(identity['issue_id'],)).fetchone()
    owner=json.loads(route[0]).get('cto') if route else None
    if not owner:raise ValueError('missing calibration requires persistent CTO owner')
    result={**state,'stage':'blocked','category':'harness_observation_handle_missing','owner':owner,
        'prior_observation':dict(state),'expected_manifest_sha256':identity['manifest_sha256'],
        'required_action':'diagnose missing recorded calibration handle; never recreate identical job',
        'delivery_approval':False}
    con.execute('UPDATE harness_qualifications SET state=? WHERE task_id=?',
        (json.dumps(result,sort_keys=True),identity['task_id']))
    con.commit();return result


def reconcile_rejected(b,con,task):
    """Observe an existing failed job only; no create/start/retry or approval."""
    row=con.execute('SELECT identity,state FROM harness_qualifications WHERE task_id=?',(task,)).fetchone()
    if not row:raise ValueError('existing harness intent required')
    identity,state=map(json.loads,row)
    if state['stage']=='blocked':return state
    if state['stage']!='observing' or identity['task_id']!=task:raise ValueError('observing exact harness task required')
    pinned=identity['payload'].get('Image','')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',pinned):raise ValueError('recorded pinned harness image required')
    # A missing handle is a nonauthorizing incident, not calibration. Record
    # that absence before requiring an old image to reconstruct job policy.
    # If the container exists, all original isolation checks still apply.
    info=b.docker('GET','/containers/'+state['container_id']+'/json')
    if info is None:return retain_missing(con,identity,state)
    # An upgrade must observe the original immutable job, not reinterpret its
    # isolation contract using the new worker image or create a replacement.
    original=SimpleNamespace(IMAGE=pinned,docker=b.docker,OWNER=b.OWNER)
    background=identity['payload'].get('Cmd',[None])[0]=='/service_mode_background_qualification.py'
    timers=identity['payload'].get('Cmd',[None])[0]=='/service_mode_timer_background_qualification.py'
    if background and pinned not in (BACKGROUND_IMAGE,LEGACY_BACKGROUND_IMAGE):raise ValueError('pinned background calibration image required')
    if timers and pinned!=TIMER_BACKGROUND_IMAGE:raise ValueError('pinned timer calibration image required')
    expected=payload(original,task,identity['volume'],identity['manifest_sha256'],background=background,timers=timers)
    if identity['payload']!=expected:raise ValueError('recorded harness policy drift')
    verify_job(info,expected)
    if info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']==0:
        raise ValueError('existing terminal failed harness job required')
    raw=b.docker_stdout(info['Id'],include_stderr=False,limit=32768)
    retained=rejection_state(con,identity['issue_id'],info,raw)
    con.execute('UPDATE harness_qualifications SET state=? WHERE task_id=?',(json.dumps(retained,sort_keys=True),task))
    con.commit();return retained


def capture(b,con,issue,task,volume,prepared):
    try:import remediation_runtime_guard as guard
    except ImportError:from broker import remediation_runtime_guard as guard
    value=guard.qualified(b,issue)
    if not value or not value.get('amendment'):return None
    from service_mode_harness_qualification import TEST
    if set(prepared['test_sha256'])!={TEST}:raise ValueError('declared amendment test scope required')
    background=value['amendment'].get('kind')=='request_scope'
    timers=value['amendment'].get('kind')=='timer_provenance'
    con.execute('CREATE TABLE IF NOT EXISTS harness_qualifications(task_id TEXT PRIMARY KEY,identity TEXT,state TEXT)')
    row=con.execute('SELECT identity,state FROM harness_qualifications WHERE task_id=?',(task,)).fetchone()
    selected=TIMER_BACKGROUND_IMAGE if timers else BACKGROUND_IMAGE
    if background and row:
        selected=json.loads(row[0])['payload']['Image']
        if selected not in (BACKGROUND_IMAGE,LEGACY_BACKGROUND_IMAGE):raise ValueError('recorded background image is not qualified')
    if timers and row and json.loads(row[0])['payload']['Image']!=TIMER_BACKGROUND_IMAGE:
        raise ValueError('historic traffic-only receipt cannot satisfy timer policy')
    image=SimpleNamespace(IMAGE=selected,docker=b.docker,OWNER=b.OWNER) if background or timers else b
    manifest=prepared['manifest_sha256'];expected=payload(image,task,volume,manifest,background=background,timers=timers)
    identity=dict(issue_id=issue,task_id=task,volume=volume,manifest_sha256=manifest,payload=expected)
    def save(state):
        con.execute('UPDATE harness_qualifications SET state=? WHERE task_id=?',(json.dumps(state,sort_keys=True),task))
        con.commit();return state
    name=b.PREFIX+'-harness-qualification-'+task
    if row:
        if json.loads(row[0])!=identity:raise ValueError('immutable harness identity drift')
        state=json.loads(row[1])
        if state['stage']=='passed':validate_result(state['result'],prepared,require_background=background,require_timers=timers);return state['result']
        if state['stage']=='blocked':raise ValueError('harness qualification retained hold; no identical retry')
    else:
        state=dict(stage='create_intent',created_at=time.time(),delivery_approval=False)
        con.execute('INSERT INTO harness_qualifications VALUES(?,?,?)',(task,json.dumps(identity,sort_keys=True),json.dumps(state)))
        con.commit()
        # Persist BEFORE the external effect. An uncertain POST is observation
        # only on the next call: never issue a second create from the same intent.
        b.docker('POST','/containers/create?name='+name,expected)
    info=b.docker('GET','/containers/'+name+'/json')
    if not info:
        if state.get('stage')=='observing' and state.get('container_id'):
            retain_missing(con,identity,state)
            raise ValueError('recorded harness observation handle missing; CTO diagnosis required')
        raise ValueError('uncertain harness create; observe exact handle, never repeat POST')
    verify_job(info,expected)
    if info['State']['Status']=='created':b.docker('POST','/containers/'+info['Id']+'/start')
    state=save({**state,'stage':'observing','container_id':info['Id']})
    deadline=time.time()+55
    while time.time()<deadline:
        info=b.docker('GET','/containers/'+name+'/json')
        if info is None:
            retain_missing(con,identity,state)
            raise ValueError('recorded harness observation handle missing; CTO diagnosis required')
        verify_job(info,expected)
        if not info['State']['Running']:
            raw=b.docker_stdout(info['Id'],include_stderr=False,limit=32768)
            try:
                if info['State']['ExitCode']!=0:raise ValueError('offline harness calibration rejected')
                result=json.loads(raw);validate_result(result,prepared,require_background=background,require_timers=timers)
            except (ValueError,KeyError,TypeError):
                save(rejection_state(con,issue,info,raw))
                raise ValueError('harness calibration rejected; CTO diagnose immutable candidate')
            save(dict(stage='passed',container_id=info['Id'],result=result,delivery_approval=False))
            return result
        time.sleep(.2)
    raise TimeoutError('harness job remains under observation; no restart')


def require(b,issue,red):
    """Revalidate the same candidate proof before any downstream test approval."""
    try:import remediation_runtime_guard as guard
    except ImportError:from broker import remediation_runtime_guard as guard
    value=guard.qualified(b,issue)
    if not value or not value.get('amendment'):return
    with b.db() as con:
        row=con.execute('SELECT identity,state FROM harness_qualifications WHERE task_id=?',(red['task_id'],)).fetchone()
    if not row:raise ValueError('actual immutable harness calibration required')
    identity,state=map(json.loads,row)
    if (identity['issue_id']!=issue or identity['volume']!=red['volume']
            or identity['manifest_sha256']!=red['red']['manifest_sha256'] or state['stage']!='passed'):
        raise ValueError('same actual Red candidate calibration required')
    validate_result(state['result'],red['red'],require_background=value['amendment'].get('kind')=='request_scope',
                    require_timers=value['amendment'].get('kind')=='timer_provenance')
