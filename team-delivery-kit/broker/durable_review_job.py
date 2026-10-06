"""One fixed readonly coverage job; ambiguous Docker responses are observed, never replayed."""
import hashlib
import json
import re
import time
try:
    import helper_cleanup as cleanup, u3_controls_execution as controls
except ImportError:
    from broker import helper_cleanup as cleanup, u3_controls_execution as controls

WINDOW = 120


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def saved(b,key):
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS durable_review_jobs(job_key TEXT PRIMARY KEY,config TEXT,state TEXT)')
        row=con.execute('SELECT config,state FROM durable_review_jobs WHERE job_key=?',(key,)).fetchone()
    return tuple(map(json.loads,row)) if row else None


def save(b,key,config,state):
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS durable_review_jobs(job_key TEXT PRIMARY KEY,config TEXT,state TEXT)')
        prior=con.execute('SELECT config FROM durable_review_jobs WHERE job_key=?',(key,)).fetchone()
        if prior and json.loads(prior[0])!=config:raise ValueError('fixed review job contract drift')
        con.execute('INSERT OR REPLACE INTO durable_review_jobs VALUES(?,?,?)',
                    (key,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))


def specification(b,key,base,seed,proof):
    if (not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',key)
            or proof.get('controls_manifest_sha256')!=seed['manifest_sha256']
            or proof.get('candidate',{}).get('tests')!=261):
        raise ValueError('fixed coverage job identity and proof required')
    for volume in (base['volume'],seed['snapshot']['volume']):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}',volume):raise ValueError('named readonly volume required')
    for sha in (base['manifest_sha256'],seed['manifest_sha256']):
        if not re.fullmatch(r'[a-f0-9]{64}',sha):raise ValueError('exact coverage manifest required')
    image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('immutable validator image required')
    return dict(schema='durable-coverage-job-v1',image=image,base=base,seed=seed,proof_sha256=digest(proof))


def payload(b,key,config):
    return dict(Image=config['image'],User='10000:10000',Entrypoint=['python'],Cmd=['/u3_product_probe.py'],
        Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1',
             'BASE_MANIFEST='+config['base']['manifest_sha256'],'CONTROLS_MANIFEST='+config['seed']['manifest_sha256']],
        NetworkDisabled=True,Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':controls.SOURCE,
            'delivery-kit.validation-key':key,'delivery-kit.validation-contract':digest(config),
            # Match the controller's central presentation boundary exactly.
            # These jobs live in the -tests group, not the live Compose stack.
            'com.docker.compose.project':b.PREFIX+'-tests','com.docker.compose.service':'job'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=536870912,PidsLimit=96,Mounts=[
                dict(Type='volume',Source=config['base']['volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=config['seed']['snapshot']['volume'],Target='/candidate',ReadOnly=True)],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=128m,mode=1777'}))


def identity(info,expected):
    config=info.get('Config',{});host=info.get('HostConfig',{})
    if (any(config.get(k)!=expected[k] for k in ('Image','User','Entrypoint','Cmd'))
            or any(config.get('Labels',{}).get(k)!=v for k,v in expected['Labels'].items())
            or any(v not in config.get('Env',[]) for v in expected['Env'])
            or host.get('NetworkMode')!='none' or host.get('ReadonlyRootfs') is not True
            or config.get('NetworkDisabled') is not True
            or host.get('CapDrop')!=['ALL'] or host.get('SecurityOpt')!=['no-new-privileges']
            or host.get('Memory')!=536870912 or host.get('PidsLimit')!=96
            or host.get('Mounts')!=expected['HostConfig']['Mounts']):
        raise ValueError('readonly validation container identity drift')


def observe(b,name,expected):
    info=b.docker('GET','/containers/'+name+'/json')
    if info:identity(info,expected)
    return info


def run(b,key,base,seed,proof):
    config=specification(b,key,base,seed,proof)
    prior=saved(b,key)
    if prior:
        old,state=prior
        if old!=config:raise ValueError('fixed review job contract drift')
        if state['phase']=='passed':return state['receipt']
        if state['phase']=='blocked':raise ValueError('fixed review job requires diagnosis; no identical retry')
    else:
        state=dict(phase='prepared',name=b.PREFIX+'-controls-job-'+digest(dict(key=key))[:12],
                   deadline=time.time()+WINDOW,observations=0,events=[])
        save(b,key,config,state)
    name=state['name'];expected=payload(b,key,config)
    try:
        if state['phase']=='prepared':
            if observe(b,name,expected):raise ValueError('unregistered validation container identity')
            state['phase']='create_intent';save(b,key,config,state)
            try:b.docker('POST','/containers/create?name='+name,expected)
            except TimeoutError:
                state['events'].append('create_response_timeout');save(b,key,config,state)
        while time.time()<state['deadline']:
            try:info=observe(b,name,expected)
            except TimeoutError:
                state['observations']+=1;save(b,key,config,state)
                time.sleep(.2);continue  # GET only: no duplicate create/start.
            state['observations']+=1
            if not info:
                time.sleep(.2);continue
            status=info['State'].get('Status')
            if state['phase']=='create_intent':
                state['phase']='created';save(b,key,config,state)
            if state['phase']=='created':
                state['phase']='start_intent';save(b,key,config,state)
                try:b.docker('POST','/containers/'+name+'/start')
                except TimeoutError:
                    state['events'].append('start_response_timeout');save(b,key,config,state)
                state['phase']='running';save(b,key,config,state)
                continue
            if status in ('exited','dead'):
                if info['State']['ExitCode']!=0:raise ValueError('fixed coverage suite failed')
                try:output=b.docker_stdout(name,limit=24576)
                except TimeoutError:
                    time.sleep(.2);continue
                actual=json.loads(output)
                if actual!=proof:raise ValueError('fixed coverage proof drift')
                receipt=dict(schema='durable-coverage-job-receipt-v1',job_key=key,name=name,image=config['image'],
                    contract_sha256=digest(config),proof=actual,output=output,
                    output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                    network='none',snapshot_mount='readonly',recovered_events=list(state['events']))
                state.update(phase='passed',receipt=receipt);save(b,key,config,state)
                try:cleanup.schedule(b,name,controls.SOURCE)
                except Exception:
                    state['cleanup_pending']=True;save(b,key,config,state)
                return receipt
            time.sleep(.2)
        raise TimeoutError('fixed review job observation deadline; no repeated mutation')
    except Exception as error:
        state.update(phase='blocked',error_type=type(error).__name__,
                     operation=getattr(error,'operation',None),next_action='CTO diagnoses exact durable phase; no replay')
        save(b,key,config,state)
        raise
