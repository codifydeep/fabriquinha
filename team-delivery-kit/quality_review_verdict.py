"""Pure strict verdict decoder shared by advisory worker and controller gates."""
import json
import re


def require(value):
    if not value:raise ValueError('exact native snapshot-bound test-review verdict required')


def parse(output,packet):
    require(isinstance(output,str) and 0<len(output.encode())<=16384)
    text=output.strip()
    fenced=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',text,re.I|re.S)
    if fenced:text=fenced.group(1)
    def unique(pairs):
        require(len({key for key,_ in pairs})==len(pairs));return dict(pairs)
    def invalid(value):raise ValueError('non-finite review verdict')
    value=json.loads(text,object_pairs_hook=unique,parse_constant=invalid)
    require(isinstance(value,dict) and set(value)=={'action','reason','manifest_sha256','plan_sha256',
        'red_sha256','criteria','findings'} and value['action'] in ('approve_tests','request_changes','escalate_cto')
        and isinstance(value['reason'],str) and 0<len(value['reason'])<=1200 and bool(value['reason'].strip())
        and all(value[key]==packet[key] for key in ('manifest_sha256','plan_sha256','red_sha256'))
        and isinstance(value['criteria'],list) and all(isinstance(item,str) for item in value['criteria'])
        and len(value['criteria'])==len(set(value['criteria']))
        and set(value['criteria'])==set(packet['plan']['criteria'])
        and isinstance(value['findings'],list) and len(value['findings'])<=8)
    if value['action']=='approve_tests':require(not value['findings'])
    if value['action']=='request_changes':require(bool(value['findings']))
    return value


def required_reads(value,packet,paths):
    if value['action']!='request_changes':return paths
    cited=[]
    for finding in value['findings']:
        require(isinstance(finding,dict) and isinstance(finding.get('path'),str))
        path='/delivery/'+finding['path'];require(path in paths);cited.append(path)
    return sorted(set(cited)|{'/delivery/'+p for p in packet['plan']['new_tests']})
