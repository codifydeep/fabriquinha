"""Real worker registry canary, with a stubbed controller and no native/model run."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from docker_grouping import args
from generic_harness_calibration import digest,require
from qualify_frozen_harness import private_json,private_bytes,docker

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image',required=True)
    parser.add_argument('--namespace',required=True);options=parser.parse_args()
    require(bool(re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',options.namespace))
        and bool(re.fullmatch('sha256:[a-f0-9]{64}',options.image)))
    require(json.loads(docker('image','inspect',options.image,'--format','{{json .Id}}'))==options.image)
    script=ROOT/'tests/author_feedback_worker_probe.py'
    sources={name:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for name,path in
        (('client','broker/author_feedback_client.py'),('policy','broker/review_tool_policy.py'),
         ('wire','literal_feedback_wire.py'),('formatter','broker/patch_receipt_contract.py'))}
    identity=dict(image=options.image,namespace=options.namespace,source_sha256=sources,
        probe_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),qualifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    key=digest(identity);folder=ROOT/'.local-port2/probes'/('author-feedback-worker-'+key)
    folder.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    def validate(value):
        require(value['identity']==identity);proof=value['proof']
        require(proof['operation']=='author_feedback_real_registry_canary_v1' and proof['status']=='passed'
            and proof['uid']==10000 and proof['network']=='none' and proof['source_sha256']==sources
            and proof['controller_transport_stubbed'] is True and proof['native_execution'] is False
            and proof['delivery_approval'] is False and proof['full_regression_suite_executed'] is False
            and type(proof['model_calls']) is int and proof['model_calls']==0)
        require(all(proof[k] is True for k in ('real_registry','direct_handler_fenced','readless_patch_denied',
            'assertion_edit_denied','shell_and_generic_write_denied','literal_edit_preserves_outside_bytes',
            'current_hash_returned','feedback_visible_in_acp_formatter','fresh_read_required_after_patch',
            'virtual_feedback_observation','wrong_mode_denied')))
        return value
    if folder.exists():
        if (folder/'receipt.json').is_file():print(json.dumps(validate(json.loads((folder/'receipt.json').read_text()))));return
        raise ValueError('existing canary intent; observe its exact handle, never replay automatically')
    folder.mkdir(mode=0o700);name=options.namespace+'-feedback-worker-'+key[:20]
    private_json(folder/'intent.json',dict(identity=identity,name=name,started=time.time(),delivery_approval=False))
    command=['docker','run','--rm','--name',name,*args('author-feedback-worker',options.namespace),
        '--network','none','--read-only','--cap-drop','ALL','--cap-add','SETUID','--cap-add','SETGID',
        '--security-opt','no-new-privileges','--memory','512m','--cpus','1','--pids-limit','64','--user','0:0',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=128m,mode=1777','--tmpfs','/workspace:rw,nosuid,nodev,size=1m,mode=1777',
        '-e','PYTHONDONTWRITEBYTECODE=1','-v',str(script)+':/probe.py:ro',
        '--entrypoint','/opt/hermes/.venv/bin/python',options.image,'-B','/probe.py']
    try:result=subprocess.run(command,capture_output=True,timeout=90)
    except subprocess.TimeoutExpired:
        private_json(folder/'observation.json',dict(category='ack_uncertain',handle=name,delivery_approval=False));raise
    private_bytes(folder/'stdout.log',result.stdout);private_bytes(folder/'stderr.log',result.stderr)
    require(hashlib.sha256(script.read_bytes()).hexdigest()==identity['probe_sha256'])
    require(result.returncode==0 and 0<len(result.stdout)<=16384 and not result.stderr)
    receipts=[json.loads(line) for line in result.stdout.decode().splitlines() if line.startswith('{')]
    proof=next(v for v in receipts if v.get('operation')=='author_feedback_real_registry_canary_v1')
    value=validate(dict(operation='qualified_author_feedback_worker_v1',identity=identity,proof=proof,
        delivery_approval=False,native_execution=False))
    private_json(folder/'receipt.json',value);print(json.dumps(value,sort_keys=True))


if __name__=='__main__':main()
