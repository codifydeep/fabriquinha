"""Validate portable team configuration. Does not dispatch work or enforce runtime policy."""
import json
from pathlib import Path
import re
import sys

QUALITY = {
    'tdd_required', 'immutable_review', 'independent_review',
    'protect_existing_tests', 'same_commit_deploy_qa',
    'instrumentation_assessment_required',
}
ROLE_FIELDS = {'enabled', 'responsibilities', 'reviewer', 'escalates_to'}


def validate(config):
    errors = []
    if not isinstance(config, dict):
        return ['configuration must be an object']

    def fields(obj, expected, label):
        if not isinstance(obj, dict) or set(obj) != expected:
            errors.append(f'{label}: missing or unknown fields')
            return False
        return True

    fields(config, {'schema_version', 'template_only', 'project', 'execution', 'quality', 'roles'}, 'root')
    if type(config.get('schema_version')) is not int or config['schema_version'] != 1:
        errors.append('unsupported schema_version')
    if type(config.get('template_only')) is not bool:
        errors.append('template_only must be boolean')
    project = config.get('project')
    if fields(project, {'repository', 'release_branch', 'test_commands'}, 'project'):
        if not isinstance(project['repository'], str) or not re.fullmatch(
            r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', project['repository']
        ):
            errors.append('repository must be a credential-free GitHub HTTPS URL')
        if not config.get('template_only') and project['repository'] == 'https://github.com/OWNER/REPOSITORY':
            errors.append('select a real sandbox repository before activation')
        if not isinstance(project['release_branch'], str) or not re.fullmatch(
            r'release/[A-Za-z0-9][A-Za-z0-9._/-]*', project['release_branch']
        ) or '..' in project['release_branch']:
            errors.append('invalid release branch')
        commands = project['test_commands']
        if not isinstance(commands, list) or not commands or any(
            not isinstance(cmd, list) or not cmd or any(
                not isinstance(arg, str) or not arg.strip() for arg in cmd
            ) for cmd in commands
        ):
            errors.append('test commands must be nonempty argv arrays, not shell strings')
    execution = config.get('execution')
    if fields(execution, {'max_workers', 'max_per_role', 'paid_fallback'}, 'execution'):
        if type(execution['max_workers']) is not int or not 1 <= execution['max_workers'] <= 2:
            errors.append('evaluation permits one or two workers')
        if type(execution['max_per_role']) is not int or execution['max_per_role'] != 1:
            errors.append('one run per role is required')
        if execution['paid_fallback'] is not False:
            errors.append('automatic paid fallback is prohibited')
    quality = config.get('quality')
    if fields(quality, QUALITY, 'quality') and any(value is not True for value in quality.values()):
        errors.append('quality invariants cannot be disabled')
    roles = config.get('roles')
    if not isinstance(roles, dict) or not roles:
        return errors + ['roles must be a nonempty mapping']
    for name, role in roles.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            errors.append('invalid role identifier')
        if not fields(role, ROLE_FIELDS, f'role {name}'):
            continue
        if type(role['enabled']) is not bool:
            errors.append(f'{name}: enabled must be boolean')
        if not isinstance(role['responsibilities'], list) or not role['responsibilities'] or any(
            not isinstance(item, str) or not item.strip() for item in role['responsibilities']
        ):
            errors.append(f'{name}: responsibilities required')
        reviewer = role['reviewer']
        reviewer_role = roles.get(reviewer) if isinstance(reviewer, str) else None
        if reviewer == name or not isinstance(reviewer_role, dict) or reviewer_role.get('enabled') is not True:
            errors.append(f'{name}: reviewer must be another enabled role')
        target = role['escalates_to']
        if not isinstance(target, str) or target == name or target not in set(roles) | {'ceo', 'technical_incident'}:
            errors.append(f'{name}: invalid escalation target')
        elif target in roles and (not isinstance(roles[target], dict) or roles[target].get('enabled') is not True):
            errors.append(f'{name}: escalation target disabled')
    return errors


if __name__ == '__main__':
    result = validate(json.loads(Path(sys.argv[1]).read_text()))
    print(json.dumps({'valid': not result, 'errors': result}, indent=2))
    raise SystemExit(bool(result))
