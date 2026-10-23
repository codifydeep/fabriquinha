"""Fixed operator-local Docker-exec verbs, not an HTTP/worker tool endpoint.

No model input, command execution, credential output, dispatch or approval.
Recording is conditional/idempotent on the exact capture and verified proof;
after a lost reply the host inspects the durable row before any local effects.
"""
import json
try:
    from . import quality_candidate_binding as binding
except ImportError:
    import quality_candidate_binding as binding

require=binding.require


def invoke(b,value):
    require(isinstance(value,dict) and isinstance(value.get('operation'),str))
    fields={'about':set(),'inspect':{'request_id'},'record':{'request_id','packet','repository','candidate'}}
    action=value['operation'];require(action in fields and set(value)=={'operation','namespace'}|fields[action]
        and value['namespace']==b.PREFIX and b.OWNER==b.PREFIX+'-broker-v1')
    with b.db() as con:paused=binding.maintenance.current(con) is not None
    if action=='about':
        return dict(operation='quality_candidate_local_rpc_v2',namespace=b.PREFIX,stage='available',
            v2_enabled=getattr(b,'QUALITY_V2_ENABLED',False) is True,
            implementation_enabled=getattr(b,'QUALITY_IMPLEMENTATION_ENABLED',False) is True,
            maintenance=paused,execution_authorized=False,delivery_approval=False)
    binding.delivery.admission.enabled(b)
    binding.delivery.admission.enrollment.canonical(value['request_id'])
    if paused:return dict(operation='quality_candidate_local_rpc_v2',namespace=b.PREFIX,stage='maintenance',delivery_approval=False)
    if action=='record':
        binding.record(b,value['request_id'],value['packet'],value['repository'],value['candidate'])
    previous=binding.load(b,value['request_id'])
    if previous:
        identity,receipt=previous
        return dict(operation='quality_candidate_local_rpc_v2',namespace=b.PREFIX,stage='bound',
            identity=identity,receipt=receipt,delivery_approval=False)
    require(action=='inspect')
    return dict(operation='quality_candidate_local_rpc_v2',namespace=b.PREFIX,stage='pending',
        packet=binding.delivery.candidate_packet(b,value['request_id']),delivery_approval=False)


def invoke_json(b,raw):
    require(isinstance(raw,str) and 0<len(raw.encode())<=262144)
    def unique(pairs):
        require(len({key for key,_ in pairs})==len(pairs));return dict(pairs)
    def invalid(_):raise ValueError('nonfinite local RPC input')
    value=invoke(b,json.loads(raw,object_pairs_hook=unique,parse_constant=invalid))
    require(len(json.dumps(value).encode())<=262144)
    return value
