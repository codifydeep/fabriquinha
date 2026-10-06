"""Narrow output contracts; never grants execution or approval authority."""
import re
import json
from artifact_read_evidence import observations, next_read

MARKER = 'DELIVERY_STRUCTURED_DECISION_V1'


def validation_schema(sha):
    props={'operation':{'type':'string','enum':['run_fixed_deployment_qa']},
        'evidence_sha256':{'type':'string','enum':[sha]},'reason':{'type':'string','minLength':1,'maxLength':600},
        'release_homologated':{'type':'boolean','enum':[False]},
        'product_admission_authorized':{'type':'boolean','enum':[False]}}
    return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}


def apply(body):
    from work_proposal_contract import apply as work_proposal
    proposal = work_proposal(body)
    if proposal is not None: return proposal
    validations={v for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^DELIVERY_DEPLOYMENT_VALIDATION_V1:([a-f0-9]{64})$',m['content'],re.M)}
    if validations:
        if len(validations)!=1 or any(re.search(r'^DELIVERY_(?:STRUCTURED_DECISION|DEPLOYMENT_EVIDENCE)_V1',
                str(m.get('content','')),re.M) for m in body['messages']):raise ValueError('conflicting fixed QA request contracts')
        body['tools']=[];body['tool_choice']='none'
        body['response_format']={'type':'json_schema','json_schema':{'name':'delivery_deployment_validation_v1',
            'strict':True,'schema':validation_schema(next(iter(validations)))}}
        body['provider']={**(body.get('provider') or {}),'require_parameters':True}
        return body
    deployment={v for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^DELIVERY_DEPLOYMENT_EVIDENCE_V1:([a-f0-9]{64})$',m['content'],re.M)}
    if deployment:
        if len(deployment)!=1 or any(MARKER+':' in str(m.get('content','')) for m in body['messages']):
            raise ValueError('conflicting deployment evidence contracts')
        props={'decision':{'type':'string','enum':['ACCEPT_EVIDENCE','REQUEST_CHANGES']},
            'evidence_sha256':{'type':'string','enum':[next(iter(deployment))]},
            'reason':{'type':'string','minLength':1,'maxLength':1200},
            'limitations':{'type':'array','minItems':1,'maxItems':6,
                'items':{'type':'string','minLength':1,'maxLength':300}},
            **{k:{'type':'boolean','enum':[False]} for k in ('release_homologated','product_admission_authorized','historical_tdd_red')}}
        body['tools']=[];body['tool_choice']='none'
        body['response_format']={'type':'json_schema','json_schema':{'name':'delivery_deployment_evidence_v1',
            'strict':True,'schema':{'type':'object','properties':props,'required':list(props),'additionalProperties':False}}}
        body['provider']={**(body.get('provider') or {}),'require_parameters':True}
        body['messages'].append({'role':'system','content':'Return only the exact JSON schema. '
            'reason target <=600 characters, hard limit1200. No tools or executed-action claims. '
            'Evidence assessment is not independent QA execution or release approval.'})
        return body
    from planning_schema import apply as apply_planning
    planning = apply_planning(body)
    if planning is not None:
        return planning
    markers = set()
    for message in body['messages']:
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, list):
            content = '\n'.join(p.get('text', '') for p in content
                                if isinstance(p, dict) and p.get('type') == 'text')
        if isinstance(content, str):
            markers.update(re.findall(r'^' + MARKER + r':(technical|qa|test_review:[a-f0-9]{64})$',
                                      content, re.MULTILINE))
    if not markers:
        return body
    if len(markers) != 1:
        raise ValueError('conflicting structured decision contracts')
    mode = markers.pop()
    finding_policy = any(message.get('role') == 'user' and
        re.search(r'^DELIVERY_TEST_FINDINGS_V1$',
            message.get('content') if isinstance(message.get('content'), str) else
            '\n'.join(p.get('text', '') for p in (message.get('content') or []) if isinstance(p, dict)), re.MULTILINE)
        for message in body['messages'])
    capture_policy = any(message.get('role') == 'user' and
        re.search(r'^DELIVERY_CAPTURE_CONSTRAINTS_V1$',
            message.get('content') if isinstance(message.get('content'), str) else
            '\n'.join(p.get('text', '') for p in (message.get('content') or []) if isinstance(p, dict)), re.MULTILINE)
        for message in body['messages'])
    if mode.startswith('test_review:') or mode in ('technical','qa'):
        paths = set()
        for message in body['messages']:
            if message.get('role') == 'user':
                content = message.get('content', '')
                if isinstance(content, list):
                    content = '\n'.join(p.get('text', '') for p in content if isinstance(p, dict))
                paths.update(re.findall(r'^DELIVERY_REVIEW_READ_PATH:(/evidence/(?:candidate|previous)/[A-Za-z0-9_./-]+)$', content, re.MULTILINE))
        if ((mode.startswith('test_review:') or mode == 'qa') and not paths) or any('/../' in p for p in paths):
            raise ValueError('review read contract missing')
        missing = sorted(paths - observations(body['messages'], wire=True).keys())
        if missing:
            page_size = 60 if mode == 'qa' else 100
            offset = next_read(body['messages'], missing[0])
            tools = body.get('tools') or []
            if not any(t.get('function', {}).get('name') == 'read_file' for t in tools):
                raise ValueError('review read tool unavailable')
            # Pin the selected page in the function schema too: a request to
            # read is not permission to choose a different file or region.
            body['tools'] = [{**tool, 'function': {**tool['function'], 'strict':True, 'parameters': {
                'type': 'object', 'properties': {
                    'path': {'type': 'string', 'enum': [missing[0]]},
                    'offset': {'type': 'integer', 'enum': [offset]},
                    'limit': {'type': 'integer', 'enum': [page_size]}},
                'required': ['path', 'offset', 'limit'], 'additionalProperties': False}}}
                if tool.get('function', {}).get('name') == 'read_file' else tool for tool in tools]
            body.pop('response_format', None)
            body['tool_choice'] = {'type': 'function', 'function': {'name': 'read_file'}}
            body['messages'].append({'role': 'system', 'content':
                'INSPECTION PHASE: read_file path=' + missing[0] +
                ', offset=' + str(offset) + ', limit=' + str(page_size) + '. Obtain this numbered page; '
                'do not repeat previously read pages. '
                'Do not decide or describe imaginary files. Decision phase opens only after all required reads.'})
            return body
        if paths:
            body['tool_choice'] = 'none'
            size_instruction = (
                'For root_cause aim below 600 characters; 1000 characters is the hard limit. '
                'Explain only the causal chain and decisive observation; do not repeat SHA, '
                'HTML excerpts, every stack frame or the full experiment in this field. '
                if mode == 'qa' else
                'State one concrete finding and next action in a complete sentence, '
                'aim below 900 characters; the 1200-character schema is a hard limit, '
                'not a target. ')
            reads = observations(body['messages'], wire=True)
            summary = [{'path': path, 'lines': reads[path]['total_lines'],
                        'output_sha256': reads[path]['output_sha256']} for path in sorted(paths)]
            body['messages'].append({'role': 'system', 'content':
                'DECISION PHASE: required artifact reads completed successfully. '
                'The temporary tool_choice=none now prevents more tools; it does NOT '
                'mean read_file was unavailable during inspection. Verified read receipts: '
                + json.dumps(summary, sort_keys=True) + '. '
                'Use actual observed contents, not a prior failed read, as evidence. '
                'Do not invent syntax or test-execution failures. Distinct initial and '
                'pending observations can correctly have different values. '
                + size_instruction + 'If rejecting, distinguish missing coverage from an '
                'infrastructure failure. Never interpret a blocked operation as a '
                'broken delivery or override an earlier independent rejection.'})
    properties = {
        'action': {'type': 'string', 'enum': ['request_correction', 'request_test_revision', 'escalate_cto']},
        'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1200},
        'optional_files': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0}}
    versions={v for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^DELIVERY_TEST_DECOMPOSITION_(V[12])$',m['content'],re.M)}
    if len(versions)>1:raise ValueError('conflicting decomposition versions')
    decomposition = mode == 'technical' and bool(versions)
    if decomposition:
        criteria=sorted(set(c for m in body['messages'] if m.get('role')=='user'
            and isinstance(m.get('content'),str)
            for c in re.findall(r'^DELIVERY_DECOMPOSITION_CRITERION:(C\d{2})$',m['content'],re.M)))
        if not 1<=len(criteria)<=32:raise ValueError('decomposition criteria contract required')
        properties['action']['enum']=['propose_test_decomposition','escalate_cto']
        properties['units']={'type':'array','minItems':0,'maxItems':4,'items':{
            'type':'object','properties':{
                'id':{'type':'string','enum':['U1','U2','U3','U4']},
                'depends_on':{'type':'array','maxItems':1,'items':{'type':'string','enum':['U1','U2','U3']}},
                'criteria':{'type':'array','minItems':1,'maxItems':32,'items':{'type':'string','enum':criteria}},
                'objective':{'type':'string','minLength':1,'maxLength':300}},
            'required':['id','depends_on','criteria','objective'],'additionalProperties':False}}
        if versions=={'V2'}:
            unit=properties['units']['items']
            del unit['properties']['criteria'];unit['required'].remove('criteria')
            properties['assignments']={'type':'object','properties':{
                c:{'type':'string','enum':['U1','U2','U3','U4']} for c in criteria},
                'required':criteria,'additionalProperties':False}
            body['messages'].append({'role':'system','content':
                'ALLOCATION CONTRACT V2: assignments MUST contain EVERY criterion ID exactly once, '
                'including governance and acceptance criteria, mapped to an existing unit ID. '
                'Units contain only id, depends_on and objective; no criteria arrays. '
                'No criteria may be omitted, auto-filled or waived. This is a proposal, not execution authority.'})
    semantic_policy = mode == 'technical' and any(m.get('role') == 'user' and
        re.search(r'^DELIVERY_SEMANTIC_CHECKS_V1$', m.get('content') or '', re.MULTILINE)
        for m in body['messages'] if isinstance(m.get('content'), str))
    if semantic_policy:
        properties['action']['enum'] = ['request_test_revision', 'escalate_cto']
        properties['experiment_sha256'] = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
        properties['semantic_checks'] = {'type': 'array', 'minItems': 1, 'maxItems': 16,
            'items': {'type': 'object', 'properties': {
                'fact_index': {'type': 'integer', 'minimum': 0, 'maximum': 15},
                'casefold_substring': {'type': 'boolean'}},
                'required': ['fact_index', 'casefold_substring'], 'additionalProperties': False}}
    runtime_repair = mode == 'technical' and any(m.get('role') == 'user' and
            re.search(r'^DELIVERY_EXECUTION_REPAIR_V1$', m.get('content') or '', re.MULTILINE)
            for m in body['messages'] if isinstance(m.get('content'), str))
    execution_diagnosis = mode == 'technical' and any(m.get('role') == 'user' and
            re.search(r'^DELIVERY_EXECUTION_DIAGNOSIS_V1$', m.get('content') or '', re.MULTILINE)
            for m in body['messages'] if isinstance(m.get('content'), str))
    if runtime_repair or execution_diagnosis:
        properties['action']['enum'] = ['retry_author', 'escalate_cto'] if runtime_repair else ['escalate_cto']
        body.pop('tools', None)
        body.pop('tool_choice', None)
        body.pop('parallel_tool_calls', None)
        body['messages'].append({'role': 'system', 'content':
            'RUNTIME DECISION PHASE: all controller-verified evidence is already supplied. '
            'No tools are available or necessary. Output ONLY a standalone JSON object '
            'with action, reason (<=1200 characters) and optional_files=[]. '
            'No preface, analysis, Markdown or code fences. This is not a delivery approval.'})
    if mode.startswith('test_review:'):
        properties['action']['enum'] = ['approve_test_revision', 'reject_test_revision']
        properties['manifest_sha256'] = {'type': 'string', 'enum': [mode.split(':', 1)[1]]}
    if capture_policy and mode == 'technical':
        properties['action']['enum'] = ['request_test_revision', 'escalate_cto']
        properties['capture_resolutions'] = {'type': 'array', 'minItems': 1, 'maxItems': 3,
            'items': {'type': 'object', 'additionalProperties': False,
                'properties': {
                    'path': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                    'capture': {'type': 'string', 'minLength': 1, 'maxLength': 100},
                    **{key: {'type': 'integer', 'minimum': 1} for key in ('whole_line', 'element_line', 'line')},
                    'lifetime': {'type': 'string', 'enum': ['shared', 'unknown']},
                    'quote': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
                'required': ['path', 'capture', 'whole_line', 'element_line', 'lifetime', 'line', 'quote']}}
        body['messages'].append({'role': 'system', 'content':
            'Resolve every controller capture witness. Shared observations require a NEW test '
            'revision with unchanged baseline and independent review, not product edits. Unknown '
            'lifetime requires escalate_cto. Cite source evidence of observation lifetime. '
            'This decision is not an approval or permission to modify frozen tests.'})
    if finding_policy and (mode.startswith('test_review:') or mode == 'technical'):
        properties['findings'] = {'type': 'array', 'maxItems': 3, 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'kind': {'type': 'string', 'enum': ['removed_method', 'removed_assertion', 'semantic_regression', 'missing_coverage', 'invalid_harness']},
                'tree': {'type': 'string', 'enum': ['candidate', 'previous']},
                'path': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                'test': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                'line': {'type': 'integer', 'minimum': 1},
                **{k: {'type': 'string', 'minLength': 1, 'maxLength': 500} for k in ('quote', 'expected', 'observed')}},
            'required': ['kind', 'tree', 'path', 'test', 'line', 'quote', 'expected', 'observed']}}
        body['messages'].append({'role': 'system', 'content':
            'EVIDENCE FINDINGS: approval requires findings=[]. Rejection or test revision requires 1-3 findings. '
            'Use an actual repository-relative test path, observed test symbol (or __module__ for module/harness), '
            'exact numbered source line and a real quote substring from that line. State expected and observed '
            'behavior separately. Removed methods/assertions must match controller diff. '
            'A narrow byte margin, stylistic preference or unverified historical allegation is not a regression.'})
    if mode == 'qa':
        properties = {
            'decision': {'type':'string','enum':['repair','blocked']},
            'root_cause': {'type':'string','minLength':1,'maxLength':1000},
            'editable_code_files': {'type':'array','maxItems':8,
                                    'items':{'type':'string','maxLength':200}},
            'new_test_file': {'type':'string','maxLength':200},
            'acceptance': {'type':'array','maxItems':5,
                           'items':{'type':'string','minLength':1,'maxLength':300}}}
        body['messages'].append({'role':'system','content':
            'QA DIAGNOSIS PHASE: output ONLY the five-field JSON schema, no prose/fences. '
            'Use repository-relative code/test paths, not mounted /evidence paths. '
            'For blocked use editable_code_files=[], new_test_file="", acceptance=[]. '
            'root_cause <=1000 characters (target <=600); acceptance has at most five '
            'strings, each <=300 characters. Shorter valid output is preferred. '
            'Cite observed runtime evidence and distinguish unexecuted hypotheses. '
            'This schema grants no editing, testing, repair, approval or release authority.'})
    body['response_format'] = {'type': 'json_schema', 'json_schema': {
        'name': 'delivery_qa_diagnosis_v1' if mode == 'qa' else 'delivery_decision_v1', 'strict': True, 'schema': {
            'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}}}
    if finding_policy and mode.startswith('test_review:'):
        branches = []
        for action in ('approve_test_revision', 'reject_test_revision'):
            branch = json.loads(json.dumps(properties))
            branch['action']['enum'] = [action]
            if action == 'approve_test_revision':
                branch['findings']['maxItems'] = 0
            else:
                branch['findings']['minItems'] = 1
            branches.append({'type': 'object', 'properties': branch,
                             'required': list(branch), 'additionalProperties': False})
        body['response_format']['json_schema']['schema']['anyOf'] = branches
    if mode == 'qa':
        # Model/provider enforcement is NOT the authority boundary. Host-side
        # parse_diagnosis still validates every field and its decision-specific
        # consistency. Express that same consistency to the provider too.
        blocked = json.loads(json.dumps(properties))
        blocked['decision']['enum'] = ['blocked']
        blocked['editable_code_files']['maxItems'] = 0
        blocked['new_test_file']['enum'] = ['']
        blocked['acceptance']['maxItems'] = 0
        repair = json.loads(json.dumps(properties))
        repair['decision']['enum'] = ['repair']
        repair['editable_code_files']['minItems'] = 1
        repair['new_test_file']['minLength'] = 1
        repair['acceptance']['minItems'] = 1
        body['response_format']['json_schema']['schema']['anyOf'] = [
            {'type':'object','properties':branch,'required':list(branch),
             'additionalProperties':False} for branch in (blocked,repair)]
    # No provider may silently drop the schema. Do not introduce model fallback.
    body['provider'] = {**(body.get('provider') or {}), 'require_parameters': True}
    terminal_instruction=(
        'STRICT TERMINAL DECISION: output one JSON object matching response_format, '
        'no preamble, prose, Markdown fences or trailing explanation. '
        'reason must be concise and within its schema limit. '
        'The controller rejects the whole response if it is not valid JSON and schema-valid. '
        'A decision is not evidence of executed actions or release approval.')
    if body['messages'][-1].get('role')=='system':
        body['messages'][-1]['content']+='\n'+terminal_instruction
    else:body['messages'].append({'role':'system','content':terminal_instruction})
    return body
