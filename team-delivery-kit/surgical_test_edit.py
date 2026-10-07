"""Bounded, hash-checked NEW-test adaptation; never approval or Red evidence."""
import ast
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from c10_micro_drain import MicroDrainError


class DriverSyntaxError(ValueError):
    """Allowlisted Node diagnostics, never source or raw stderr."""
    def __init__(self,stderr,body):
        super().__init__('driver syntax invalid')
        match=re.search(r'\[stdin\]:(\d{1,5})\b',stderr or '')
        line=int(match[1]) if match else None
        self.diagnostic={'syntax_category':next((category for text,category in (
            ('Unexpected end of input','unexpected_end'),('Unexpected token','unexpected_token'),
            ('missing ) after argument list','missing_parenthesis'),
            ('Invalid or unexpected token','invalid_token')) if text in (stderr or '')),'other_syntax_error')}
        if line is not None and 1<=line<=len(body.splitlines())+1:
            self.diagnostic['driver_line']=line


class FragmentSelectionError(ValueError):
    """Source-free diagnostics for an already hash-validated bounded input."""
    def __init__(self,index,matches,reason):
        if (type(index) is not int or not 1<=index<=4 or type(matches) is not int
                or not 0<=matches<=32768 or reason not in ('missing','ambiguous','unchanged')):
            raise ValueError('invalid fragment diagnostic')
        super().__init__('surgical edit made no bounded change' if reason=='unchanged'
            else 'ambiguous or oversized surgical edit')
        self.index,self.matches,self.reason=index,matches,reason


def rejection_feedback(error):
    """Fixed, actionable categories; never disclose exception text or paths."""
    mapping={
        'micro drain requires exact executable recipe':('micro_recipe_required','use_exact_controller_recipe_not_comments'),
        'micro drain source anchor mismatch':('micro_anchor_mismatch','request_controller_diagnosis'),
        'atomic STATUS requires one complete multiline window':('status_atomic_shape_required','submit_one_multiline_534_536_replacement'),
        'atomic STATUS missing complete real observation operations':('status_observations_incomplete','include_all_status_observations_before_submit'),
        'all tests must remain unittest discoverable':('unittest_discovery_required','wrap_in_unittest_testcase'),
        'test discovery signature invalid':('unittest_signature_invalid','use_test_method_with_self'),
        'no preserved test methods':('test_methods_missing','retain_original_test_methods'),
        'test bodies or methods changed':('test_bodies_changed','restore_original_test_bodies'),
        'unpinned framework remains':('pytest_dependency_remaining','adapt_framework_scaffolding_only'),
        'test skipping forbidden':('test_skip_forbidden','remove_skipping_without_weakening_tests'),
        'ambiguous or oversized surgical edit':('replacement_not_unique_or_bounded','select_unique_exact_fragment'),
        'surgical edit made no bounded change':('no_bounded_change','provide_bounded_scaffolding_change'),
        'surgical result exceeds file limit':('file_size_exceeded','compact_driver_comments_within_granted_scope'),
        'stale surgical input hash':('stale_input_hash','request_controller_diagnosis'),
        'surgical hash mismatch':('grant_hash_mismatch','use_exact_controller_grant'),
        'surgical path mismatch':('grant_path_mismatch','use_exact_controller_grant'),
        'surgical grant hash drift':('grant_hash_mismatch','use_exact_controller_grant'),
        'unobserved or invalid surgical target':('read_or_target_invalid','complete_fresh_target_read'),
        'unowned surgical target':('target_ownership_invalid','request_controller_diagnosis'),
        'operation forbidden in surgical mode':('operation_forbidden','use_surgical_tool_only'),
        'outside driver scope changed':('outside_driver_scope_changed','edit_driver_body_only'),
        'driver syntax invalid':('driver_syntax_invalid','balance_driver_constructs_before_submit'),
        'identical rejected surgical proposal':('identical_rejected_proposal','change_proposal_using_previous_syntax_feedback'),
        'surgical argument shape mismatch':('argument_shape_invalid','use_explicit_typed_arguments'),
        'surgical edits invalid':('edit_shape_invalid','use_bounded_old_new_fragments')}
    category,action=mapping.get(str(error),('internal_error','request_controller_diagnosis')) if isinstance(error,ValueError) else (
        ('syntax_invalid','correct_scaffolding_syntax') if isinstance(error,SyntaxError) else
        ('permission_denied','request_controller_diagnosis') if isinstance(error,PermissionError) else
        ('io_failure','request_controller_diagnosis') if isinstance(error,OSError) else
        ('internal_error','request_controller_diagnosis'))
    result=dict(error='surgical_edit_rejected:'+category+':'+action,
        category=category,next_operation=action,verified=False,delivery_approval=False,
        constraints='Keep every original test name and complete body unchanged; use top-level unittest.TestCase with test_name(self). No skip or product edits.')
    if isinstance(error,FragmentSelectionError):
        hint=('extend_old_with_exact_surrounding_context' if error.reason=='ambiguous' else
            'copy_old_exactly_from_fresh_read' if error.reason=='missing' else 'make_old_and_new_different')
        result['fragment_diagnostic']={'index':error.index,'match_count':error.matches,'reason':error.reason,'hint':hint}
        # ACP surfaces only the error field: preserve its stable first-line protocol.
        result['error']+='\nfragment_index='+str(error.index)+' match_count='+str(error.matches)+' reason='+error.reason+' hint='+hint
    if isinstance(error,DriverSyntaxError):
        result['driver_diagnostic']=dict(error.diagnostic)
        result['error']+='\n'+' '.join(k+'='+str(v) for k,v in error.diagnostic.items())
    return result


