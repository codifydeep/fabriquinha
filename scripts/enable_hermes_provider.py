"""Explicit operator enablement after a human grants inference consumption.

Checks the disabled relay's metadata and exact counter/ceiling. Never reads the
provider key, resets the ledger, removes a hold or increases the existing cap.
Recreate the Compose relay afterwards: no live policy reload is supported.
"""
import argparse
import http.client
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.effects import write_json
from fabriquinha.provider import Policy


def enable(root,expected_calls,expected_limit):
    path=Path(root)/'provider-policy.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_mode&0o077 or path.stat().st_size>4096:
        raise ValueError('existing private operator policy required')
    policy=Policy.parse(json.loads(path.read_bytes()))
    route=json.loads((Path(root)/'route.json').read_bytes())
    from urllib.parse import urlsplit
    url=urlsplit(route['base_url'])
    if (url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.path!='/v1'
            or url.username or url.password or url.query or url.fragment
            or route['model']!=policy.model or route['api_key']!=policy.client_token
            or policy.enabled or policy.max_calls!=expected_limit
            or type(expected_calls) is not int or not 0<=expected_calls<expected_limit):
        raise ValueError('disabled matching policy and exact authorized existing budget required')
    connection=http.client.HTTPConnection('127.0.0.1',url.port,timeout=5)
    try:
        connection.request('GET','/status');reply=connection.getresponse()
        if reply.status!=200:raise ValueError('relay metadata unavailable')
        value=json.loads(reply.read(16385))
    finally:connection.close()
    if (value.get('project')!=policy.project or value.get('policy')!=policy.fingerprint()
            or value.get('calls')!=expected_calls or value.get('max_calls')!=expected_limit
            or value.get('enabled') is not False or value.get('credential_present') is not True
            or value.get('provider_pause') is not None or value.get('relay_hold') is not None):
        raise ValueError('counter, policy or provider pause changed; do not enable')
    updated=Policy.parse({**policy.values(),'enabled':True})
    write_json(path,updated.values())
    result=dict(project=policy.project,enabled=True,calls_before=expected_calls,max_calls=expected_limit,
        model_calls=0,recreate_relay_required=True,delivery_approval=False)
    write_json(Path(root)/'provider-enablement.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--expect-calls',type=int,required=True);parser.add_argument('--expect-limit',type=int,required=True)
    args=parser.parse_args();print(json.dumps(enable(args.root,args.expect_calls,args.expect_limit),indent=2))
