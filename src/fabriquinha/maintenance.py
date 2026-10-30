"""Scoped maintenance of a delivered observer; existing native delivery gates apply.

Operator scope authorizes a proposal, not a freeze, merge or delivery. Historical
business approval is reused explicitly only for unchanged delivered behavior.
"""
from pathlib import PurePosixPath
from .artifacts import digest
from .observer_maintenance import PROTOCOL, snapshot_diff


def source(project, store, acceptance, paths):
    record = store.receipt(acceptance, kind='release_acceptance')
    data = record['payload']; scope = record['binding']
    if (data.get('project') != project.fingerprint() or data.get('state') != 'HOMOLOGADA'
            or scope.get('actor') != 'controller' or data.get('qualification') != project.qualification
            or not data.get('packages')):
        raise ValueError('exact accepted source release required')
    final = data['packages'][-1]
    if final['commit'] != data['commit'] or final['qa'] != data['final_qa']:
        raise ValueError('final accepted commit and QA required')
    qa = store.receipt(final['qa'],kind='release_evidence')
    artifact = store.receipt(qa['payload']['artifact'],kind='artifact')
    if (qa['binding']['release'] != scope['release'] or qa['payload']['project'] != project.fingerprint()
            or qa['payload']['commit'] != data['commit'] or artifact['payload']['snapshot'] != final['snapshot']
            or artifact['payload']['project'] != project.fingerprint()):
        raise ValueError('maintenance source must match deployed acceptance')
    from .quality import Quality
    frozen = Quality(project,store,None,None).frozen_plan(store.receipt(final['tests'],kind='tests_frozen'))
    if (not isinstance(paths,list) or not 1 <= len(paths) <= 2
            or any(not isinstance(p,str) for p in paths) or len(set(paths)) != len(paths)):
        raise ValueError('one or two exact observer paths required')
    manifest = store.manifest(final['snapshot'])
    for path in paths:
        item = PurePosixPath(path)
        if (str(item) != path or item.parent.as_posix() != project.tests_dir
                or not item.name.startswith('acceptance_') or item.suffix != '.py'
                or path not in frozen['tests'] or manifest.get(path) != frozen['tests'][path]):
            raise ValueError('exact delivered frozen acceptance paths required')
    business=data['brief']
    for _ in range(32):
        approval=store.receipt(business)
        if approval['kind']=='brief_approval':break
        if approval['kind']!='maintenance_authorization' or approval['payload'].get('project')!=project.fingerprint():
            raise ValueError('preserved business approval required')
        business=approval['payload']['brief']
    else:raise ValueError('bounded business provenance required')
    return dict(protocol=PROTOCOL,acceptance=acceptance,paths=sorted(paths),snapshot=final['snapshot'],
                commit=final['commit'],tests=final['tests'],brief=business,delivery_approval=False)


def authorization(project,store,key):
    record=store.receipt(key,kind='maintenance_authorization');data=record['payload'];scope=record['binding']
    if (set(scope)!={'actor','release','request','task'} or scope['actor']!='operator'
            or data.get('project')!=project.fingerprint() or data.get('business_change') is not False):
        raise ValueError('explicit operator maintenance scope required')
    expected=source(project,store,data['acceptance'],data['paths'])
    original=store.receipt(expected['brief'],kind='brief_approval')
    if scope['task']!=original['binding']['task']:raise ValueError('exact historical brief dependency required')
    if any(data.get(k)!=v for k,v in expected.items()):raise ValueError('maintenance source drift')
    return record


