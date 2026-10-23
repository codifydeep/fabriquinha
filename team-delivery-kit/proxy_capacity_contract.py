"""Pure capacity-probe facts shared by host and controller; no authority."""
import hashlib
import json
import math
import re


def require(value):
    if not value:raise ValueError('exact bounded proxy capacity evidence required')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_report(report,source):
    require(isinstance(source,str) and re.fullmatch('[a-f0-9]{64}',source)
        and isinstance(report,dict) and report.get('operation')=='real_http_proxy_capacity_canary_v1'
        and report.get('status')=='passed' and report.get('source_sha256')==source
        and report.get('max_request_bytes')==2097152 and type(report.get('max_request_bytes')) is int
        and report.get('fixed_forwards')==2 and report.get('fixture_max_calls')==2 and report.get('fixture_calls')==2
        and report.get('model_calls')==0 and type(report.get('model_calls')) is int
        and report.get('oversized_rejected') is True and report.get('call_ceiling_preserved') is True
        and report.get('counter_preserved') is True and report.get('credentials_mounted') is False
        and report.get('docker_socket') is False and report.get('network')=='none' and report.get('data_tmpfs') is True
        and report.get('tests_approved') is False and report.get('delivery_approval') is False)
    sizes=report.get('accepted_request_bytes')
    require(isinstance(sizes,list) and len(sizes)==2 and all(type(n) is int for n in sizes)
        and 600000<sizes[0]<700000 and 2096128<sizes[1]<=2097152)
    return report


def rejection(event,request):
    fields={'event','status','category','call_number','route','execution_id','started_at',
        'duration_seconds','response_deadline_seconds'}
    require(isinstance(event,dict) and set(event)==fields and event['event']=='model_proxy_request'
        and event['execution_id']==request and event['status']==400 and type(event['status']) is int
        and event['category']=='request body size limit' and event['call_number'] is None
        and event['route']=='/api/v1/chat/completions' and event['response_deadline_seconds']==120
        and type(event['started_at']) in (int,float) and math.isfinite(event['started_at']) and event['started_at']>0
        and type(event['duration_seconds']) in (int,float) and math.isfinite(event['duration_seconds'])
        and 0<=event['duration_seconds']<=120)
    return event
