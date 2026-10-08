"""Offline fixed-input qualification of the installed Hermes patch/write path.

No ACP prompt, model call, product workspace or delivery approval. The native
LocalEnvironment and ShellFileOperations are real; no tool/backend is mocked.
"""
import inspect
import json
import hashlib
from pathlib import Path
import subprocess

from evalctl import PRIVATE, PROJECT
from release_eval import save_receipt


def native_case():
    import os
    import hashlib
    from pathlib import Path
    from tools.environments.local import LocalEnvironment
    from tools.file_operations import ShellFileOperations
    target=Path('/workspace/tests/test_new.py')
    before=target.read_bytes()
    baseline={p:Path(p).read_bytes() for p in ('/workspace/app.py','/workspace/tests/test_old.py')}
    old="QUERY = 'calls.length'"
    invalid="QUERY = 'calls.filter(c => c.url === '/service-mode').length'"
    corrected='QUERY = \'calls.filter(c => c.url === "/service-mode").length\''
    env=LocalEnvironment(cwd='/workspace',timeout=15,env={'HOME':'/tmp'})
    ops=ShellFileOperations(env,cwd='/workspace')
    rejected=ops.patch_replace(str(target),old,invalid)
    preserved=target.read_bytes()==before
    accepted=ops.patch_replace(str(target),old,corrected)
    actual=target.read_bytes()
    expected=before.replace(old.encode(),corrected.encode())
    result=dict(uid=os.getuid(),invalid_patch_rejected=rejected.success is False,
        fixed_syntax_error=('fenced Python syntax rejected' in (rejected.error or '')),
        rejected_patch_preserved_bytes=preserved,valid_patch_success=accepted.success is True,
        exact_quotes_preserved=actual==expected,
        baseline_unchanged=all(Path(p).read_bytes()==content for p,content in baseline.items()),
        credentials_absent=not any(Path(p).exists() for p in ('/var/run/docker.sock',
            '/broker-state/token','/secret/openrouter.key','/run/secrets/openrouter_api_key')),
        writer_sha256=hashlib.sha256(Path('/fenced_file_write.py').read_bytes()).hexdigest(),
        output_sha256=hashlib.sha256(actual).hexdigest())
    if hasattr(env,'cleanup'):env.cleanup()
    return result


def valid_result(record,writer_sha256):
    return (record.get('uid')==10000 and record.get('writer_sha256')==writer_sha256
        and all(record.get(k) is True for k in ('invalid_patch_rejected','fixed_syntax_error',
            'rejected_patch_preserved_bytes','valid_patch_success','exact_quotes_preserved',
            'baseline_unchanged','credentials_absent')))


def native_program():
    return ('import json\n'+inspect.getsource(native_case)+
        '\ntry:\n    record=native_case()\nexcept Exception as error:\n'
        '    record={"native_failure_category":type(error).__name__}\nprint(json.dumps(record))\n')


