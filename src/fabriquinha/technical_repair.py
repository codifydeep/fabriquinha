"""Scoped CTO test-repair decisions. Admission never approves tests or delivery."""
from pathlib import PurePosixPath

PROTOCOL = 'technical-test-repair-1'
STRENGTHEN = 'technical-test-strengthening-1'

def scope_input(scope):
    return {k:scope[k] for k in ('tests','test_paths','cases','mode','product_imports','parent_repair','probe_offer') if k in scope}


def validate_scope(project, store, incident, binding, experiment, scope):
    extended=isinstance(scope,dict) and scope.get('mode')=='strengthen'
    keys={'tests','test_paths','cases'}|({'mode','product_imports'} if extended else set())
    probe=extended and 'probe_offer' in scope
    if probe:keys.add('probe_offer')
    if extended and 'parent_repair' in scope:keys.add('parent_repair')
    if (not isinstance(scope, dict) or set(scope) != keys
            or binding.get('actor') != project.technical_roles.get('cto')
            or binding.get('kind') != 'diagnostic' or binding.get('reviewing') is not False):
        raise ValueError('exact CTO technical repair scope required')
    source = store.receipt(incident, kind='incident')
    data = source['payload']
    coverage=extended and source['binding'].get('kind')=='tests' and source['binding'].get('reviewing') is True
    if (data.get('project') != project.fingerprint()
            or source['binding'].get('release') != binding.get('release')
            or source['binding'].get('kind') not in (('implementation','tests') if extended else ('implementation',))
            or not (source['binding'].get('reviewing') is False or coverage)
            or data.get('source_state') not in ('blocked', 'triage')
            or data.get('controller_effects') != []
            or data.get('source') != source['binding'].get('task')
            or data.get('source_run') != source['binding'].get('number')):
        raise ValueError('settled blocked or triaged implementation incident required')
    if probe and (coverage or source['binding']['kind']!='tests'):raise ValueError('probe requires failed test author')
    parent=None
    if source['binding']['kind']=='tests':
        from .repairs import reviewed
        parent=reviewed(project,store,scope.get('parent_repair'))
        old=parent['context']
        if (old.get('protocol')!=(STRENGTHEN if coverage or probe else PROTOCOL) or old.get('tests')!=scope['tests']
                or parent['proposal'].get('classification')!='test_contract'
                or store.receipt(scope['parent_repair'])['binding']['release']!=binding['release']):
            raise ValueError('exact prior strict repair authority required for strengthening successor')
    elif 'parent_repair' in scope:raise ValueError('parent repair applies only to failed test authors')
    observation = store.receipt(experiment, kind='diagnostic_experiment')
    if (observation['binding'] != binding
            or observation['payload'].get('incident') != incident
            or observation['payload'].get('project') != project.fingerprint()
            or observation['payload'].get('snapshot') != data['snapshot']):
        raise ValueError('exact current CTO experiment required')
    from .quality import Quality
    quality = Quality(project, store, None, None)
    freeze = store.receipt(scope['tests'], kind='tests_frozen')
    frozen = quality.frozen_plan(freeze)
    if freeze['binding'].get('release') != binding['release']:
        raise ValueError('foreign test freeze')
    if coverage:
        escalation=store.receipt(data.get('review_escalation'),kind='review_escalation')
        if escalation['binding']!=source['binding'] or escalation['payload'].get('snapshot')!=data['snapshot']:
            raise ValueError('exact immutable rejected test review required')
        from .test_revision import revision_context
        revision_context(project,store,quality,parent,data['snapshot'],contract=3)
    elif probe:
        from .http_probe import check_offer
        spec=check_offer(store,project,scope['probe_offer'],incident,scope['parent_repair'],scope['tests'])
        offer=store.receipt(scope['probe_offer'],kind='http_probe_offer')['payload']
        trial=store.receipt(offer['qualification'],kind='offline_http_probe_qualification')['payload']
        if (trial['green']!=old['implementation_snapshot'] or scope['cases']!=[spec['case']] or spec['case'] not in old['cases'] or old.get('probe_offer')
                or scope['test_paths']!=[project.tests_dir+'/'+spec['case'].split('.')[0]+'.py']
                or scope['test_paths'][0] not in old['test_paths']):
            raise ValueError('one existing authorized probe case required')
    else:quality.protect(frozen['snapshot'], data['snapshot'], exact_tests=True)
    paths, cases = scope['test_paths'], scope['cases']
    for values in (paths, cases):
        if (not isinstance(values, list) or not 1 <= len(values) <= 20
                or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values)):
            raise ValueError('bounded distinct paths and cases required')
    for path in paths:
        item = PurePosixPath(path)
        if (str(item) != path or item.parent.as_posix() != project.tests_dir
                or not item.name.startswith('acceptance_') or item.suffix != '.py'
                or path not in frozen['tests']):
            raise ValueError('only exact existing acceptance files may be repaired')
    if not set(cases) <= set(frozen['cases']):
        raise ValueError('unknown repair case')
    modules = {PurePosixPath(path).stem for path in paths}
    if {case.split('.')[0] for case in cases} != modules:
        raise ValueError('every scoped file must have an exact scoped case')
    extra={}
    if extended:
        imports=scope['product_imports'];manifest=store.manifest(data['snapshot'])
        if (not isinstance(imports,list) or not 1<=len(imports)<=4 or len(set(imports))!=len(imports)
                or any(not isinstance(m,str) or not m.isidentifier() or m.startswith('_') or m+'.py' not in manifest for m in imports)):
            raise ValueError('explicit existing root product modules required')
        extra=dict(mode='strengthen',product_imports=sorted(imports))
        if parent:
            extra.update(parent_repair=scope['parent_repair'],author_snapshot=data['snapshot'])
        if probe:
            extra.update(probe_offer=scope['probe_offer'],probe_spec=spec)
        if coverage:
            paths=sorted(set(paths)|set(old['test_paths']))
            cases=sorted(set(cases)|set(old['cases']))
            extra['product_imports']=sorted(set(imports)|set(old['product_imports']))
            extra['preserve_snapshot']=data['snapshot']
            if len(paths)>20 or len(cases)>20 or len(extra['product_imports'])>4:
                raise ValueError('cumulative coverage scope exceeds bounded authority')
    return dict(protocol=STRENGTHEN if extended else PROTOCOL,**extra, tests=scope['tests'], test_paths=sorted(paths),
                cases=sorted(cases), snapshot=frozen['snapshot'],
                implementation_snapshot=parent['context']['implementation_snapshot'] if parent else data['snapshot'], red_baseline=frozen['baseline'],
                delivery_approval=False, independent_freeze_required=True)