def marker_config(body):
    markers=[]
    for message in body.get('messages',[]):
        if message.get('role')!='user':continue
        content=message.get('content','')
        if isinstance(content,list):content='\n'.join(p.get('text','') for p in content if isinstance(p,dict))
        if isinstance(content,str):markers.extend(re.findall(r'^DELIVERY_SURGICAL_TEST_(V[12345]):([^\n]+)$',content,re.M))
    if not markers:return None
    markers=set(markers)
    if len(markers)!=1:raise ValueError('surgical marker drift')
    version,value=next(iter(markers))
    match=re.fullmatch(r'(/workspace/[A-Za-z0-9_./-]+):([0-9a-f]{64})',value)
    if not match or any(p in ('.','..','') for p in match[1].split('/')[2:]):raise ValueError('invalid surgical marker')
    result=dict(path=match[1],expected_sha256=match[2])
    if version=='V2':result['protocol']='typed_v2'
    if version=='V3':result['protocol']='typed_driver_v3'
    if version=='V4':result['protocol']='typed_driver_lines_v4'
    if version=='V5':result['protocol']='typed_template_v5'
    drains={value for message in body.get('messages',[]) if message.get('role')=='user'
        and isinstance(message.get('content'),str)
        for value in re.findall(r'^DELIVERY_STATUS_DRAIN_V1:([^\n]+)$',message['content'],re.M)}
    if drains:
        if version!='V4' or len(drains)!=1 or not drains<= {'resolveNewest','resolveOldest'}:
            raise ValueError('invalid micro drain marker')
        result['drain_resolver']=next(iter(drains))
    return result


