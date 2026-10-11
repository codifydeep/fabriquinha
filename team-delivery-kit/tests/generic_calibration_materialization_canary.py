"""Real fixed-job canary, no native/model authorization; preserve volume proof."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid
import http.client
import socket
from functools import lru_cache

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from broker import generic_calibration_materialization as jobs,generic_calibration_proposal as producer
from generic_harness_calibration import digest
from generic_calibration_bundle_writer import decode_environment
from test_generic_calibration_proposal import ProposalTests


def command(*args):
    # Match the installed controller API. Newer CLI API projections omit the
    # legacy NetworkDisabled field, which must not be invented by a verifier.
    environment={**os.environ,'DOCKER_API_VERSION':'1.45'}
    try:reply=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=20,env=environment)
    except subprocess.TimeoutExpired:raise TimeoutError('observe exact fixed Docker operation; never repeat write') from None
    if reply.returncode:raise ValueError('fixed canary Docker operation rejected; preserve exact resources')
    return reply


@lru_cache(maxsize=1)
def endpoint():
    host=command('context','inspect','--format','{{.Endpoints.docker.Host}}').stdout.strip()
    if not host.startswith('unix:///'):raise ValueError('local Unix Docker context required; no remote daemon')
    return host[7:]


class LocalConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout);self.sock.connect(endpoint())


def docker(method,path,body=None):
    allowed=(method=='GET' and path.startswith(('/images/','/volumes/','/containers/'))
        or method=='POST' and (path=='/volumes/create' or path.startswith('/containers/create?name=')
            or path.startswith('/containers/') and path.endswith('/start')))
    if not allowed:raise ValueError('canary adapter refuses operation outside fixed materialization')
    con=LocalConnection('localhost',timeout=10)
    try:
        con.request(method,'/v1.45'+path,json.dumps(body).encode() if body is not None else None,
            {'Content-Type':'application/json'})
        response=con.getresponse();raw=response.read(1048577)
        if len(raw)>1048576:raise ValueError('bounded Docker observation required')
        if response.status==404 and method=='GET':return None
        if not 200<=response.status<300:raise ValueError('fixed Docker API operation rejected; preserve resources')
        return json.loads(raw) if raw else {}
    finally:con.close()


def stdout(container,include_stderr=False,limit=65536):
    reply=command('logs',container);value=reply.stdout+(reply.stderr if include_stderr else '')
    if len(value.encode())>limit:raise ValueError('canary log exceeds exact evidence bound')
    return value


def main(image,resume=None):
    fixture=ProposalTests();fixture.setUp()
    try:
        record=producer.bundle(fixture.body,fixture.value,fixture.route,fixture.prepared)
        # Unique native-free evidence identity prevents collision with a real
        # production proposal. This synthetic producer grants no approvals.
        record['producer']={'task_id':str(uuid.uuid4()),'actor':'canary-not-native','wakeup_id':'none'}
        root=Path(__file__).resolve().parents[1]/'.local-port2/backups'
        if resume:
            archive=Path(resume)
            if (archive.is_symlink() or archive.resolve().parent!=root.resolve()
                    or not archive.name.startswith('materialization-canary-')):
                raise ValueError('exact private canary archive required')
            database=archive/'jobs.sqlite'
            if database.is_symlink() or not database.is_file():raise ValueError('persisted canary database required')
        else:
            archive=root/('materialization-canary-'+record['producer']['task_id']);archive.mkdir(mode=0o700)
            database=archive/'jobs.sqlite'
            descriptor=os.open(database,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
        con=sqlite3.connect(database)
        try:
            if resume:
                prior=con.execute('SELECT record FROM generic_calibration_proposals WHERE issue_id=? AND author_task=?',
                    ('canary-issue','canary-author')).fetchone()
                if not prior:raise ValueError('exact original canary proposal required')
                record=json.loads(prior[0])
            else:producer.store(con,'canary-issue','canary-author',record);con.commit()
            b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='calibration-materialization-canary',
                GENERIC_CALIBRATION_WRITER_IMAGE=image,docker=docker,docker_stdout=stdout)
            deadline=time.monotonic()+60
            while True:
                try:result=jobs.run(b,con,'canary-issue','canary-author');break
                except TimeoutError:
                    if time.monotonic()>=deadline:raise
                    time.sleep(.25)
            row=con.execute('SELECT identity,state FROM generic_calibration_materializations').fetchone()
            identity,state=map(json.loads,row)
            info=docker('GET','/containers/'+result['container_id']+'/json')
            if info['State']['Status']!='exited' or info['State']['ExitCode']!=0:raise ValueError('terminal canary required')
            for name,value in (('job.json',dict(identity=identity,state=state)),('result.json',result)):
                with os.fdopen(os.open(archive/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
                    json.dump(value,stream,sort_keys=True)
            # Exact-ID retirement only after durable evidence; retain volumes.
            observed=docker('GET','/containers/'+result['container_id']+'/json')
            if observed['Id']!=result['container_id'] or observed['State']['Running']:
                raise ValueError('canary changed before retirement')
            jobs.verify(b,observed,identity['payload'])
            command('container','rm',result['container_id'])
            print(json.dumps(dict(status='passed',receipt=result['receipt'],
                readonly_root=True,network='none',socket_mounted=False,native_approvals=False,
                current_delivery_changed=False,proof_volumes_preserved=True,archive=str(archive)),sort_keys=True))
        finally:con.close()
    finally:fixture.doCleanups()


def retire_rejected(container):
    """Explicit exact-ID administrative action for a never-started canary."""
    info=docker('GET','/containers/'+container+'/json')
    if not info or info['Id']!=container or info['State']['Status']!='created' or info['State']['Running']:
        raise ValueError('exact never-started canary required')
    config=info['Config'];tags=config['Labels']
    if (tags.get('delivery-kit.owner')!='calibration-materialization-canary'
            or tags.get('com.docker.compose.project')!='delivery-kit-port2-tests'):
        raise ValueError('canary ownership mismatch')
    record=decode_environment(next(v.split('=',1)[1] for v in config['Env'] if v.startswith('CALIBRATION_BUNDLE_ZLIB=')))
    sha=digest(record)
    if tags.get('delivery-kit.calibration-bundle')!=sha or config['Cmd']!=[
            '/generic_calibration_bundle_writer.py','/controls','/policy','--environment',sha]:
        raise ValueError('exact fixed canary command and bundle required')
    archive=Path(__file__).resolve().parents[1]/'.local-port2/backups'/('rejected-materialization-canary-'+container[:24])
    archive.mkdir(mode=0o700)
    with os.fdopen(os.open(archive/'evidence.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as stream:
        json.dump(dict(operation='preserved_never_started_canary_v1',inspection=info,
            native_approvals=False,tests_executed=False,delivery_approval=False),stream,sort_keys=True)
    current=docker('GET','/containers/'+container+'/json')
    if (current['Id']!=container or current['State']['Status']!='created' or current['State']['Running']
            or current['Config']!=config or current['Image']!=info['Image']):
        raise ValueError('canary changed after archive; retain it')
    command('container','rm',container)
    print(json.dumps(dict(retired_exact_id=container,proof_volumes_preserved=True,archive=str(archive))))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--retire-rejected':retire_rejected(sys.argv[2])
    elif len(sys.argv)==4 and sys.argv[1]=='--resume':main(sys.argv[2],sys.argv[3])
    else:main(sys.argv[1])