def remote_probe(program,writer_sha256):
    import json
    import uuid
    import struct
    import time
    import broker as b
    if b.PREFIX!='delivery-kit-port2':raise ValueError('isolated namespace required')
    identifier=str(uuid.uuid4());name=b.PREFIX+'-native-patch-job-'+identifier
    owner=b.PREFIX+'-native-patch-probe-v1'
    result=dict(schema='native-patch-probe-v1',status='failed',execution_id=identifier,
        worker_image=b.IMAGE,model_calls=0,delivery_approval=False,product_retry=False)
    setup="""from pathlib import Path
import time
p=Path('/workspace');(p/'tests').mkdir()
(p/'app.py').write_text('VALUE = 0\\n')
(p/'tests/test_old.py').write_text('baseline preserved\\n')
(p/'tests/test_new.py').write_text("import unittest\\nQUERY = 'calls.length'\\nclass Probe(unittest.TestCase):\\n    def test_fixture(self): self.assertEqual(QUERY, 'calls.length')\\n")
for f in (p/'app.py',p/'tests/test_old.py'):f.chmod(0o444)
(p/'tests/test_new.py').chmod(0o666);(p/'tests').chmod(0o555);p.chmod(0o555)
print('fixture-ready',flush=True)
time.sleep(90)
"""
    created=False
    private_output={}
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=b.IMAGE,User='0:0',
            Entrypoint=['python'],Cmd=['-c',setup],WorkingDir='/tmp',
            Labels={'delivery-kit.owner':owner,'delivery-kit.request':identifier},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
                SecurityOpt=['no-new-privileges'],Memory=536870912,NanoCpus=1000000000,PidsLimit=64,
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777',
                    '/workspace':'rw,nosuid,nodev,size=1m,mode=0777'})))
        created=True;b.docker('POST','/containers/'+name+'/start')
        for _ in range(30):
            if b.docker_stdout(name).strip()=='fixture-ready':break
            time.sleep(.2)
        else:raise ValueError('fixture unavailable')
        execution=b.docker('POST','/containers/'+name+'/exec',dict(AttachStdout=True,AttachStderr=True,
            User='10000:10000',WorkingDir='/workspace',Cmd=['python','-c',program],
            Env=['HOME=/tmp','HERMES_HOME=/tmp/hermes','HERMES_FENCED_INPLACE_WRITES=1',
                 'HERMES_WRITE_SAFE_ROOT=/workspace','DELIVERY_EXECUTION_MODE=implementation',
                 'PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/opt/hermes:/']))['Id']
        conn=b.DockerConnection('localhost',timeout=45)
        try:
            conn.request('POST','/v1.45/exec/'+execution+'/start',json.dumps(dict(Detach=False,Tty=False)),
                {'Content-Type':'application/json'})
            response=conn.getresponse();data=response.read(8193)
            if response.status!=200 or len(data)>8192:raise ValueError('bounded probe output required')
            output=b'';stderr=b'';offset=0
            while offset<len(data):
                size=struct.unpack('>I',data[offset+4:offset+8])[0]
                if data[offset] not in (1,2) or offset+8+size>len(data):raise ValueError('invalid Docker frame')
                if data[offset]==1:output+=data[offset+8:offset+8+size]
                else:stderr+=data[offset+8:offset+8+size]
                offset+=8+size
            import base64
            private_output=dict(stdout_base64=base64.b64encode(output).decode(),
                                stderr_base64=base64.b64encode(stderr).decode())
            result['inspection']=json.loads(output)
            if valid_result(result['inspection'],writer_sha256):result['status']='passed'
        finally:conn.close()
    except Exception as error:result['failure_category']=type(error).__name__
    finally:
        if created:
            container=b.docker('GET','/containers/'+name+'/json')
            labels=container['Config'].get('Labels',{})
            if labels.get('delivery-kit.owner')!=owner or labels.get('delivery-kit.request')!=identifier:
                raise ValueError('cleanup identity mismatch')
            b.docker('POST','/containers/'+container['Id']+'/stop?t=1')
            stopped=b.docker('GET','/containers/'+container['Id']+'/json')
            if stopped['State']['Running'] or stopped['Id']!=container['Id']:raise ValueError('stop uncertain')
            evidence=b.STATE/'synthetic-probe-evidence';evidence.mkdir(mode=0o700,exist_ok=True)
            if evidence.is_symlink():raise ValueError('unsafe evidence path')
            path=evidence/(identifier+'.json')
            with path.open('x') as stream:json.dump(dict(result=result,private_output=private_output),stream,sort_keys=True)
            path.chmod(0o600)
            final=b.docker('GET','/containers/'+container['Id']+'/json')
            final_labels=final['Config'].get('Labels',{})
            if (final['Id']!=container['Id'] or final['State']['Running']
                    or final_labels.get('delivery-kit.owner')!=owner
                    or final_labels.get('delivery-kit.request')!=identifier):
                raise ValueError('retirement ownership changed')
            b.docker('DELETE','/containers/'+container['Id']+'?force=false')
            result['fixture_removed']=True
    return result


def main():
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated project required')
    program=native_program()
    writer_sha=hashlib.sha256((Path(__file__).parent/'broker/fenced_file_write.py').read_bytes()).hexdigest()
    source=inspect.getsource(valid_result)+'\n'+inspect.getsource(remote_probe)+'\nimport json\nprint(json.dumps(remote_probe('+repr(program)+','+repr(writer_sha)+')))\n'
    process=subprocess.run(['docker','exec','-i','-e','PYTHONPATH=/',PROJECT+'-execution-broker-1',
        'python','-c',source],text=True,capture_output=True)
    if process.returncode:raise RuntimeError('fixed native probe unavailable; raw output withheld')
    result=json.loads(process.stdout)
    if valid_result(result.get('inspection',{}),writer_sha):result['status']='passed'
    save_receipt(PRIVATE/'provider-probes'/('native-patch-'+result['execution_id']+'.json'),result)
    print(json.dumps(result));return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
