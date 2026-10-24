"""Pure strict verdict decoder shared by advisory worker and controller gates."""
import json
import re

CATEGORIES=frozenset(('output_type_or_size','invalid_json','duplicate_keys','non_finite_json',
    'verdict_fields','invalid_action','invalid_reason','snapshot_binding_mismatch',
    'criteria_mismatch','invalid_findings','approval_has_findings','changes_require_concrete_findings',
    'finding_scope_invalid','invalid_verdict'))


class VerdictRejected(ValueError):
    """Only fixed categories leave the parser; no rejected values or prose."""
    def __init__(self,category):
        if category not in CATEGORIES:raise ValueError('fixed review rejection category required')
        self.category=category
        super().__init__('exact native snapshot-bound test-review verdict required')


def rejection_category(error):
    return error.category if isinstance(error,VerdictRejected) else 'invalid_verdict'


def require(value,category='finding_scope_invalid'):
    if not value:raise VerdictRejected(category)


def parse(output,packet):
    try:size=len(output.encode()) if isinstance(output,str) else 0
    except UnicodeError:size=0
    require(0<size<=16384,'output_type_or_size')
    text=output.strip()
    fenced=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',text,re.I|re.S)
    if fenced:text=fenced.group(1)
    def unique(pairs):
        require(len({key for key,_ in pairs})==len(pairs),'duplicate_keys');return dict(pairs)
    def invalid(value):raise VerdictRejected('non_finite_json')
    try:value=json.loads(text,object_pairs_hook=unique,parse_constant=invalid)
    except (json.JSONDecodeError,RecursionError):raise VerdictRejected('invalid_json') from None
    require(isinstance(value,dict) and set(value)=={'action','reason','manifest_sha256','plan_sha256',
        'red_sha256','criteria','findings'},'verdict_fields')
    require(value['action'] in ('approve_tests','request_changes','escalate_cto'),'invalid_action')
    require(isinstance(value['reason'],str) and 0<len(value['reason'])<=1200 and bool(value['reason'].strip()),'invalid_reason')
    require(all(value[key]==packet[key] for key in ('manifest_sha256','plan_sha256','red_sha256')),'snapshot_binding_mismatch')
    require(isinstance(value['criteria'],list) and all(isinstance(item,str) for item in value['criteria'])
        and len(value['criteria'])==len(set(value['criteria']))
        and set(value['criteria'])==set(packet['plan']['criteria']),'criteria_mismatch')
    require(isinstance(value['findings'],list) and len(value['findings'])<=8,'invalid_findings')
    if value['action']=='approve_tests':require(not value['findings'],'approval_has_findings')
    if value['action']=='request_changes':require(bool(value['findings']),'changes_require_concrete_findings')
    return value


def required_reads(value,packet,paths):
    if value['action']!='request_changes':return paths
    cited=[]
    for finding in value['findings']:
        require(isinstance(finding,dict) and isinstance(finding.get('path'),str))
        path='/delivery/'+finding['path'];require(path in paths);cited.append(path)
    return sorted(set(cited)|{'/delivery/'+p for p in packet['plan']['new_tests']})
