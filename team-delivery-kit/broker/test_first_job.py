"""Durable controller-only copy/Red jobs; uncertain effects are never replayed."""
import hashlib
import json
import time
import uuid
from docker_grouping import grouped_create


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS test_first_jobs(job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')


def verify(b,info,expected):
    config=info.get('Config',{});host=info.get('HostConfig',{})
    if (info.get('Image')!=expected['Image'] or
            any(config.get(k)!=expected[k] for k in ('User','Entrypoint','Cmd'))
            or ('WorkingDir' in expected and config.get('WorkingDir')!=expected['WorkingDir'])
            or any(config.get('Labels',{}).get(k)!=v for k,v in expected['Labels'].items())
            or any(host.get(k)!=v for k,v in expected['HostConfig'].items())
            or config.get('NetworkDisabled') not in (True,False)
            or host.get('NetworkMode')!='none'):
        raise ValueError('fixed test-first job isolation drift')
    inherited=(b.docker('GET','/images/'+expected['Image']+'/json') or {}).get('Config',{}).get('Env',[])
    env={v.split('=',1)[0]:v for v in inherited}
    env.update({v.split('=',1)[0]:v for v in expected['Env']})
    if sorted(config.get('Env',[]))!=sorted(env.values()):raise ValueError('fixed test-first job environment drift')


def run(b,con,task,phase,payload,*,now=None):
    if str(uuid.UUID(task))!=task or phase not in ('copy','red'):
        raise ValueError('fixed test-first phase and task required')
    now=time.time() if now is None else now
    initialize(con)
    name=b.PREFIX+'-test-first-'+phase+'-v2-'+task
    key=task+':'+phase
    expected={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.test-first-task':task,'delivery-kit.test-first-job':key}}
    expected=grouped_create('POST','/containers/create?name='+name,expected,b.PREFIX)
    identity=dict(name=name,payload=expected)
    row=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(key,)).fetchone()
    if row:
        if phase=='copy':
            # Destination existence changes after creation. The first recorded
            # resume flag remains the immutable command's authority.
            previous=json.loads(row[0])['payload']['Env']
            if all(v.startswith('TEST_FIRST_RESUME=') for v in [*previous,*expected['Env']]):
                expected['Env']=previous
        if json.loads(row[0])!=identity:raise ValueError('immutable test-first job drift')
        state=json.loads(row[1])
        if state['stage']=='complete':return state['result']
        if state['stage']=='blocked':raise ValueError('test-first job blocked; no identical retry')
    else:
        if b.docker('GET','/containers/'+name+'/json'):raise ValueError('unregistered test-first job')
        state=dict(stage='prepared',deadline=now+600,approval=False)
        con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',(key,json.dumps(identity,sort_keys=True),json.dumps(state)))
        con.commit()
    def save(**values):
        state.update(values)
        con.execute('UPDATE test_first_jobs SET state=? WHERE job_key=?',(json.dumps(state,sort_keys=True),key))
        con.commit()
    if now>=state['deadline']:
        save(stage='blocked',category='observation_deadline')
        raise ValueError('test-first job observation deadline; preserve exact handle')
    if state['stage']=='prepared':
        save(stage='create_intent')
        try:b.docker('POST','/containers/create?name='+name,expected)
        except TimeoutError:raise TimeoutError('observe test-first create; no repeated POST') from None
    info=b.docker('GET','/containers/'+name+'/json')
    if not info:raise TimeoutError('observe exact test-first handle; no repeated create')
    verify(b,info,expected)
    if state['stage']=='create_intent':save(stage='created',container_id=info['Id'])
    if info['Id']!=state['container_id']:raise ValueError('test-first job identity changed')
    if state['stage']=='created':
        if info['State']['Status']!='created':raise ValueError('unstarted test-first job state drift')
        save(stage='start_intent')
        try:b.docker('POST','/containers/'+info['Id']+'/start')
        except TimeoutError:raise TimeoutError('observe test-first start; no repeated POST') from None
        info=b.docker('GET','/containers/'+info['Id']+'/json');verify(b,info,expected)
    if info['State']['Status']!='exited':raise TimeoutError('test-first job pending; observe existing execution')
    output=b.docker_stdout(info['Id'],include_stderr=phase=='red',limit=65536)
    result=dict(container_id=info['Id'],exit_code=info['State']['ExitCode'],output=output,
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),approval=False)
    save(stage='complete',result=result)
    try:
        import helper_cleanup
    except ImportError:
        from broker import helper_cleanup
    try:helper_cleanup.schedule(b,name,task)
    except Exception:save(cleanup_pending=True)  # Result is already durable; no repeated execution.
    return result