def typed_schema(config):
    """One JSON object, not encoded JSON inside a file-content string."""
    if config.get('protocol')=='typed_driver_lines_v4':
        schema={'name':'surgical_test_edit','description':'Hash-bound DRIVER_BODY-only line edits. Use absolute 1-based file lines from fresh read, inclusive start/end. All ranges refer to the ORIGINAL granted file, sorted and disjoint. Replace complete lines; include newline endings. Never copy old text. No terminal or product edits; not approval.',
            'strict':True,'parameters':{'type':'object','properties':{
                'path':{'type':'string','enum':[config['path']]},
                'expected_sha256':{'type':'string','enum':[config['expected_sha256']]},
                'edits':{'type':'array','minItems':1,'maxItems':4,'items':{'type':'object','properties':{
                    'start_line':{'type':'integer','minimum':1,'maximum':32768},
                    'end_line':{'type':'integer','minimum':1,'maximum':32768},
                    'new':{'type':'string','maxLength':4096}},'required':['start_line','end_line','new'],'additionalProperties':False}}},
                'required':['path','expected_sha256','edits'],'additionalProperties':False}}
        if config.get('atomic_contract'):
            from c10_status_atomic import CONTRACT
            if config['atomic_contract']!=CONTRACT:raise ValueError('unknown atomic contract')
            edits=schema['parameters']['properties']['edits'];edits['maxItems']=1
            edits['items']['properties']['start_line']={'type':'integer','enum':[534]}
            edits['items']['properties']['end_line']={'type':'integer','enum':[536]}
            schema['description']='ONE complete multiline STATUS replacement at534-536. new must contain the WHOLE experiment, not three single-line starters. Real filter-open/filter-completed clicks, calls.slice URL reports, two items responses with flush/DOM observations, final pending.length. Partial edits are rejected before writing. Not approval.'
        if config.get('drain_resolver'):
            from c10_micro_drain import recipe
            if config.get('atomic_contract'):raise ValueError('conflicting micro and atomic contracts')
            edits=schema['parameters']['properties']['edits'];edits['maxItems']=1
            props=edits['items']['properties']
            props['start_line']={'type':'integer','enum':[551]};props['end_line']={'type':'integer','enum':[551]}
            props['new']={'type':'string','enum':[recipe(config['drain_resolver'])]}
            schema['description']='Apply ONLY this controller-verified executable recipe at original line551, after fresh complete read. Do not generate code, comments or explanations. Invocation performs a real hash-checked edit; not tests, review or approval.'
        return schema
    return {'name':'surgical_test_edit','description':
        ('Hash-bound NODE_HARNESS_TEMPLATE-only repair with Node syntax validation; all other Python AST and test bodies stay unchanged. '
        if config.get('protocol')=='typed_template_v5' else
        'Hash-bound DRIVER_BODY-only repair with Node syntax validation before writing. '
        if config.get('protocol')=='typed_driver_v3' else
        'Hash-bound adaptation of the declared NEW test scaffolding only. ')+
        'Each old fragment must match exactly once and differ from new. Include '
        'surrounding context to distinguish repeated code; copy it exactly from a '
        'fresh read. Never submit unchanged pairs. Preserves all test bodies. '
        'Not Red, delivery completion or approval.',
        'strict':True,'parameters':{'type':'object','properties':{
            'path':{'type':'string','enum':[config['path']]},
            'expected_sha256':{'type':'string','enum':[config['expected_sha256']]},
            'edits':{'type':'array','minItems':1,'maxItems':4,'items':{
                'type':'object','properties':{
                    'old':{'type':'string','minLength':1,'maxLength':4096},
                    'new':{'type':'string','maxLength':4096}},
                'required':['old','new'],'additionalProperties':False}}},
            'required':['path','expected_sha256','edits'],'additionalProperties':False}}


def validate_typed(args,config):
    # Fixed categories only: never return provider arguments or source text.
    if not isinstance(args,dict) or set(args)!={'path','expected_sha256','edits'}:
        raise ValueError('surgical argument shape mismatch')
    if args['path']!=config['path']:raise ValueError('surgical path mismatch')
    if args['expected_sha256']!=config['expected_sha256']:raise ValueError('surgical hash mismatch')
    try:
        validator=validate_line_envelope if config.get('protocol')=='typed_driver_lines_v4' else validate_envelope
        validator({k:args[k] for k in ('expected_sha256','edits')},config['expected_sha256'])
    except (ValueError,TypeError,UnicodeError):raise ValueError('surgical edits invalid') from None
    if config.get('atomic_contract'):
        from c10_status_atomic import CONTRACT
        if config['atomic_contract']!=CONTRACT:raise ValueError('unknown atomic contract')
    if config.get('drain_resolver'):
        from c10_micro_drain import validate
        validate(args,config['drain_resolver'])


def validate_envelope(args,expected):
    if (not isinstance(args,dict) or set(args)!={'expected_sha256','edits'}
            or args.get('expected_sha256')!=expected or not isinstance(args['edits'],list)
            or not 1<=len(args['edits'])<=4):raise ValueError('invalid surgical envelope')
    for edit in args['edits']:
        if (not isinstance(edit,dict) or set(edit)!={'old','new'}
                or not isinstance(edit['old'],str) or not 0<len(edit['old'].encode())<=4096
                or not isinstance(edit['new'],str) or len(edit['new'].encode())>4096):
            raise ValueError('invalid surgical envelope')


def _tests(tree):
    nodes=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
           and n.name.startswith('test_')]
    if not nodes:raise ValueError('no preserved test methods')
    return Counter((n.name,ast.dump(ast.Module(body=n.body,type_ignores=[]),include_attributes=False)) for n in nodes)


