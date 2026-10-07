"""Opt-in test-author phases: observed source reads, then an actual file tool.

This steers an existing permitted operation; workspace fences and controller
snapshots remain authoritative for access, TDD and delivery.
"""
import copy
import ast
import json
import re

from artifact_read_evidence import observations, next_read, coverage
from surgical_test_edit import marker_config,typed_schema
from author_read_policy import page_size

def additive_phase(body):
    marked=[]
    for index,message in enumerate(body.get('messages',[])):
        content=message.get('content','')
        if isinstance(content,list):content='\n'.join(p.get('text','') for p in content if isinstance(p,dict))
        if message.get('role')=='user' and isinstance(content,str) and re.search(r'^DELIVERY_ADDITIVE_CONTROL_V1\s*$',content,re.M):
            targets=re.findall(r'^DELIVERY_TEST_ARTIFACT_V1:([^\n]+)$',content,re.M)
            valid={'/workspace/tests/test_u3_c01_controls.py':'C01','/workspace/tests/test_u3_c02_controls.py':'C02'}
            if len(targets)!=1 or targets[0] not in valid:raise ValueError('additive target drift')
            if re.search(r'DELIVERY_(?:TEST_REVISION|SURGICAL_TEST|SEEDED_EDIT_REQUIRED)_V',content):raise ValueError('conflicting additive phase')
            marked.append(dict(index=index,path=targets[0],criterion=valid[targets[0]]))
    return marked[-1] if marked else None


def _selected(result,name,instruction):
    result.pop('response_format',None)
    result['tool_choice']={'type':'function','function':{'name':name}}
    result.pop('parallel_tool_calls',None)
    result.setdefault('provider',{})['require_parameters']=True
    result['messages'].append({'role':'system','content':instruction})
    return result


def revision_write_completed(history, target, sources):
    """Freeze pre-edit inspection; new bytes cannot invalidate old evidence."""
    calls={}
    for index,message in enumerate(history):
        if message.get('role')=='assistant':
            for call in message.get('tool_calls') or []:
                fn=call.get('function') or {}
                if fn.get('name') not in ('write_file','patch'):continue
                try:args=json.loads(fn.get('arguments','{}'))
                except (ValueError,TypeError):continue
                if (not isinstance(args,dict) or args.get('path')!=target
                        or not sources<=observations(history[:index],wire=True).keys()):continue
                if fn['name']=='patch':
                    if (isinstance(args.get('old_string'),str) and isinstance(args.get('new_string'),str)
                            and args['old_string']!=args['new_string']):
                        calls[call.get('id')]='patch'
                    continue
                if not isinstance(args.get('content'),str):continue
                content=args['content'];size=len(content.encode())
                if not 0<size<=32768:continue
                if target.endswith('.py'):
                    try:tree=ast.parse(content)
                    except SyntaxError:continue
                    if not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
                               and n.name.startswith('test_') for n in ast.walk(tree)):continue
                calls[call.get('id')]=size
        if message.get('role')!='tool' or message.get('tool_call_id') not in calls:continue
        try:receipt=json.loads(message.get('content',''))
        except (ValueError,TypeError):continue
        if calls[message['tool_call_id']]=='patch':
            if (isinstance(receipt,dict) and receipt.get('success') is True and not receipt.get('error')
                    and not receipt.get('already_applied') and not receipt.get('no_change')
                    and isinstance(receipt.get('diff'),str) and receipt['diff'].strip()):return True
            continue
        if (isinstance(receipt,dict) and not receipt.get('error') and receipt.get('success') is not False
                and receipt.get('verified') is True and type(receipt.get('bytes_written')) is int
                and receipt['bytes_written']==calls[message['tool_call_id']]
                and receipt.get('path',target)==target):return True
    return False


