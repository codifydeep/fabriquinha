"""Handler-bound review policy: no general code execution or tool bypass."""
import json
import os
from pathlib import PurePosixPath
import urllib.request
from test_runner_policy import validate_workspace_command
try:import review_read_gate
except ImportError:from broker import review_read_gate

SURGICAL_READ_PAGES={}
ADDITIVE_READ_PAGES={}


def observe_surgical_read(name,args,result):
    additive=os.environ.get('DELIVERY_ADDITIVE_TEST_JSON')
    if additive and name=='read_file' and isinstance(args,dict):
        try:
            config=json.loads(additive);value=json.loads(result);path=args.get('path')
            total=value['total_lines'];offset=args.get('offset',1);limit=args.get('limit',200)
            if path in config['sources'] and not value.get('error') and type(total) is int and total>0 and type(offset) is int and type(limit) is int:
                ADDITIVE_READ_PAGES.setdefault(path,set()).update(range(offset,min(total+1,offset+limit)))
        except (ValueError,KeyError,TypeError):pass
    raw=os.environ.get('DELIVERY_SURGICAL_TEST_JSON')
    if not raw or name!='read_file' or not isinstance(args,dict):return
    config=json.loads(raw)
    if args.get('path')!=config['path']:return
    try:
        value=json.loads(result)
        if value.get('error') or value.get('success') is False or not isinstance(value.get('content'),str):return
        total=value['total_lines'];offset=args.get('offset',1);limit=args.get('limit',200)
        if type(total) is not int or type(offset) is not int or type(limit) is not int or total<1 or offset<1 or limit<1:return
        pages=SURGICAL_READ_PAGES.setdefault(config['path'],set())
        pages.update(range(offset,min(total+1,offset+limit)))
    except (ValueError,TypeError,KeyError):return