def _discoverable(tree):
    found=[]
    for node in tree.body:
        if not isinstance(node,ast.ClassDef):continue
        if not any(ast.unparse(b) in ('unittest.TestCase','TestCase') for b in node.bases):continue
        for method in node.body:
            if isinstance(method,ast.FunctionDef) and method.name.startswith('test_'):
                if (method.decorator_list or [a.arg for a in method.args.args]!=['self']
                        or method.args.vararg or method.args.kwarg or method.args.kwonlyargs
                        or method.args.posonlyargs or method.args.defaults):
                    raise ValueError('test discovery signature invalid')
                found.append(method)
    all_tests=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
               and n.name.startswith('test_')]
    if len(found)!=len(all_tests):raise ValueError('all tests must remain unittest discoverable')
    for node in ast.walk(tree):
        if isinstance(node,ast.Name) and node.id in ('pytest','_pytest'):raise ValueError('unpinned framework remains')
        if isinstance(node,ast.Import) and any(a.name.split('.')[0] in ('pytest','_pytest') for a in node.names):
            raise ValueError('unpinned framework remains')
        if isinstance(node,ast.ImportFrom) and (node.module or '').split('.')[0] in ('pytest','_pytest'):
            raise ValueError('unpinned framework remains')
        if isinstance(node,ast.Attribute) and node.attr in ('skip','skipIf','skipUnless','SkipTest'):
            raise ValueError('test skipping forbidden')


def prepare(source,args):
    if (not isinstance(args,dict) or set(args)!={'expected_sha256','edits'}
            or not re.fullmatch('[0-9a-f]{64}',str(args.get('expected_sha256')))
            or not isinstance(args['edits'],list) or not 1<=len(args['edits'])<=4):
        raise ValueError('invalid surgical edit contract')
    if not 0<len(source)<=32768 or hashlib.sha256(source).hexdigest()!=args['expected_sha256']:
        raise ValueError('stale surgical input hash')
    text=source.decode('utf-8');original=ast.parse(text)
    for index,edit in enumerate(args['edits'],1):
        if (not isinstance(edit,dict) or set(edit)!={'old','new'}
                or not isinstance(edit['old'],str) or not 0<len(edit['old'].encode())<=4096
                or not isinstance(edit['new'],str) or len(edit['new'].encode())>4096):raise ValueError('ambiguous or oversized surgical edit')
        matches=text.count(edit['old'])
        if matches!=1:raise FragmentSelectionError(index,matches,'missing' if matches==0 else 'ambiguous')
        if edit['old']==edit['new']:raise FragmentSelectionError(index,matches,'unchanged')
        text=text.replace(edit['old'],edit['new'],1)
    result=text.encode('utf-8')
    if not 0<len(result)<=32768:raise ValueError('surgical result exceeds file limit')
    if result==source:raise ValueError('surgical edit made no bounded change')
    tree=ast.parse(text)
    if _tests(original)!=_tests(tree):raise ValueError('test bodies or methods changed')
    _discoverable(tree)
    return result


def validate_line_envelope(args,expected):
    if (not isinstance(args,dict) or set(args)!={'expected_sha256','edits'}
            or not re.fullmatch('[0-9a-f]{64}',str(expected)) or args.get('expected_sha256')!=expected
            or not isinstance(args['edits'],list) or not 1<=len(args['edits'])<=4):
        raise ValueError('invalid surgical envelope')
    prior=0
    for edit in args['edits']:
        if (not isinstance(edit,dict) or set(edit)!={'start_line','end_line','new'}
                or type(edit['start_line']) is not int or type(edit['end_line']) is not int
                or not prior<edit['start_line']<=edit['end_line']<=32768
                or not isinstance(edit['new'],str) or len(edit['new'].encode())>4096):
            raise ValueError('invalid surgical envelope')
        prior=edit['end_line']


def prepare_driver_lines(source,args):
    validate_line_envelope(args,args.get('expected_sha256') if isinstance(args,dict) else None)
    if not 0<len(source)<=32768 or hashlib.sha256(source).hexdigest()!=args['expected_sha256']:
        raise ValueError('stale surgical input hash')
    text=source.decode('utf-8');lines=text.splitlines(keepends=True);tree=ast.parse(text)
    drivers=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
        and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='DRIVER_BODY']
    if len(drivers)!=1 or not isinstance(drivers[0].value,ast.Constant) or not isinstance(drivers[0].value.value,str):
        raise ValueError('single literal driver required')
    node=drivers[0].value
    pieces=[];cursor=0
    for index,edit in enumerate(args['edits'],1):
        start,end=edit['start_line'],edit['end_line']
        if not node.lineno<start<=end<node.end_lineno or end>len(lines):
            raise ValueError('outside driver scope changed')
        old=''.join(lines[start-1:end])
        if len(old.encode())>4096:raise ValueError('ambiguous or oversized surgical edit')
        if old==edit['new']:raise FragmentSelectionError(index,1,'unchanged')
        pieces.extend(lines[cursor:start-1]);pieces.append(edit['new']);cursor=end
    pieces.extend(lines[cursor:]);result=''.join(pieces).encode()
    if not 0<len(result)<=32768:raise ValueError('surgical result exceeds file limit')
    if result==source:raise ValueError('surgical edit made no bounded change')
    if _tests(tree)!=_tests(ast.parse(result)):raise ValueError('test bodies or methods changed')
    _discoverable(ast.parse(result))
    return _validate_driver_result(source,result)


