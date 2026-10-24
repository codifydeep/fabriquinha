"""Fixed synthetic delivery-review sandbox qualification; no native approval.

--prepare creates public synthetic base/candidate inputs in a new private
qualification directory. --check runs inside a disposable socketless container
with those exact inputs mounted read-only. It never calls a provider/model.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys


def isolated_network(up_interfaces,routes4,routes6):
    assert up_interfaces=={'lo'}
    rows4=[line.split() for line in routes4.splitlines() if line.strip()]
    assert rows4 and rows4[0][0]=='Iface'
    assert all(len(row)==11 and row[0]=='lo' for row in rows4[1:])
    assert all(len(row)==10 and row[-1]=='lo' for row in
        (line.split() for line in routes6.splitlines() if line.strip()))


def prepare(destination):
    from test_quality_delivery_review_job import DeliveryReviewJobTests
    root=Path(destination)
    assert root.is_absolute() and root.resolve()==root and not root.exists() and root.parent.is_dir()
    root.mkdir(mode=0o700)
    fixture=DeliveryReviewJobTests();fixture.setUp()
    try:
        fixture.prepare()
        for name,source in (('base',fixture.f.f.base),('snapshot',fixture.f.green)):
            target=root/name;shutil.copytree(source,target)
            for p in target.rglob('*'):
                assert not p.is_symlink()
                p.chmod(0o555 if p.is_dir() else 0o444)
            target.chmod(0o555)
        fd=os.open(root/'request.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as out:
            json.dump(fixture.value,out,sort_keys=True);out.flush();os.fsync(out.fileno())
    finally:fixture.doCleanups()
    return dict(stage='prepared_synthetic_delivery_review',model_calls=0,delivery_approval=False)


def check():
    import fcntl
    import struct
    import quality_delivery_review_job as job
    assert os.getuid()==os.getgid()==10000
    assert not Path('/var/run/docker.sock').exists() and not Path('/secret/openrouter.key').exists()
    # Linux may expose inactive default tunnel devices even with network=none.
    # Require only loopback UP and no route via any other interface, rather than
    # mistaking the names of inactive devices for external connectivity.
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as control:
        active=set()
        for _,name in socket.if_nameindex():
            flags=fcntl.ioctl(control.fileno(),0x8913,struct.pack('256s',name.encode()))
            if struct.unpack_from('H',flags,16)[0]&1:active.add(name)
    isolated_network(active,Path('/proc/net/route').read_text(),Path('/proc/net/ipv6_route').read_text())
    for name in os.environ:
        assert not any(s in name.lower() for s in ('token','password','api_key','credential'))
    mounts={line.split()[1]:line.split()[3].split(',') for line in Path('/proc/mounts').read_text().splitlines()}
    assert all('ro' in mounts.get(p,[]) for p in ('/','/base','/snapshot'))
    before=hashlib.sha256(Path('/snapshot/manifest.json').read_bytes()).hexdigest()
    for root in ('/base','/snapshot'):
        try:Path(root,'app.py').write_bytes(b'PROHIBITED')
        except OSError as error:assert error.errno in (errno.EROFS,errno.EACCES)
        else:raise AssertionError('snapshot write was not denied')
    value=job.request(os.environ['QUALITY_DELIVERY_REVIEW_JOB_JSON'])
    observed=job.run('/base','/snapshot',value)
    assert observed['task_id']==value['task_id'] and observed['suite']['tests_run']==2
    assert observed['manifest_sha256']==before==hashlib.sha256(Path('/snapshot/manifest.json').read_bytes()).hexdigest()
    assert observed['suite']['tests']==value['evidence']['green']['tests']
    assert all(observed[k] is False for k in ('native_identity_verified','job_receipt_verified',
        'tests_approved','merge_authorized','delivery_approval'))
    rejected=0
    for change in (dict(reviewer=value['plan']['author']),dict(task_id=value['evidence']['green']['task_id']),
            dict(snapshot_manifest_sha256='0'*64),dict(command=['sh']),dict(test_paths=['tests/test_new.py'])):
        try:job.request(json.dumps({**value,**change}))
        except ValueError:rejected+=1
        else:raise AssertionError('invalid fixed request accepted')
    return dict(operation='fixed_delivery_review_runtime_canary_v1',status='passed',
        tests_run=observed['suite']['tests_run'],controls_rejected=rejected,
        read_only_mounts=True,writes_denied=True,network='none',credential_mounts=False,docker_socket=False,
        model_calls=0,real_provider_calls=0,validation_facts_sha256=job.quality.digest(observed),
        native_identity_verified=False,job_receipt_verified=False,tests_approved=False,
        merge_authorized=False,delivery_approval=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare');mode.add_argument('--check',action='store_true');args=parser.parse_args()
    print(json.dumps(prepare(args.prepare) if args.prepare else check(),sort_keys=True),flush=True)
