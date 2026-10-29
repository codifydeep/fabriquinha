"""Scoped CTO test-repair decisions. Admission never approves tests or delivery."""
from pathlib import PurePosixPath

PROTOCOL = 'technical-test-repair-1'


def validate_scope(project, store, incident, binding, experiment, scope):
    if (not isinstance(scope, dict) or set(scope) != {'tests', 'test_paths', 'cases'}
            or binding.get('actor') != project.technical_roles.get('cto')
            or binding.get('kind') != 'diagnostic' or binding.get('reviewing') is not False):
        raise ValueError('exact CTO technical repair scope required')
    source = store.receipt(incident, kind='incident')
    data = source['payload']
    if (data.get('project') != project.fingerprint()
            or source['binding'].get('release') != binding.get('release')
            or source['binding'].get('kind') != 'implementation'
            or source['binding'].get('reviewing') is not False
            or data.get('source_state') not in ('blocked', 'triage')
            or data.get('controller_effects') != []
            or data.get('source') != source['binding'].get('task')
            or data.get('source_run') != source['binding'].get('number')):
        raise ValueError('settled blocked or triaged implementation incident required')
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
    quality.protect(frozen['snapshot'], data['snapshot'], exact_tests=True)
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
    return dict(protocol=PROTOCOL, tests=scope['tests'], test_paths=sorted(paths),
                cases=sorted(cases), snapshot=frozen['snapshot'],
                implementation_snapshot=data['snapshot'], red_baseline=frozen['baseline'],
                delivery_approval=False, independent_freeze_required=True)