def prepare_driver(source,args):
    """Stricter maintenance checkpoint: reject before any file truncation.

    This is not a functional test, Red receipt or review approval. Only the
    literal DRIVER_BODY may change; the fixed Node argv cannot be agent-supplied.
    """
    result=prepare(source,args)
    return _validate_driver_result(source,result)


def _validate_driver_result(source,result):
    return _validate_literal_result(source,result,'DRIVER_BODY')


def prepare_template(source,args):
    """Scoped NEW-harness repair, not edits to assertions or product files."""
    return _validate_literal_result(source,prepare(source,args),'NODE_HARNESS_TEMPLATE')


def _validate_literal_result(source,result,name):
    trees=[ast.parse(value.decode('utf-8')) for value in (source,result)]
    bodies=[]
    for tree in trees:
        drivers=[node for node in tree.body if isinstance(node,ast.Assign)
            and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
            and node.targets[0].id==name]
        if len(drivers)!=1:raise ValueError('single literal driver required')
        try:body=ast.literal_eval(drivers[0].value)
        except (ValueError,TypeError):raise ValueError('single literal driver required') from None
        if not isinstance(body,str):raise ValueError('single literal driver required')
        bodies.append(body);drivers[0].value=ast.Constant(value='DRIVER_ONLY')
    if ast.dump(trees[0],include_attributes=False)!=ast.dump(trees[1],include_attributes=False):
        raise ValueError('outside driver scope changed')
    body=bodies[1]
    if name=='NODE_HARNESS_TEMPLATE':
        body=body % {'source_path':json.dumps('/delivery/product.js'),'source_filename':json.dumps('/delivery/product.js')}
    checked=subprocess.run(['node','--check'],input=body,text=True,
        capture_output=True,timeout=10)
    if checked.returncode:raise DriverSyntaxError(checked.stderr,body)
    return result


def diagnose_driver_proposal(source, args):
    """Controller-only replay of validation, never application of a rejected edit.

    Return only hashes, bounded line numbers and allowlisted syntax categories.
    Node receives source through stdin with fixed --check argv, never execution.
    """
    report={'delivery_approval':False,'files_modified':False,
            'source_sha256':hashlib.sha256(source).hexdigest()}
    try:
        result=prepare(source,args)
        tree=ast.parse(result)
        nodes=[n for n in tree.body if isinstance(n,ast.Assign) and
            len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='DRIVER_BODY']
        if len(nodes)!=1:raise ValueError('outside driver scope changed')
        body=ast.literal_eval(nodes[0].value)
        if not isinstance(body,str):raise ValueError('outside driver scope changed')
        report['candidate_sha256']=hashlib.sha256(result).hexdigest()
        checked=subprocess.run(['node','--check'],input=body,text=True,capture_output=True,timeout=10)
        report['node_syntax_valid']=checked.returncode==0
        if checked.returncode:
            stderr=checked.stderr or ''
            match=re.search(r'\[stdin\]:(\d+)',stderr)
            line=int(match[1]) if match else None
            if line is not None and 1<=line<=len(body.splitlines())+1:report['driver_line']=line
            report['syntax_category']=next((category for text,category in (
                ('Unexpected end of input','unexpected_end'),('Unexpected token','unexpected_token'),
                ('missing ) after argument list','missing_parenthesis'),('Invalid or unexpected token','invalid_token'))
                if text in stderr),'other_syntax_error')
            report['category']='driver_syntax_invalid'
        else:
            prepare_driver(source,args)
            report['category']='structurally_valid_proposal'
    except (ValueError,SyntaxError,TypeError) as error:
        report['category']=rejection_feedback(error)['category']
        if str(error)=='surgical result exceeds file limit':
            text=source.decode('utf-8')
            for edit in args['edits']:text=text.replace(edit['old'],edit['new'],1)
            report.update(proposed_bytes=len(text.encode('utf-8')),limit_bytes=32768)
    return report


