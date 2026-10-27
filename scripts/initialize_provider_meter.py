"""Initialize only a new, empty private meter; never repair/reset an old ledger.

Run once before starting the relay, as its filesystem owner. An interrupted
initialization stays visible and requires inspection, not automatic retry.
No credentials, provider requests, policy enablement or limit changes.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def initialize(root):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('existing regular empty private directory required')
    if root.stat().st_mode&0o077:
        raise ValueError('meter directory must be private (0700)')
    if any(root.iterdir()):
        raise ValueError('refusing existing or interrupted meter; never reset')
    # Exclusive marker also rejects simultaneous initializers. It is retained
    # on failure: the relay must not infer a fresh zero from missing history.
    marker=root/'initialization.json'
    with marker.open('x') as stream:
        marker.chmod(0o600)
        json.dump(dict(version=1,origin='explicit_new_meter',initial_calls=0),stream)
        stream.flush();os.fsync(stream.fileno())
    counter=root/'calls.json'
    with counter.open('x') as stream:
        counter.chmod(0o600);stream.write('{"calls":0}\n')
        stream.flush();os.fsync(stream.fileno())
    descriptor=os.open(root,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return dict(initialized=True,calls=0,model_calls=0,provider_enabled=False)


def initialize_storage(meter,secret,credential,uid=10000):
    """Fixed offline Compose bootstrap, before a relay exists. No overwrites."""
    meter,secret=Path(meter),Path(secret)
    if (os.geteuid()!=0 or uid!=10000 or not isinstance(credential,bytes) or len(credential)>4096
            or not 8<=len(credential.strip())<=4096
            or any(byte<33 or byte>126 for byte in credential.strip())):
        raise ValueError('root bootstrap, fixed relay owner and bounded credential required')
    for path in (meter,secret):
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):
            raise ValueError('two empty regular storage directories required; never reset')
    if (meter.stat().st_dev,meter.stat().st_ino)==(secret.stat().st_dev,secret.stat().st_ino):
        raise ValueError('meter and credential storage must be distinct')
    meter.chmod(0o700);secret.chmod(0o700)
    initialize(meter)
    key=secret/'openrouter.key'
    with key.open('xb') as stream:
        key.chmod(0o400);stream.write(credential.strip());stream.flush();os.fsync(stream.fileno())
    descriptors=[os.open(path,os.O_RDONLY) for path in (meter,secret)]
    try:
        for path in (*meter.iterdir(),key,meter,secret):os.chown(path,uid,uid)
        for descriptor in descriptors:os.fsync(descriptor)
    finally:
        for descriptor in descriptors:os.close(descriptor)
    return dict(initialized=True,calls=0,credential_installed=True,model_calls=0,provider_enabled=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--new-meter',type=Path,required=True)
    parser.add_argument('--new-secret',type=Path)
    args=parser.parse_args()
    value=(initialize_storage(args.new_meter,args.new_secret,sys.stdin.buffer.read(4097))
           if args.new_secret else initialize(args.new_meter))
    print(json.dumps(value,sort_keys=True))
