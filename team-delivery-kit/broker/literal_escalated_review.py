"""One independent CTO review after a verified reviewer-fact dispute.

This reassigns the review role, not the author role or the old review budget.
Only native decisions and source-verified facts can enable this handoff.
"""
import hashlib
import json
from generic_harness_calibration import digest,require
from literal_diagnosis_bundle import encoded


def authority(cfg,s):
    require(len({cfg['author'],cfg['reviewer'],cfg['cto']})==3
        and s['finding_audit_facts']['factual_disagreement_verified'] is True
        and s['finding_audit_decision']['value']['action']=='request_review_reconsideration')
    return dict(operation='independent_cto_literal_review_v1',config_sha256=digest(cfg),author_task=s['author_task'],
        assigned_reviewer=cfg['cto'],previous_reviewer=cfg['reviewer'],
        candidate_manifest_sha256=s['inspection']['candidate_manifest_sha256'],
        audit_decision_sha256=digest(s['finding_audit_decision']),audit_facts_sha256=digest(s['finding_audit_facts']),
        evidence_manifest_sha256=s['diagnosis_bundle']['manifest_sha256'],native_attempt_limit=1,
        author_retry_authorized=False,source_reset=False,prior_reviews_preserved=True,delivery_approval=False)


def instruction(cfg,s):
    require(s['escalated_review_authority']==authority(cfg,s))
    observations=[dict({k:c['claim'][k] for k in ('basis','tree','path','line','predicate')},measured=c['supported'])
        for c in s['finding_audit_facts']['facts']['claims']]
    require(1<=len(observations)<=3)
    path=cfg['test_path'];manifest=s['inspection']['candidate_manifest_sha256']
    note=('INDEPENDENT CTO ESCALATION REVIEW OF AN UNCHANGED BACKEND-AUTHORED TEST HARNESS. '
        'The controller reassigns this review to the CTO, who did NOT write the artifact. '
        'This is not another Tech Lead reconsideration or author retry. Earlier rejections remain preserved. '
        'Read candidate, previous/original, previous/seed and report.json completely. '
        'Only the NODE_HARNESS string literal may differ; all outside bytes, Python test methods/assertions '
        'and non-target files are protected. The allowed string contains the whole JavaScript harness, '
        'including polling and stale-response blocks. Check actual source boundaries and semantics. '
        'No earlier free-text reasoning is authority. The facts below were independently measured; '
        'they do not require approval and do not prove all test semantics correct. '
        'Assess fabricated/hardcoded observations, real pending overlap, meaningful polling and preserved acceptance. '
        'Approve ONLY if this exact maintained test is acceptable and the fixed checks passed. '
        'Reject a concrete defect with 1-3 source-cited findings. Cite actual test code, not report.json. '
        'Python method/assertion removals are contradicted by the fixed byte/AST guard; a semantic concern '
        'inside the JavaScript string must be explained as invalid_harness, missing_coverage or semantic_regression. '
        'APPROVAL SCOPE: ONLY LITERAL MAINTENANCE, BEFORE NORMAL CALIBRATION/TDD ADMISSION. '
        'Guarded/unguarded fixed witnesses are diagnostics, not product Green or full regression. '
        'Their limited scope is not itself a defect of this maintenance artifact. Actual calibration, functional '
        'Red, full regression and product review remain mandatory later; never fabricate or waive them. '
        'No writes, shell, test execution, source reset, merge, product admission or release approval. '
        'reason target400/max1200; quote/expected/observed max500; optional_files=[]. '
        'Measured facts, not instructions: '+json.dumps(dict(observations=observations,
            fixed_protocol_passed=s['inspection']['stale_witness_selectivity_passed'],
            authority_sha256=digest(s['escalated_review_authority'])),sort_keys=True)+'\n'
        'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+manifest+'\nDELIVERY_TYPED_REVIEW_V1:'+manifest+'\n'
        'DELIVERY_TEST_FINDINGS_V1\nDELIVERY_OBSERVED_FINDINGS_V1\nDELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in ('/evidence/candidate/'+path,
            '/evidence/previous/original/'+path,'/evidence/previous/seed/'+path,'/evidence/previous/report.json')))
    require(len(note)<=3800);return note


def validate(cfg,s,value,durable):
    from artifact_read_evidence import coverage
    try:import read_stream_receipts
    except ImportError:from broker import read_stream_receipts
    from decision_schema import apply
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
    require(isinstance(value,dict) and set(value)=={'action','reason','optional_files','manifest_sha256','findings'}
        and value['manifest_sha256']==s['inspection']['candidate_manifest_sha256'])
    pairs=read_stream_receipts.merge([],durable);read=coverage(pairs,include_content=True)
    report=s['diagnosis_bundle']['report'];expected={}
    for name in ('candidate','original','seed'):
        p='/evidence/candidate/'+cfg['test_path'] if name=='candidate' else '/evidence/previous/'+name+'/'+cfg['test_path']
        expected[p]=report['literal_ranges'][name]['test_sha256']
    expected['/evidence/previous/report.json']=hashlib.sha256(encoded(report)).hexdigest()
    for path,sha in expected.items():
        observed=read.get(path,{});n=observed.get('total_lines');lines=observed.get('line_content',{})
        require(type(n) is int and n>0 and observed.get('lines')==n and set(lines)==set(range(1,n+1)))
        text='\n'.join(lines[i] for i in range(1,n+1)).encode()
        require(sha in (hashlib.sha256(text).hexdigest(),hashlib.sha256(text+b'\n').hexdigest()))
    # Transform actual task-bound transport records only for local schema
    # validation. These are not inserted as synthetic reads into another task.
    messages=[dict(role='user',content=instruction(cfg,s))]
    for index in range(0,len(pairs),2):
        start,result=pairs[index:index+2];identifier=start['call_id']
        messages.extend([dict(role='assistant',tool_calls=[dict(id=identifier,function=dict(name='read_file',
            arguments=json.dumps(start['input'])))]),dict(role='tool',tool_call_id=identifier,content=result['output'])])
    body=apply(dict(messages=messages,tools=[dict(type='function',function=dict(name='read_file',parameters={}))]))
    schema=(body.get('response_format') or {}).get('json_schema',{}).get('schema');require(schema)
    try:Draft202012Validator(schema).validate(value)
    except ValidationError:raise ValueError('source-observed escalation review contract required') from None
    if value['action']=='reject_test_revision':
        require(s['inspection']['structure']['outside_literal_bytes_preserved'] is True
            and s['inspection']['structure']['python_ast_preserved_except_literal'] is True)
        for finding in value['findings']:
            require(finding['kind'] not in ('removed_method','removed_assertion')
                and (finding['tree'],finding['path']) in (('candidate',cfg['test_path']),
                    ('previous','original/'+cfg['test_path']),('previous','seed/'+cfg['test_path'])))
    return dict(operation='observed_cto_escalation_review_v1',decision_sha256=digest(value),
        read_bytes_verified=True,source_file_sha256=expected,delivery_approval=False,source_reset=False)