def apply(body):
    additive=additive_phase(body)
    surgical=marker_config(body)
    markers = set()
    sources = set()
    revisions = set()
    edit_required = set()
    for message in body.get('messages', []):
        if message.get('role') != 'user':
            continue
        content = message.get('content', '')
        if isinstance(content, list):
            content = '\n'.join(p.get('text', '') for p in content if isinstance(p, dict))
        if not isinstance(content, str):
            continue
        markers.update(re.findall(r'^DELIVERY_TEST_ARTIFACT_V1:([^\n]+)$', content, re.M))
        sources.update(re.findall(r'^DELIVERY_TEST_SOURCE_V1:([^\n]+)$', content, re.M))
        revisions.update(re.findall(r'^DELIVERY_TEST_REVISION_V1:([^\n]+)$', content, re.M))
        edit_required.update(re.findall(r'^DELIVERY_SEEDED_EDIT_REQUIRED_V1:([^\n]+)$', content, re.M))
    if not markers:
        if surgical:raise ValueError('surgical editing requires artifact contract')
        if revisions:raise ValueError('revision requires artifact contract')
        return body
    safe = lambda p: bool(re.fullmatch(r'/workspace/[A-Za-z0-9_./-]+', p)) and all(
        part not in ('.', '..', '') for part in p.split('/')[2:])
    if (len(markers) != 1 or not 1 <= len(sources) <= 4
            or any(not safe(p) for p in markers | sources)):
        raise ValueError('invalid test artifact phase contract')
    target = next(iter(markers))
    if additive and (target!=additive['path'] or revisions or edit_required or surgical):raise ValueError('conflicting additive phase')
    if revisions and revisions != {target}:
        raise ValueError('revision target drift')
    if edit_required and (edit_required != {target} or revisions != {target}):
        raise ValueError('seeded edit target drift')
    if target in sources or not (target.rsplit('/', 1)[-1].startswith('test_') and target.endswith('.py')
                               or target.endswith(('.test.js', '.spec.js'))):
        raise ValueError('invalid new-test target')
    tools = body.get('tools') or []
    names = [t.get('function', {}).get('name') for t in tools]
    if names.count('read_file') != 1 or names.count('write_file') != 1:
        raise ValueError('test artifact requires existing read and write tools')
    if surgical and surgical.get('protocol') in ('typed_v2','typed_driver_v3','typed_driver_lines_v4') and names.count('surgical_test_edit')!=1:
        raise ValueError('typed surgical tool missing from actual registry')
    result = copy.deepcopy(body)
    if surgical:
        if surgical['path']!=target:raise ValueError('surgical target drift')
        sources.add(target)
    if revisions:
        # A seeded revision must inspect the complete existing NEW test too.
        # Do not force an empty-file bootstrap write that truncates its suite.
        sources.add(target)
    read_history=body['messages']
    if additive:read_history=body['messages'][additive['index']:]
    if revisions:
        start=max(i for i,m in enumerate(body['messages']) if m.get('role')=='user'
            and re.search(r'DELIVERY_TEST_REVISION_V1:',str(m.get('content',''))))
        read_history=body['messages'][start:]
    if surgical:
        # A resumed session's historical reads do not authorize this new worker.
        # Require fresh observations after the controller's current grant marker.
        start=max(i for i,m in enumerate(body['messages']) if m.get('role')=='user'
                  and re.search(r'DELIVERY_SURGICAL_TEST_V[1234]:',str(m.get('content',''))))
        read_history=body['messages'][start:]
    if revisions and not edit_required and not surgical:
        if revision_write_completed(read_history,target,sources):
            return body  # Phase only: Red, protected bytes and review remain controller gates.
    if edit_required:
        # Editing invalidates comparisons of OLD/NEW lines in later reads.
        # Establish the inspection phase at the FIRST successful actual edit,
        # not from an ever-mutating file's entire conversation history.
        inspected_edits=set()
        for index,message in enumerate(read_history):
            if message.get('role')=='assistant':
                for call in message.get('tool_calls') or []:
                    fn=call.get('function') or {}
                    if fn.get('name')!='patch':continue
                    try:args=json.loads(fn.get('arguments','{}'))
                    except (ValueError,TypeError):continue
                    if (isinstance(args,dict) and args.get('path')==target
                            and isinstance(args.get('old_string'),str) and isinstance(args.get('new_string'),str)
                            and args['old_string']!=args['new_string']
                            and sources<=observations(read_history[:index],wire=True).keys()):
                        inspected_edits.add(call.get('id'))
            if message.get('role')!='tool' or message.get('tool_call_id') not in inspected_edits:continue
            try:receipt=json.loads(message.get('content',''))
            except (ValueError,TypeError):continue
            if (isinstance(receipt,dict) and receipt.get('success') is True and not receipt.get('error')
                    and not receipt.get('already_applied') and not receipt.get('no_change')
                    and isinstance(receipt.get('diff'),str) and receipt['diff'].strip()):
                return body  # Only phase progression; never Red, review or delivery approval.
    missing = sorted(sources - observations(read_history, wire=True).keys())
    if missing:
        path = missing[0]
        offset = next_read(read_history, path)
        chosen = next(t for t in result['tools'] if t['function']['name'] == 'read_file')
        chosen['function']['strict'] = True
        chosen['function']['parameters'] = {'type': 'object', 'properties': {
            'path': {'type': 'string', 'enum': [path]}, 'offset': {'type': 'integer', 'enum': [offset]},
            'limit': {'type': 'integer', 'enum': [200 if edit_required else page_size(body)]}},
            'required': ['path', 'offset', 'limit'], 'additionalProperties': False}
        name = 'read_file'
        instruction = 'TEST AUTHOR INSPECTION: read the selected source page, then proceed to actual test writing.'
    else:
        if surgical:
            for message in read_history:
                if message.get('role')!='tool':continue
                try:receipt=json.loads(message.get('content',''))
                except (ValueError,TypeError):continue
                if (receipt.get('operation')=='surgical_test_edit_v1' and receipt.get('verified') is True
                        and receipt.get('before_sha256')==surgical['expected_sha256']
                        and receipt.get('path')==target and receipt.get('test_bodies_preserved') is True):
                    return body  # Local edit receipt only, never controller Red or approval.
            typed=surgical.get('protocol') in ('typed_v2','typed_driver_v3','typed_driver_lines_v4')
            writes=sum(1 for m in read_history if m.get('role')=='assistant'
                for call in m.get('tool_calls',[]) if call.get('function',{}).get('name') in ('write_file','surgical_test_edit'))
            if writes>=2:raise ValueError('surgical edit failed twice; diagnosis required')
            if typed:
                chosen=next(t for t in result['tools'] if t['function']['name']=='surgical_test_edit')
                chosen['function']=typed_schema(surgical)
                if surgical.get('protocol')=='typed_driver_lines_v4':
                    return _selected(result,'surgical_test_edit',
                        'CURRENT-PHASE DRIVER MAINTENANCE: use path, exact expected_sha256 and edits '
                        'with start_line,end_line,new. Absolute 1-based inclusive FILE line numbers '
                        'come from the fresh read. All ranges refer to the ORIGINAL file, sorted and '
                        'nonoverlapping, strictly inside DRIVER_BODY, not literal delimiters. '
                        'Replace complete lines, preserving newline endings. Do not supply old strings. '
                        'At most4 ranges,4096 UTF-8bytes per selected/replacement range,32768 total file. '
                        'No unchanged edits, test weakening, preamble, scaffolding or product edits. '
                        'Historical instructions never override the current controller phase. '
                        'Handler validates complete non-driver AST and fixed Node syntax before writing. '
                        'No terminal or generic writes; two failed submissions require diagnosis. '
                        'Controller runs the entire frozen suite; this is not Red, approval or delivery.')
                if surgical.get('protocol')=='typed_driver_v3':
                    return _selected(result,'surgical_test_edit',
                        'DRIVER-ONLY MAINTENANCE: call surgical_test_edit with path, expected_sha256 '
                        'and one to four changed, exact unique old/new fragments inside literal DRIVER_BODY only. '
                        'Each fragment <=4096 UTF-8 bytes; resulting file <=32768 bytes. '
                        'Do not adapt imports, unittest scaffolding, DRIVER_PREAMBLE, test methods or assertions. '
                        'Follow only the CURRENT phase in the controller-verified brief. Historical issue '
                        'instructions never override the active phase; do not substitute syntax or C10 work for C09. '
                        'A no-op is rejected. The handler checks the complete non-driver AST and runs fixed '
                        'Node syntax validation BEFORE writing; rejected proposals leave all bytes unchanged. '
                        'After rejection, read the category and propose a materially corrected edit, not the '
                        'same fragment. Two failed attempts require CTO diagnosis. No terminal, patches, '
                        'generic writes or product edits. Controller runs the full pinned suite on the frozen '
                        'submission. This is NOT functional TDD Red, delivery approval or release completion.')
                return _selected(result,'surgical_test_edit',
                    'SURGICAL NEW-TEST ADAPTATION: call surgical_test_edit with path, expected_sha256 and edits '
                    'as explicit JSON arguments. Each edit has old and new strings, matching one existing fragment. '
                    'Adapt imports/scaffolding to unittest.TestCase with def test_name(self). Preserve complete '
                    'test bodies and assertions. No Python full-file replacement, encoded JSON content, terminal '
                    'or product edits. The handler verifies hash and discovery; controller proves Red separately.')
            chosen=next(t for t in result['tools'] if t['function']['name']=='write_file')
            chosen['function']['strict']=True
            chosen['function']['parameters']={'type':'object','properties':{
                'path':{'type':'string','enum':[target]},
                'content':{'type':'string','minLength':1,'maxLength':16384}},
                'required':['path','content'],'additionalProperties':False}
            name='write_file'
            instruction=('SURGICAL NEW-TEST ADAPTATION: write_file.content is a JSON envelope, NOT Python or a full file. '
                'Use {"expected_sha256":"'+surgical['expected_sha256']+'","edits":[{"old":"exact existing fragment","new":"replacement"}]}. '
                'One to four exact unique replacements, each fragment at most4096 UTF-8 bytes. '
                'Adapt only imports/scaffolding to unittest.TestCase with def test_name(self). '
                'Preserve every test name, complete test body and assertion unchanged; remove pytest dependencies '
                'without skipping tests. The handler checks the current hash and discovery, then performs the edit. '
                'Do not send write_file content as Python, use terminal, patches or edit product/baseline files. '
                'Read pages completed. Controller will execute the full suite and freeze Red independently.')
            return _selected(result,name,instruction)
        elif revisions:
            if edit_required:
                patch_calls = {}
                for message in read_history:
                    if message.get('role') != 'assistant': continue
                    for call in message.get('tool_calls') or []:
                        fn=call.get('function') or {}
                        if fn.get('name')!='patch': continue
                        try: args=json.loads(fn.get('arguments','{}'))
                        except (ValueError,TypeError): continue
                        if (isinstance(args,dict) and args.get('path')==target
                                and isinstance(args.get('old_string'),str) and isinstance(args.get('new_string'),str)
                                and args['old_string']!=args['new_string']):
                            patch_calls[call.get('id')]=args
                for message in read_history:
                    if message.get('role')!='tool' or message.get('tool_call_id') not in patch_calls: continue
                    try: receipt=json.loads(message.get('content',''))
                    except (ValueError,TypeError): continue
                    if (isinstance(receipt,dict) and receipt.get('success') is True and not receipt.get('error')
                            and not receipt.get('already_applied') and not receipt.get('no_change')
                            and isinstance(receipt.get('diff'),str) and receipt['diff'].strip()):
                        return body  # Tool receipt only; controller still verifies changed hash and Red.
                if len(patch_calls)>=2: raise ValueError('seeded patch failed twice; diagnosis required')
                if names.count('patch')!=1: raise ValueError('seeded repair requires existing patch tool')
                chosen=next(t for t in result['tools'] if t['function']['name']=='patch')
                chosen['function']['strict']=True
                chosen['function']['parameters']={'type':'object','properties':{
                    'path':{'type':'string','enum':[target]},
                    'old_string':{'type':'string','minLength':1,'maxLength':4096},
                    'new_string':{'type':'string','minLength':1,'maxLength':4096}},
                    'required':['path','old_string','new_string'],'additionalProperties':False}
                observed=coverage(read_history,wire=True,include_content=True).get(target,{})
                lines=observed.get('line_content',{})
                # Full numbered reads prove content, not the exact final-newline
                # bit. Report a conservative byte ceiling, never invented stat.
                byte_ceiling=sum(len(text.encode('utf-8'))+1 for text in lines.values())
                budget=('Observed complete source byte ceiling='+str(byte_ceiling)+
                    '; write limit32768. If headroom is small, first shorten duplicate COMMENTS with a narrow patch, '
                    'preserving every method/assertion, then repair the harness. Do not increase limits or weaken tests. '
                    if observed.get('lines')==observed.get('total_lines') and lines else '')
                return _selected(result,'patch',
                    budget+'SEEDED HARNESS REPAIR: fresh reads observed. Perform ONE actual narrow patch '
                    'to the diagnosed NEW harness now: unique old_string and changed new_string. '
                    'No promise, terminal, full-file replacement or assertion deletion. Preserve '
                    'existing methods/assertions. Then complete remaining fixes and executable '
                    'negative controls using permitted tools. One patch is NOT completion. '
                    'Controller changed-hash check, real Red and independent review remain required.')
            result.pop('tool_choice',None)
            result['messages'].append({'role':'system','content':
                'SEEDED NEW-TEST REVISION. Required source and historic test reads completed. '
                'Use existing permitted editing tools for narrow fixture/parser/report corrections '
                'in the declared NEW test only. Preserve all test methods, assertions and acceptance '
                'criteria; do not replace the suite with a small bootstrap test. Baseline tests and '
                'product code remain forbidden. Tool receipts, controller Red and independent '
                'snapshot review are still required; this is not approval or completion evidence.'})
            return result
        calls = {}
        for message in body['messages']:
            if message.get('role') != 'assistant':
                continue
            for call in message.get('tool_calls') or []:
                function = call.get('function') or {}
                if function.get('name') != 'write_file':
                    continue
                try:
                    args = json.loads(function.get('arguments', '{}'))
                except (ValueError, TypeError):
                    continue
                if isinstance(args, dict) and args.get('path') == target and isinstance(args.get('content'), str):
                    content = args['content']
                    recognizable = True
                    if target.endswith('.py'):
                        try:
                            tree = ast.parse(content)
                            recognizable = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                                               and n.name.startswith('test_') for n in ast.walk(tree))
                        except SyntaxError:
                            recognizable = False
                    calls[call.get('id')] = (len(content.encode()), recognizable)
        for message in body['messages']:
            if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
                continue
            try:
                receipt = json.loads(message.get('content', ''))
            except (ValueError, TypeError):
                continue
            size, recognizable = calls[message['tool_call_id']]
            if (isinstance(receipt, dict) and not receipt.get('error') and receipt.get('success') is not False
                    and receipt.get('verified') is True and type(receipt.get('bytes_written')) is int
                    and receipt['bytes_written'] == size and 0 < size <= 32768
                    and receipt.get('path', target) == target and recognizable
                    and (not additive or (receipt.get('created') is True and receipt.get('delivery_approval') is False))):
                return body  # Tool receipt only; controller must still prove Red and freeze hashes.
        if len(calls) >= 2:
            raise ValueError('test artifact write failed twice; diagnosis required')
        chosen = next(t for t in result['tools'] if t['function']['name'] == 'write_file')
        chosen['function']['strict'] = True
        chosen['function']['parameters'] = {'type': 'object', 'properties': {
            'path': {'type': 'string', 'enum': [target]},
            'content': {'type': 'string', 'minLength': 1, 'maxLength': 6144}},
            'required': ['path', 'content'], 'additionalProperties': False}
        name = 'write_file'
        instruction = ('TEST AUTHOR FIRST ARTIFACT PHASE: use write_file for a small executable NEW test now, '
            'at most 6144 characters; aim below 4000. Reuse baseline harness patterns; '
            'do not copy application sources or invent a giant replacement harness. '
            'Start with one real failing behavior and actual assertions. After this verified write, '
            'extend the SAME new test incrementally to cover ALL unchanged acceptance criteria, '
            'using ordinary permitted tools and small edits. This first artifact is not completion '
            'or scope reduction. A promise or plan is not an artifact. '
            'Python content must parse and contain actual test_ methods, not just documentation or a harness. '
            'Do not modify application code or existing tests. Controller Red and independent review remain required.')
        if additive:
            method='test_c01_query_clearing_control' if additive['criterion']=='C01' else 'test_c02_stale_status_control'
            instruction=('ADDITIVE CONTROL SINGLE-CREATE PHASE. Call write_file exactly once with path='+target+
                ' and complete executable Python content. Aim below 3000 UTF-8 bytes; hard limit6144 bytes. '
                'One unittest.TestCase, one method '+method+'(self). '
                'Top level: imports and the TestCase only, optional docstring. '
                'All driver strings/constants go inside the method; no top-level assignments/functions or __main__ guard. '
                'Allowed imports only unittest, json, subprocess, shutil, pathlib, tests.test_incremental_u3; no __future__ import. '
                'Import tests.test_incremental_u3 as u3; reuse its actual harness, never copy its long driver. '
                'For C01 use a short Node driver with u3.DRIVER_PREAMBLE to input alpha then blank and assert no q in next actual GET. '
                'For C02 instantiate u3.IncrementalU3QueryMemoryTests, setUpClass/setUp, and assert recorded rendered_after_stale_status excludes STALE OPEN (with a space). '
                'Do not extend or patch the file after the verified create. Stop with a short completion statement. '
                'No terminal, existing-file changes, new Red execution or product edits. '
                'The fixed controller runs real mutations and full suite, then an independent reviewer; this write is not approval.')
            result['tools']=[chosen]
    result.pop('response_format', None)
    result['tool_choice'] = {'type': 'function', 'function': {'name': name}}
    # OpenRouter require_parameters filters even false-valued unsupported
    # parameters. DeepSeek endpoints advertise tools/tool_choice, not this
    # optional flag. Keep the pinned tool and controller fences, not a flag
    # that makes every provider ineligible before any tool can execute.
    result.pop('parallel_tool_calls', None)
    result.setdefault('provider', {})['require_parameters'] = True
    result['messages'].append({'role': 'system', 'content': instruction})
    return result
