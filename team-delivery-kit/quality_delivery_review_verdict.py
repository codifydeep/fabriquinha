"""Strict final-review decoder and byte-bound citations, not provenance.

Only a controller may obtain messages from its durable ACP read stream. Passing
caller-supplied messages here never authenticates a reviewer or grants merge.
"""
import json
import re
from quality_review_verdict import require,VerdictRejected
try:
    from broker import quality_review_reads as reads,quality_lifecycle_v2 as quality
except ImportError:
    import quality_review_reads as reads,quality_lifecycle_v2 as quality
import quality_delivery_review_policy as policy


def instruction(plan,evidence,validation):
    bindings=dict(manifest_sha256=evidence['green']['manifest_sha256'],commit_sha=evidence['green']['commit_sha'],
        plan_sha256=quality.digest(plan),quality_evidence_sha256=quality.digest(evidence),validation_sha256=quality.digest(validation),
        criteria=list(plan['criteria']))
    return ('Return ONLY one JSON object with exactly action, reason, manifest_sha256, commit_sha, '
        'plan_sha256, quality_evidence_sha256, validation_sha256, criteria and findings. '
        'action must be approve_delivery, request_changes or escalate_cto. reason is nonblank and <=1200 characters. '
        'Inspect every registered snapshot file through actual read_file pages (offset>=1, limit<=100); no reading claims. '
        'The controller has already run your fixed validation; do not use shell or recreate Red. '
        'approve_delivery requires findings=[]. request_changes requires 1..8 concrete findings, each exactly '
        '{criterion,path,line,quote,expected,observed}: relative registered path, 1-based integer line, exact quoted '
        'text on that observed line, registered criterion, nonblank expected/observed <=500 characters. '
        'No extra fields, approval booleans or prior-phase decisions. Technical problems go to CTO, never CEO. '
        'Copy these exact snapshot/evidence bindings: '+json.dumps(bindings,sort_keys=True))


def parse(output,plan,evidence,validation):
    try:size=len(output.encode()) if isinstance(output,str) else 0
    except UnicodeError:size=0
    require(0<size<=16384,'output_type_or_size')
    text=output.strip();fence=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',text,re.I|re.S)
    if fence:text=fence.group(1)
    def unique(pairs):
        require(len({k for k,_ in pairs})==len(pairs),'duplicate_keys');return dict(pairs)
    def invalid(value):raise VerdictRejected('non_finite_json')
    try:value=json.loads(text,object_pairs_hook=unique,parse_constant=invalid)
    except (json.JSONDecodeError,RecursionError):raise VerdictRejected('invalid_json') from None
    fields={'action','reason','manifest_sha256','commit_sha','plan_sha256','quality_evidence_sha256',
        'validation_sha256','criteria','findings'}
    require(isinstance(value,dict) and set(value)==fields,'verdict_fields')
    require(value['action'] in ('approve_delivery','request_changes','escalate_cto'),'invalid_action')
    require(isinstance(value['reason'],str) and 0<len(value['reason'])<=1200 and bool(value['reason'].strip()),'invalid_reason')
    expected=dict(manifest_sha256=evidence['green']['manifest_sha256'],commit_sha=evidence['green']['commit_sha'],
        plan_sha256=quality.digest(plan),quality_evidence_sha256=quality.digest(evidence),validation_sha256=quality.digest(validation))
    require(all(value[k]==v for k,v in expected.items()),'snapshot_binding_mismatch')
    require(isinstance(value['criteria'],list) and all(isinstance(x,str) for x in value['criteria'])
        and len(value['criteria'])==len(set(value['criteria'])) and set(value['criteria'])==set(plan['criteria']),'criteria_mismatch')
    require(isinstance(value['findings'],list) and len(value['findings'])<=8,'invalid_findings')
    if value['action']=='approve_delivery':require(not value['findings'],'approval_has_findings')
    if value['action']=='request_changes':require(bool(value['findings']),'changes_require_concrete_findings')
    for finding in value['findings']:
        require(isinstance(finding,dict) and set(finding)=={'criterion','path','line','quote','expected','observed'}
            and finding['criterion'] in plan['criteria'] and isinstance(finding['path'],str)
            and type(finding['line']) is int and finding['line']>=1
            and all(isinstance(finding[k],str) and 0<len(finding[k])<=500 and bool(finding[k].strip())
                for k in ('quote','expected','observed')),'invalid_findings')
    return value


def inspect_reads(value,files,paths,messages):
    # Final review inspects the delivered candidate, not an author's mutable
    # workspace or a previous test-review stream. All paths must be byte-bound.
    observed=reads.observe(files,value['manifest_sha256'],paths,messages,include_content=True)
    for finding in value['findings']:
        path='/delivery/'+finding['path']
        require(path in observed,'finding_scope_invalid')
        line=observed[path]['line_content'].get(finding['line'])
        require(isinstance(line,str) and finding['quote'] in line,'finding_scope_invalid')
    return observed


def approval(plan,evidence,validation,value,observed):
    require(value['action']=='approve_delivery','invalid_action')
    require(observed and all(isinstance(v,dict) and 'line_content' in v for v in observed.values()))
    decision=dict(operation='independent_delivery_review_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
        contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),task_id=validation['task_id'],
        author=plan['author'],reviewer=plan['reviewer'],manifest_sha256=value['manifest_sha256'],commit_sha=value['commit_sha'],
        **{key+'_sha256':quality.digest(evidence[key]) for key in ('red','test_review','green','sensitivity')},
        validation_sha256=quality.digest(validation),decision='approve_delivery',criteria=value['criteria'],complete_reads=True,read_only=True)
    return decision,policy.qualify(plan,evidence,decision,validation)
