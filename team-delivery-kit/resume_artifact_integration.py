"""Register a single changed-schema repair, preserving historical provenance."""
import json
import subprocess
import argparse
from evalctl import PRIVATE, PROJECT
from release_eval import save_receipt
from start_eval import read_model_budget


def build_payload(compact=False):
    if compact:
        probe=json.loads((PRIVATE/'provider-probes/acp-d3841241-6ec9-4de1-85e3-4c9e7a7bef98.json').read_text())
        return {'issue_id':'01a0fc34-fa97-70ce-bcdb-5c48b62fdb42',
            'source_task':'01a0fee8-f2ac-72b6-987c-01bf38c0f600','probe':probe,
            'failure':{'origin':'operator_verified_historical_proxy_metadata',
                'execution_id':'d520a7bc-7686-4a71-bda9-88e90f6754a1','call_number':2936,
                'status':502,'category':'invalid_response_encoding','selected_tool':'write_file',
                'completion_tokens':8192,'output_limit':8192,'finish_reason':'tool_calls'}}
    probe = json.loads((PRIVATE/'provider-probes/acp-07befdbb-9ddc-4518-a5c7-a83bd3299502.json').read_text())
    return {'issue_id':'01a0fc34-fa97-70ce-bcdb-5c48b62fdb42',
        'source_task':'01a0fed4-593a-7093-b561-9ef1339740b5', 'probe':probe,
        'failure':{'origin':'operator_verified_historical_proxy_metadata',
            'execution_id':'57b3c06e-e71a-4320-9351-297f6598bd09', 'call_number':2921,
            'status':502, 'category':'wrong_forced_arguments', 'selected_tool':'read_file'}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compact',action='store_true')
    args=parser.parse_args()
    if PROJECT != 'delivery-kit-port2' or read_model_budget()['remaining'] < 32:
        raise ValueError('isolated integration recovery reserve required')
    payload = build_payload(args.compact)
    script = '''import json,sys,urllib.request,urllib.error,hashlib
from pathlib import Path
p=json.load(sys.stdin)
r=urllib.request.Request('http://127.0.0.1:8090/v1/test-first-integration-recovery',data=json.dumps(p).encode(),headers={'Authorization':'Bearer '+Path('/broker-state/token').read_text(),'Content-Type':'application/json'})
try:
 d=json.load(urllib.request.urlopen(r,timeout=120))
 print(json.dumps({'registered':True,'repair_kind':d['repair_kind'],'source_task':d['request']['source_task'],'original_source':d['original_source'],'cto_task':d['cto_task'],'receipt_sha256':hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()}))
except urllib.error.HTTPError as e:
 body=json.loads(e.read(2048)); error=body.get('error','')
 allowed={'exact failed ACP execution binding required','preserved exact author workspace required',
 'exact failed transport recovery lineage required','preserved incident changed',
 'qualified installed scoped proxy required','changed qualified proxy required',
 'latest idle pre-tool provider failure required','preserved independent CTO sponsorship required',
 'blocked tests-only integration route required','integration repair requires idle workers',
 'integration repair forbidden after tool activity','test-first NEW test has no executable test methods'}
 print(json.dumps({'registered':False,'http_status':e.code,'category':error if error in allowed else 'unclassified_controller_rejection'}));sys.exit(1)
'''
    process = subprocess.run(['docker','exec','-i',PROJECT+'-execution-broker-1','python','-c',script],
                             input=json.dumps(payload),text=True,capture_output=True)
    if process.returncode:
        raise RuntimeError('integration repair rejected: '+process.stdout.strip())
    result = json.loads(process.stdout)
    save_receipt(PRIVATE/('artifact-compact-replan.json' if args.compact else 'artifact-integration-recovery.json'), result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
