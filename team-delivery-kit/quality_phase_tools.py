"""Handler-bound v2 quality phases, supplied solely by controller transport."""
import json
from pathlib import PurePosixPath
import uuid
from portable_contract import MAX_FILE_BYTES

KEY='DELIVERY_QUALITY_PHASE_JSON'
CONFLICTS=('DELIVERY_AUTHOR_FEEDBACK_JSON','DELIVERY_ADDITIVE_TEST_JSON',
    'DELIVERY_SURGICAL_TEST_JSON','DELIVERY_REVIEW_SUITE_CAPABILITY')
REVIEW_PHASES=('test_review_v2','delivery_review_v2')


def validate(config,execution):
    keys={'version','phase','request_id','editable_paths','read_paths'}
    if (not isinstance(config,dict) or set(config) not in (keys,keys|{'review_context'})
            or type(config['version']) is not int or config['version']!=2
            or config['phase'] not in ('tests_only_v2','implementation_v2')+REVIEW_PHASES
            or not isinstance(execution,str) or str(uuid.UUID(execution))!=execution
            or config['request_id']!=execution):raise ValueError('exact tests-only execution contract required')
    reviewing=config['phase'] in REVIEW_PHASES
    root='/delivery/' if reviewing else '/workspace/'
    for key in ('editable_paths','read_paths'):
        paths=config[key]
        minimum=0 if reviewing and key=='editable_paths' else 1
        if (not isinstance(paths,list) or not minimum<=len(paths)<=256 or len(set(paths))!=len(paths)
                or any(not isinstance(p,str) or not 1<=len(p)<=300 or not p.startswith(root)
                    or str(PurePosixPath(p))!=p or '..' in PurePosixPath(p).parts for p in paths)):
            raise ValueError('exact tests-only path inventory required')
    if reviewing and config['editable_paths']:
        raise ValueError('test review has no editable files')
    if not set(config['editable_paths'])<=set(config['read_paths']):raise ValueError('editable files must be readable')
    if 'review_context' in config:
        if config['phase']!='test_review_v2':raise ValueError('test-review stop context belongs only to test review')
        from quality_review_stop import validate_context
        validate_context(config['review_context'],config['read_paths'])
    return config


def controlled(name,args,environment,*,handler_entry=False):
    """None permits the already-fenced original handler; every other tool denies."""
    current_phase='quality_phase_v2'
    def deny():return json.dumps(dict(error='operation_forbidden_in_'+current_phase,delivery_approval=False))
    try:
        config=validate(json.loads(environment[KEY]),environment.get('DELIVERY_MODEL_EXECUTION_ID'))
        current_phase=config['phase']
        expected='review' if config['phase'] in REVIEW_PHASES else 'implementation'
        if environment.get('DELIVERY_EXECUTION_MODE')!=expected or any(k in environment for k in CONFLICTS):
            return deny()
        if not isinstance(args,dict):return deny()
        path=args.get('path')
        if name=='read_file' and path in config['read_paths'] and not set(args)-{'path','offset','limit'}:
            if any(type(args[k]) is not int or not 1<=args[k]<=65536 for k in ('offset','limit') if k in args):return deny()
            if config['phase'] in REVIEW_PHASES and (set(args)!={'path','offset','limit'}
                    or not 1<=args['limit']<=100):return deny()
            if config['phase']=='test_review_v2' and 'review_context' in config:
                from quality_review_paging import allowed,rejection
                if not allowed(config,args,consume=handler_entry):return json.dumps(rejection(config))
            return None
        if config['phase'] in ('tests_only_v2','implementation_v2') and name=='write_file' and set(args)=={'path','content'} and path in config['editable_paths']:
            content=args['content']
            maximum=MAX_FILE_BYTES if config['phase']=='implementation_v2' else 32768
            minimum=0 if config['phase']=='implementation_v2' else 1
            if isinstance(content,str) and minimum<=len(content.encode())<=maximum:return None
        return deny()
    except (ValueError,TypeError,KeyError,UnicodeError):return deny()
