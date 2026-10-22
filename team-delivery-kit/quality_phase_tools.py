"""Handler-bound tests-only phase, supplied solely by controller transport."""
import json
from pathlib import PurePosixPath
import uuid

KEY='DELIVERY_QUALITY_PHASE_JSON'
CONFLICTS=('DELIVERY_AUTHOR_FEEDBACK_JSON','DELIVERY_ADDITIVE_TEST_JSON',
    'DELIVERY_SURGICAL_TEST_JSON','DELIVERY_REVIEW_SUITE_CAPABILITY')


def validate(config,execution):
    if (not isinstance(config,dict) or set(config)!={'version','phase','request_id','editable_paths','read_paths'}
            or type(config['version']) is not int or config['version']!=2 or config['phase']!='tests_only_v2'
            or not isinstance(execution,str) or str(uuid.UUID(execution))!=execution
            or config['request_id']!=execution):raise ValueError('exact tests-only execution contract required')
    for key in ('editable_paths','read_paths'):
        paths=config[key]
        if (not isinstance(paths,list) or not 1<=len(paths)<=256 or len(set(paths))!=len(paths)
                or any(not isinstance(p,str) or not 1<=len(p)<=300 or not p.startswith('/workspace/')
                    or str(PurePosixPath(p))!=p or '..' in PurePosixPath(p).parts for p in paths)):
            raise ValueError('exact tests-only path inventory required')
    if not set(config['editable_paths'])<=set(config['read_paths']):raise ValueError('editable files must be readable')
    return config


def controlled(name,args,environment):
    """None permits the already-fenced original handler; every other tool denies."""
    def deny():return json.dumps(dict(error='operation_forbidden_in_tests_only_v2',delivery_approval=False))
    try:
        config=validate(json.loads(environment[KEY]),environment.get('DELIVERY_MODEL_EXECUTION_ID'))
        if environment.get('DELIVERY_EXECUTION_MODE')!='implementation' or any(k in environment for k in CONFLICTS):
            return deny()
        if not isinstance(args,dict):return deny()
        path=args.get('path')
        if name=='read_file' and path in config['read_paths'] and not set(args)-{'path','offset','limit'}:
            if any(type(args[k]) is not int or not 1<=args[k]<=65536 for k in ('offset','limit') if k in args):return deny()
            return None
        if name=='write_file' and set(args)=={'path','content'} and path in config['editable_paths']:
            content=args['content']
            if isinstance(content,str) and 0<len(content.encode())<=32768:return None
        return deny()
    except (ValueError,TypeError,KeyError,UnicodeError):return deny()
