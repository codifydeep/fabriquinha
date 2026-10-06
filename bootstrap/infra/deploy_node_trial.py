"""Local first-deploy smoke and undeploy/recovery drill; not independent QA."""
import base64,hashlib,json,sqlite3,subprocess,time,urllib.request,urllib.error
from publish_product_node_trial import api,ROOT

NAME='truco-online-adapter-homologation'
PORT=18876

def docker(*args):return subprocess.run(['docker',*args],check=True,capture_output=True,text=True,timeout=60).stdout.strip()

def main():
    journal=sqlite3.connect(ROOT/'node-publication.db')
    merge=json.loads(journal.execute("SELECT value FROM receipts WHERE key='merge'").fetchone()[0])['merge']
    pr=api('pulls/21');assert pr['merged'] and pr['merge_commit_sha']==merge
    def read(path):return base64.b64decode(api('contents/'+path+'?ref='+merge)['content'])
    policy=json.loads(read('adapter-control/expected.json'))
    files={n:read(n) for n in policy['files']}
    assert {n:hashlib.sha256(raw).hexdigest() for n,raw in files.items()}==policy['files']
    target=ROOT/('deploy-'+merge)
    existing=target.exists()
    target.mkdir(mode=0o755,exist_ok=True)
    for name,raw in files.items():
        path=target/name.removeprefix('adapter-node/');path.parent.mkdir(parents=True,exist_ok=True)
        if existing:assert path.read_bytes()==raw
        else:path.write_bytes(raw);path.chmod(0o444)
    service=read('adapter-control/service.mjs')
    if existing:assert (target/'service.mjs').read_bytes()==service
    else:(target/'service.mjs').write_bytes(service);(target/'service.mjs').chmod(0o444)
    found=docker('ps','-aq','--filter','name=^/'+NAME+'$')
    if found:
        container=json.loads(docker('inspect',NAME))[0]
        assert container['Image']==policy['image'] and 'APP_COMMIT='+merge in container['Config']['Env']
        assert container['Config']['Labels']['com.docker.compose.service']=='adapter-homologation'
        assert any(m['Source']==str(target) and m['Destination']=='/app' and not m['RW'] for m in container['Mounts'])
        if 'truco-online-adapter-internal' in container['NetworkSettings']['Networks']:
            docker('network','connect','bridge',NAME)
            docker('network','disconnect','truco-online-adapter-internal',NAME)
            docker('restart','--timeout','5',NAME)
    else:docker('run','-d','--name',NAME,'--pull=never','--label','com.docker.compose.project=truco-online',
           '--label','com.docker.compose.service=adapter-homologation','--network','bridge',
           '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=64','--memory=128m','--cpus=0.5',
           '--user=10000:10000','--mount',f'type=bind,src={target},dst=/app,readonly','--workdir=/app',
           '-e','APP_COMMIT='+merge,'-p',f'127.0.0.1:{PORT}:8080','--entrypoint=node',policy['image'],'service.mjs')
    def probe(path,status=200):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}'+path,timeout=3) as response:code=response.status;body=json.load(response)
        except urllib.error.HTTPError as exc:code=exc.code;body=json.load(exc)
        assert code==status and body['commit']==merge,(code,body)
        return body
    for attempt in range(15):
        try:probe('/health');break
        except (OSError,AssertionError):
            if attempt==14:raise
            time.sleep(1)
    for n,expected in ((0,False),(1,True),(2,False),(-1,False)):
        assert probe('/capacity?n='+str(n))['capacity']==expected
    probe('/capacity?n=abc',400);probe('/capacity?n=1&n=2',400);probe('/absent',404)
    docker('stop','--timeout','5',NAME)
    try:urllib.request.urlopen(f'http://127.0.0.1:{PORT}/health',timeout=2)
    except OSError:pass
    else:raise AssertionError('undeploy did not remove service')
    docker('start',NAME)
    for attempt in range(15):
        try:probe('/health');break
        except OSError:
            if attempt==14:raise
            time.sleep(1)
    result=dict(commit=merge,url=f'http://127.0.0.1:{PORT}',smoke_passed=True,undeploy_restore_passed=True,
                previous_version_rollback_tested=False,independent_qa=False,release_homologated=False)
    with journal:journal.execute('INSERT INTO receipts VALUES(?,?)',('deploy-smoke',json.dumps(result)))
    print(json.dumps(result));journal.close()

if __name__=='__main__':main()
