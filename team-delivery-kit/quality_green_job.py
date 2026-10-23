"""Socketless fixed snapshot/full-suite job; no worker-supplied shell or paths."""
import json
import os
import signal
import sys
import quality_delivery_snapshot as snapshot
import quality_red_observation as observer
import quality_reversion_job as reversion


def request(raw):
    if not isinstance(raw,str) or len(raw.encode())>65536:raise ValueError('bounded fixed Green input required')
    value=json.loads(raw)
    common={'operation','plan','base_manifest_sha256'}
    fields={'snapshot_after_implementation_v2':{'reviewed_manifest_sha256','frozen_tests'},
        'observe_green_v2':{'task_id','snapshot_manifest_sha256','green_context'},
        'observe_reversion_v2':{'task_id','candidate_manifest_sha256','reviewed_manifest_sha256','evidence'}}
    if (not isinstance(value,dict) or not isinstance(value.get('operation'),str) or value['operation'] not in fields
            or set(value)!=common|fields[value['operation']]):raise ValueError('exact fixed Green input required')
    if value['operation']=='observe_green_v2' and not isinstance(value['green_context'],dict):
        raise ValueError('explicit Green evidence context required; no Red fallback')
    return value


def run(value):
    value=request(json.dumps(value))
    if value['operation']=='snapshot_after_implementation_v2':
        return snapshot.copy('/base','/reviewed','/workspace','/snapshot',value['plan'],
            value['base_manifest_sha256'],value['reviewed_manifest_sha256'],value['frozen_tests'])
    if value['operation']=='observe_reversion_v2':
        return reversion.run('/base','/candidate','/snapshot',value['plan'],value['task_id'],
            value['base_manifest_sha256'],value['candidate_manifest_sha256'],value['reviewed_manifest_sha256'],value['evidence'])
    return observer.run('/base','/snapshot',value['plan'],value['task_id'],
        value['base_manifest_sha256'],value['snapshot_manifest_sha256'],green_context=value['green_context'])


if __name__=='__main__':
    try:
        if len(sys.argv)!=1:raise ValueError('fixed Green job takes no commands')
        signal.alarm(180)
        result=run(request(os.environ['QUALITY_GREEN_JOB_JSON']))
        print(json.dumps(result,sort_keys=True),flush=True)
    except Exception as error:
        print(json.dumps(dict(operation='rejected_green_job_v2',category=getattr(error,'category',type(error).__name__),
            execution_authorized=False,delivery_approval=False)),flush=True)
        sys.exit(2)