def reviewed(project,store,key):
    review=store.receipt(key,kind='plan_review');scope=review['binding'];data=review['payload']
    plan=store.receipt(data['plan'],kind='work_plan');origin=plan['binding']
    authority=authorization(project,store,plan['payload']['approval'])
    if (scope.get('kind')!='plan' or scope.get('reviewing') is not True
            or scope.get('actor')!=project.technical_roles['cto'] or scope['actor']==origin.get('actor')
            or origin.get('actor')!=project.coordination_roles['lead'] or origin.get('reviewing') is not False or origin.get('kind')!='plan'
            or scope.get('author')!=origin['actor'] or scope.get('task')!=origin.get('task')
            or scope.get('contract')!=origin.get('contract') or scope.get('number',0)<=origin.get('number',0)
            or scope.get('release')!=origin.get('release') or scope['release']!=authority['binding']['release']
            or data.get('project')!=project.fingerprint() or plan['payload'].get('project')!=project.fingerprint()
            or data.get('verdict',{}).get('decision')!='approve' or data['verdict'].get('findings')!=[]
            or len(plan['payload']['document'].get('tasks',[]))!=1):
        raise ValueError('one maintenance package independently approved by CTO required')
    return authority['payload']


def run_authority(project,store,board,run):
    reader=getattr(board,'maintenance_input',None)
    key=reader(run) if reader else None
    if key is None:return None
    facts=reviewed(project,store,key)
    if store.receipt(key)['binding']['release']!=run.release:raise ValueError('foreign maintenance release')
    return key,facts


def validate_revision(project,store,quality,record):
    data=record['payload'];key=data['maintenance'];facts=reviewed(project,store,key)
    scope=record['binding'];old=quality.frozen_plan(store.receipt(facts['tests'],kind='tests_frozen'))
    historical=quality.test_evidence(old['red'])
    if (record['kind']!='test_revision' or scope.get('kind')!='tests' or scope.get('reviewing') is not False
            or scope.get('actor')!=project.delivery_roles['tests'] or scope.get('author')!=scope['actor']
            or scope['release']!=store.receipt(key)['binding']['release']
            or data.get('project')!=project.fingerprint() or data['baseline']!=facts['snapshot']
            or data.get('historical_tests')!=facts['tests'] or data.get('historical_red')!=old['red']
            or data.get('red_job')!=historical['payload']['red_job']
            or data['cases']!=old['cases'] or data['new_cases']!=[] or data['control_cases']!=old['control_cases']):
        raise ValueError('exact current maintenance author, baseline and historical evidence required')
    snapshot_diff(store,data['baseline'],data['snapshot'],facts['paths'],project.tests_dir)
    from .quality import preview_evidence,suite_report
    for name,snapshot,phase in [('baseline_job',data['baseline'],'baseline'),('validation_job',data['snapshot'],'green')]:
        job=store.receipt(data[name],kind='suite_job');value=job['payload'];identity=value['identity']
        if (job['binding']!=scope or identity['binding']!=scope or identity['snapshot']!=snapshot
                or identity['project']!=project.fingerprint() or identity['phase']!=phase
                or identity['image']!=project.validation_image
                or value.get('sandbox')!=dict(network='none',snapshot='readonly',user='65534:65534')):
            raise ValueError('fresh maintenance suite observations required')
        preview_evidence(project,store,value,snapshot,phase);report=suite_report(value)
        if report['failures'] or set(report['cases'])!=set(old['cases']):
            raise ValueError('complete passing original and revised suites required')
    return facts


def observer_failures(store, snapshot, paths, report):
    """Which repaired fixtures actually failed their preserved live-list assertion?"""
    import ast
    from .test_revision import shape
    expected=shape(ast.parse("self.assertEqual(pair['errors'], [])",mode='eval').body)
    lines={}
    for path in paths:
        tree=ast.parse((store.tree(snapshot)/path).read_text())
        lines[path]={node.lineno for node in ast.walk(tree) if isinstance(node,ast.Call) and shape(node)==expected}
    return {frame['file'] for failure in report['failures'] if failure.get('assertion') is True
            for frame in failure.get('frames',[]) if frame.get('file') in lines
            and frame.get('line') in lines[frame['file']] and frame.get('function','').startswith('test')}
