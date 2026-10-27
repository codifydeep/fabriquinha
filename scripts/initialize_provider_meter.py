"""Initialize only a new, empty private meter; never repair/reset an old ledger.

Run once before starting the relay, as its filesystem owner. An interrupted
initialization stays visible and requires inspection, not automatic retry.
No credentials, provider requests, policy enablement or limit changes.
"""
import argparse
import json
import os
from pathlib import Path


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


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--new-meter',type=Path,required=True)
    print(json.dumps(initialize(parser.parse_args().new_meter),sort_keys=True))