def controlled(name, args):
    """None delegates to the original handler; all other results are terminal."""
    mode = os.environ.get('DELIVERY_EXECUTION_MODE')
    additive=os.environ.get('DELIVERY_ADDITIVE_TEST_JSON')
    if mode=='implementation' and additive:
        try:
            config=json.loads(additive)
            if name=='read_file' and isinstance(args,dict) and args.get('path') in set(config['sources'])|{config['path']}:return None
            if name!='write_file':raise ValueError('only reads and one new test write permitted')
            from additive_test_policy import write
            return json.dumps(write(config,args,ADDITIVE_READ_PAGES))
        except Exception as error:
            # ACP's write formatter preserves `error`, but drops separate reason fields.
            # Emit only known policy text there, never paths or arbitrary exception text.
            reasons={'only one new test file permitted','fresh complete approved source reads required',
                'bounded new test required','only existing unittest harness imports allowed',
                'new file must contain imports and a TestCase only','one independent unittest.TestCase required',
                'one exact criterion test required','test signature required','test weakening forbidden',
                'dynamic test replacement forbidden','observable assertion required',
                'only reads and one new test write permitted','new artifact write incomplete'}
            reason=str(error) if type(error) is ValueError and str(error) in reasons else {
                SyntaxError:'python_syntax_invalid',FileExistsError:'target_already_exists',
                PermissionError:'workspace_permission_denied'}.get(type(error),'request_controller_diagnosis')
            return json.dumps({'error':'additive_test_rejected: '+reason,'category':type(error).__name__,
                'reason':reason,'delivery_approval':False})
    surgical=os.environ.get('DELIVERY_SURGICAL_TEST_JSON')
    if mode=='implementation' and surgical:
        try:
            from surgical_test_edit import edit_file,validate_typed
            from pathlib import Path
            config=json.loads(surgical)
            typed=config.get('protocol') in ('typed_v2','typed_driver_v3','typed_driver_lines_v4','typed_template_v5','typed_template_lines_v6')
            expected=({'path','expected_sha256','protocol'} if typed else {'path','expected_sha256'})
            if config.get('atomic_contract'):
                from c10_status_atomic import CONTRACT
                if config.get('protocol')!='typed_driver_lines_v4' or config['atomic_contract']!=CONTRACT:
                    raise ValueError('invalid surgical worker configuration')
                expected=expected|{'atomic_contract'}
            if config.get('drain_resolver'):
                if config.get('atomic_contract') or config.get('protocol')!='typed_driver_lines_v4' or config['drain_resolver'] not in ('resolveNewest','resolveOldest'):
                    raise ValueError('invalid surgical worker configuration')
                expected=expected|{'drain_resolver'}
            if set(config)!=expected:
                raise ValueError('invalid surgical worker configuration')
            if (name=='read_file' and isinstance(args,dict) and isinstance(args.get('path'),str)
                    and args['path'].startswith('/workspace/') and str(PurePosixPath(args['path']))==args['path']
                    and '..' not in PurePosixPath(args['path']).parts):
                return None  # Original read handler and workspace fence still apply.
            if typed:
                if name!='surgical_test_edit':raise ValueError('operation forbidden in surgical mode')
                validate_typed(args,config)
                envelope={k:args[k] for k in ('expected_sha256','edits')}
            else:
                if name!='write_file' or not isinstance(args,dict) or set(args)!={'path','content'} or args['path']!=config['path']:
                    raise ValueError('operation forbidden in surgical mode')
                envelope=json.loads(args['content'])
            if envelope.get('expected_sha256')!=config['expected_sha256']:raise ValueError('surgical grant hash drift')
            total=len(Path(config['path']).read_text().splitlines())
            read=set(range(1,total+1))<=SURGICAL_READ_PAGES.get(config['path'],set())
            return json.dumps(edit_file(args['path'],envelope,observed_read=read,required_uid=0,
                driver_only=config.get('protocol') in ('typed_driver_v3','typed_driver_lines_v4'),
                line_ranges=config.get('protocol') in ('typed_driver_lines_v4','typed_template_lines_v6'),
                template_only=config.get('protocol') in ('typed_template_v5','typed_template_lines_v6'),
                atomic_status=bool(config.get('atomic_contract')),
                micro_resolver=config.get('drain_resolver'),
                rejection_ledger='/tmp/delivery-surgical-rejections.json'))
        except Exception as error:
            from surgical_test_edit import rejection_feedback
            return json.dumps(rejection_feedback(error))
    if mode not in ('review', 'planning'):
        if name=='surgical_test_edit':return json.dumps({'error':'surgical_operation_unavailable'})
        return None
    def deny():
        return json.dumps({'error': 'operation_forbidden_in_' + mode,
                           'tool': name, 'permitted': ['read_file'] +
                           (['terminal:fixed_full_suite_only'] if mode == 'review' else [])})
    if not isinstance(args, dict):
        return deny()
    if name == 'read_file':
        path = args.get('path')
        roots = ('/delivery/',) if mode == 'review' else ('/evidence/candidate/', '/evidence/previous/')
        if (isinstance(path, str) and path.startswith(roots)
                and str(PurePosixPath(path)) == path and '..' not in PurePosixPath(path).parts):
            return review_read_gate.request(args) if mode=='review' else None
        return deny()
    if name != 'terminal' or mode != 'review':
        return deny()
    # Never forward an agent command to the original terminal handler. Match
    # one controller-owned command, then run its prevalidated argv shell-free.
    commands = json.loads(os.environ.get('DELIVERY_TEST_COMMANDS_JSON', '[]'))
    supplied = args.get('command')
    if set(args) - {'command', 'timeout'} or not isinstance(supplied, str):
        return deny()
    matched = [command for command in commands
               if supplied == command.replace('cd /workspace && ', 'cd /delivery && ', 1)]
    if len(matched) != 1:
        return deny()
    validate_workspace_command(matched[0])
    missing=review_read_gate.pending()
    if missing:
        return json.dumps(dict(error='review_reads_incomplete',missing=missing,
            instruction='Complete these actual reads before running the suite or declaring APPROVE.'))
    token = os.environ.get('DELIVERY_REVIEW_SUITE_CAPABILITY', '')
    if len(token) != 64:
        return json.dumps({'error': 'review_suite_capability_missing', 'exit_code': 5})
    # Fixed endpoint + empty body. The agent cannot supply command, image,
    # snapshot, path or credentials. Never run tests inside this model worker.
    request = urllib.request.Request('http://execution-broker:8090/v1/review-suite',
        data=b'{}', headers={'Authorization': 'Bearer ' + token,
                            'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=150) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('review suite response too large')
        result = json.loads(raw)
        if (result.get('executed_by') != 'controller_offline_review_suite'
                or result.get('exit_code') != 0 or result.get('network') != 'none'
                or result.get('snapshot_mount') != 'readonly'):
            raise ValueError('review suite evidence invalid')
        return json.dumps(result)
    except Exception:
        # No credential/error-body disclosure and absolutely no local fallback.
        return json.dumps({'error': 'review_suite_infrastructure_failed', 'exit_code': 5})


def fence(name, handler, is_async=False):
    """Also fence direct calls to a registered handler, not only dispatch."""
    if is_async:
        async def guarded(args, **kwargs):
            result = controlled(name, args)
            if result is not None:return result
            result=await handler(args, **kwargs)
            observe_surgical_read(name,args,result)
            if name=='read_file' and os.environ.get('DELIVERY_EXECUTION_MODE')=='review':
                review_read_gate.observe(args,result)
            return result
    else:
        def guarded(args, **kwargs):
            result = controlled(name, args)
            if result is not None:return result
            result=handler(args, **kwargs)
            observe_surgical_read(name,args,result)
            if name=='read_file' and os.environ.get('DELIVERY_EXECUTION_MODE')=='review':
                review_read_gate.observe(args,result)
            return result
    return guarded