def _guarded_prepare(source,args,prepare_fn,ledger_path,target,required_uid):
    from c10_status_atomic import StatusAtomicError
    """Worker-private persistent syntax rejection receipts, scoped to exact input.

    The controller supplies the ledger path, never the agent. Only hashes are
    stored; IO/corruption failures are fail-closed, not silently forgotten.
    """
    if ledger_path is None:return prepare_fn(source,args)
    fingerprint=hashlib.sha256(json.dumps({'path':str(target),
        'source_sha256':hashlib.sha256(source).hexdigest(),'proposal':args},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    fd=os.open(ledger_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_mode & 0o077
                or info.st_uid!=os.geteuid()):
            raise PermissionError('invalid rejection ledger')
        raw=os.read(fd,65537)
        if len(raw)>65536:raise ValueError('invalid rejection ledger')
        receipts=json.loads(raw) if raw else []
        if (not isinstance(receipts,list) or len(receipts)>256 or
                any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in receipts)):
            raise ValueError('invalid rejection ledger')
        if fingerprint in receipts:raise ValueError('identical rejected surgical proposal')
        # Do not evict rejection receipts: the worker's 40-iteration limit is
        # below this bound, and eviction would allow an old proposal to recur.
        if len(receipts)>=256:raise ValueError('invalid rejection ledger')
        try:return prepare_fn(source,args)
        except (DriverSyntaxError,StatusAtomicError,MicroDrainError):
            payload=json.dumps(receipts+[fingerprint],separators=(',',':')).encode()
            os.lseek(fd,0,os.SEEK_SET);os.ftruncate(fd,0)
            view=memoryview(payload)
            while view:
                count=os.write(fd,view)
                if count<=0:raise OSError('incomplete rejection receipt')
                view=view[count:]
            os.fsync(fd)
            raise
    finally:os.close(fd)


def edit_file(path,args,*,root=Path('/workspace'),observed_read=False,required_uid=None,driver_only=False,line_ranges=False,rejection_ledger=None,atomic_status=False,micro_resolver=None,template_only=False):
    target=Path(path);root=Path(root)
    if (not observed_read or not target.is_absolute() or target.resolve()!=target
            or root not in target.parents or not target.name.startswith('test_') or target.suffix!='.py'):
        raise ValueError('unobserved or invalid surgical target')
    fd=os.open(target,os.O_RDWR|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
                or required_uid is not None and info.st_uid!=required_uid):raise ValueError('unowned surgical target')
        if line_ranges and not driver_only:raise ValueError('operation forbidden in surgical mode')
        source=os.read(fd,32769)
        if template_only and (driver_only or line_ranges or atomic_status or micro_resolver):raise ValueError('operation forbidden in surgical mode')
        prepare_fn=prepare_template if template_only else prepare_driver_lines if line_ranges else prepare_driver if driver_only else prepare
        if micro_resolver:
            from c10_micro_drain import validate
            if atomic_status or not driver_only or not line_ranges:raise ValueError('operation forbidden in surgical mode')
            original_micro_prepare=prepare_fn
            def prepare_micro(raw,envelope):
                validate(envelope,micro_resolver,raw)
                return original_micro_prepare(raw,envelope)
            prepare_fn=prepare_micro
        if atomic_status:
            from c10_status_atomic import validate
            if not driver_only or not line_ranges:raise ValueError('operation forbidden in surgical mode')
            original_prepare=prepare_fn
            def prepare_atomic(raw,envelope):
                validate(envelope)  # Locked, before truncate/write and within replay ledger.
                return original_prepare(raw,envelope)
            prepare_fn=prepare_atomic
        result=_guarded_prepare(source,args,prepare_fn,rejection_ledger,target,required_uid)
        os.lseek(fd,0,os.SEEK_SET);os.ftruncate(fd,0)
        view=memoryview(result)
        while view:
            count=os.write(fd,view)
            if count<=0:raise OSError('incomplete surgical write')
            view=view[count:]
        os.fsync(fd)
        os.lseek(fd,0,os.SEEK_SET)
        if os.read(fd,32769)!=result:raise OSError('surgical post-write verification failed')
        return dict(operation='surgical_test_edit_v1',path=str(target),verified=True,
            before_sha256=args['expected_sha256'],sha256=hashlib.sha256(result).hexdigest(),
            bytes_written=len(result),test_bodies_preserved=True,delivery_approval=False)
    finally:os.close(fd)
