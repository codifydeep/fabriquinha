"""One immutable offline observation; never retry a native author or approve Red."""
import argparse
import hashlib
import json
import subprocess
import uuid
import docker_grouping
from evalctl import PROJECT,PRIVATE
from release_eval import save_receipt


def presentation(result,task):
    import re
    value=result['result'];facts=value.get('facts') or {};positive=facts.get('positive') or {}
    def hash_value(key):
        value=facts.get(key)
        return value if isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) else None
    counts={k:positive.get(k) if type(positive.get(k)) is int and 0<=positive[k]<=10000 else None
        for k in ('tests','failures','errors','skipped')}
    return dict(source_task=task,container_id=result['container_id'],exit_code=result['exit_code'],
        status=value.get('status') if value.get('status') in ('passed','rejected') else 'unknown',
        phase=value.get('phase') if value.get('phase') in
            ('compile','positive_reference','behavioral_controls','background_control') else None,
        manifest_sha256=hash_value('manifest_sha256'),test_sha256=hash_value('test_sha256'),
        positive=counts,author_retry_authorized=False,delivery_approval=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    if PROJECT!='delivery-kit-port2' or str(uuid.UUID(args.task))!=args.task:
        raise ValueError('canonical isolated failed task required')
    import re
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',args.image):raise ValueError('immutable diagnostic image required')
    script='''import broker as b,json,sys
task=sys.argv[1]
with b.db() as c:
 r=c.execute('SELECT identity,state FROM harness_qualifications WHERE task_id=?',(task,)).fetchone()
 assert r;identity,state=map(json.loads,r)
 assert state['stage']=='blocked' and state['category']=='harness_calibration_rejected'
 assert not c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()
 assert not c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(identity['issue_id'],)).fetchone()
info=b.docker('GET','/containers/'+state['container_id']+'/json')
assert info['State']['Status']=='exited' and not info['State']['Running']
raw=b.docker_stdout(info['Id'],include_stderr=False,limit=32768)
import hashlib
assert hashlib.sha256(raw.encode()).hexdigest()==state['output_sha256']
old=json.loads(raw);assert old['category']=='CalibrationRejected' and 'facts' not in old and 'phase' not in old
print(json.dumps(dict(volume=identity['volume'],manifest_sha256=identity['manifest_sha256'],
 issue_id=identity['issue_id'],source_task=task,owner=b.OWNER,original_output_sha256=state['output_sha256'])))
'''
    metadata=json.loads(subprocess.check_output(['docker','exec','-w','/',PROJECT+'-execution-broker-1',
        'python','-c',script,args.task],text=True))
    labels=json.loads(subprocess.check_output(['docker','volume','inspect',metadata['volume'],
        '--format','{{json .Labels}}'],text=True))
    if labels.get('delivery-kit.owner')!=metadata['owner'] or labels.get('delivery-kit.test-first-task')!=args.task:
        raise ValueError('exact controller-owned test snapshot required')
    image_labels=json.loads(subprocess.check_output(['docker','image','inspect',args.image,
        '--format','{{json .Config.Labels}}'],text=True)) or {}
    if image_labels.get('delivery-kit.purpose')!='calibration-evidence-observation':
        raise ValueError('owned fixed diagnostic image required')
    folder=PRIVATE/'calibration-observations';folder.mkdir(mode=0o700,exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode&0o077:raise ValueError('restricted observation folder required')
    intent=folder/(args.task+'.intent.json');receipt=folder/(args.task+'.json')
    identity=dict(metadata,image=args.image,native_task_replayed=False,author_retry_authorized=False,delivery_approval=False)
    if receipt.exists():
        if receipt.is_symlink() or receipt.stat().st_mode&0o077:raise ValueError('private receipt required')
        result=json.loads(receipt.read_text())
        if result.get('identity')!=identity:raise ValueError('observation identity drift')
    else:
        if intent.exists():raise ValueError('observation outcome uncertain; inspect existing handle, never repeat')
        name=PROJECT+'-calibration-observation-'+args.task
        save_receipt(intent,dict(identity,container_name=name))
        cid=subprocess.check_output(['docker','create','--name',name,
            *docker_grouping.args('calibration-observation',PROJECT),'--network=none','--read-only',
            '--user','10000:10000','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--memory=256m','--cpus=1','--pids-limit=96','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
            '-e','PYTHONPATH=/','-e','PYTHONDONTWRITEBYTECODE=1',
            '--mount','type=volume,source='+metadata['volume']+',target=/delivery,readonly',
            '--entrypoint','python',args.image,'/service_mode_background_qualification.py',
            '/delivery',metadata['manifest_sha256']],text=True).strip()
        try:observed=subprocess.run(['docker','start','-a',cid],text=True,capture_output=True,timeout=55)
        except subprocess.TimeoutExpired:
            raise TimeoutError('observation deadline; inspect existing handle, never repeat') from None
        if len(observed.stdout.encode())>65536:raise ValueError('bounded diagnostic output required')
        info=json.loads(subprocess.check_output(['docker','inspect',cid,'--format','{{json .State}}'],text=True))
        if info['Running'] or info['Status']!='exited':raise ValueError('observation remains live; inspect exact handle')
        result=dict(identity=identity,container_id=cid,exit_code=info['ExitCode'],
            output_sha256=hashlib.sha256(observed.stdout.encode()).hexdigest(),result=json.loads(observed.stdout))
        save_receipt(receipt,result)
    print(json.dumps(presentation(result,args.task)))


if __name__=='__main__':main()
