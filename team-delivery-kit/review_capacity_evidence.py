"""Read-only private installation/log proof for one failed review request.

No receipt is invented from agent prose or a generic 400. The archived proxy,
legacy source constant, exact local admission rejection and unchanged meter
must agree. This reader does not register recovery or contact the provider.
"""
import json
import re
from pathlib import Path
from install_model_proxy_capacity import qualified,private_digest,environment,old_capacity,counter_receipt
from migrate_quality_candidate_pin import read
from proxy_capacity_contract import require,rejection
from qualify_quality_review_stop import sha
from quality_git_candidate import canonical

ROOT=Path(__file__).resolve().parent


def load(namespace,operation,maintenance,request):
    require(isinstance(namespace,str) and re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace))
    for value in (operation,maintenance,request):canonical(value)
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('model-proxy-install-'+operation)
    state=json.loads(read(archive/'state.json'));receipt=state['receipt'];before=json.loads(read(archive/'before.json'))
    require(state['stage']=='installed_stopped' and state['namespace']==namespace and state['operation']==operation
        and state['maintenance_operation']==maintenance and receipt['namespace']==namespace
        and receipt['install_operation']==operation and receipt['maintenance_operation']==maintenance
        and receipt['current_image']==state['image'] and receipt['previous_image']==before['Image']
        and receipt['previous_container']==before['Id'] and receipt['model_calls']==0
        and receipt['delivery_approval'] is False and receipt['maintenance_sealed'] is True)
    require(qualified(namespace,state['qualification_id'],maintenance,state['image'])==receipt['qualification'])
    program=read(archive/'previous-model_proxy.py')
    require(sha(program)==receipt['previous_source_sha256']
        and old_capacity(program,environment(before))==receipt['previous_capacity']==524288)
    prior=counter_receipt(read(archive/'counter-before.json'));current=counter_receipt(read(archive/'counter-after.json'))
    require(prior==current==receipt['counter'] and int(environment(before)['MODEL_PROXY_MAX_CALLS'])==receipt['max_calls'])
    path=archive/'previous-proxy-logs.json'
    require(private_digest(path)==receipt['previous_logs_sha256'])
    logs=json.loads(path.read_bytes());require(logs['container_id']==receipt['previous_container'])
    events=[]
    for line in (logs['stdout']+'\n'+logs['stderr']).splitlines():
        # Docker --timestamps prefixes the unmodified JSON event with one token.
        raw=line if line.startswith('{') else line.partition(' ')[2]
        try:event=json.loads(raw)
        except ValueError:continue
        if isinstance(event,dict) and event.get('event')=='model_proxy_request' and event.get('execution_id')==request:
            events.append(event)
    matching=[event for event in events if event.get('category')=='request body size limit']
    require(len(matching)==1);event=rejection(matching[0],request)
    require(not any(e.get('status')==200 and e.get('started_at',0)>=event['started_at'] for e in events))
    return dict(operation='observed_proxy_capacity_change_v1',installation=receipt,rejection=event)
