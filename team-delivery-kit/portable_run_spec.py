"""Operator-owned, repository-neutral intake for one portable delivery run."""
import hashlib
import json
import os
from pathlib import Path
import re

from portable_contract import safe_path


FIELDS = {'label', 'title', 'description', 'review_instruction', 'qa_host_port',
          'container_port', 'dockerfile', 'implementer_registry', 'reviewer_registry'}
OPTIONAL_FIELDS = {'runtime_env', 'browser_qa', 'execution_context'}
LABEL = re.compile(r'[A-Z][A-Z0-9]{1,31}-[1-9][0-9]{0,5}\Z')
REGISTRY = re.compile(r'[a-z][a-z0-9-]{1,63}\.json\Z')
ENV_NAME = re.compile(r'[A-Z][A-Z0-9_]{0,63}\Z')
SECRET_NAME = re.compile(r'(SECRET|TOKEN|PASSWORD|PASSWD|KEY|CREDENTIAL|AUTH)', re.I)


def validate(data, contract):
    if not isinstance(data, dict) or not FIELDS <= set(data) or set(data) - FIELDS - OPTIONAL_FIELDS:
        raise ValueError('invalid portable run spec fields')
    if not isinstance(data['label'], str) or not LABEL.fullmatch(data['label']):
        raise ValueError('invalid portable run label')
    for key in ('title', 'description', 'review_instruction'):
        value = data[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 12000:
            raise ValueError('invalid portable run ' + key)
    if 'execution_context' in data:
        from execution_context import resolve
        for key, mode in [('description', 'implementation'), ('review_instruction', 'review')]:
            resolve(data['execution_context'], data[key], mode)
    for key in ('qa_host_port', 'container_port'):
        value = data[key]
        if type(value) is not int or not 1024 <= value <= 65535:
            raise ValueError('invalid portable run ' + key)
    dockerfile = safe_path(data['dockerfile'])
    if dockerfile not in contract['protected_files']:
        raise ValueError('Dockerfile must be protected by the delivery contract')
    for key in ('implementer_registry', 'reviewer_registry'):
        if not isinstance(data[key], str) or not REGISTRY.fullmatch(data[key]):
            raise ValueError('invalid agent registry filename')
    if data['implementer_registry'] == data['reviewer_registry']:
        raise ValueError('reviewer must be an independent agent')
    runtime_env = data.get('runtime_env', {})
    if (not isinstance(runtime_env, dict) or len(runtime_env) > 8
            or any(not isinstance(name, str) or not ENV_NAME.fullmatch(name)
                   or SECRET_NAME.search(name) or name == 'SOURCE_SHA'
                   or not isinstance(value, str) or not value or len(value) > 256
                   or any(char in value for char in ('\x00', '\n', '\r'))
                   for name, value in runtime_env.items())):
        raise ValueError('runtime env must contain bounded non-secret values')
    if 'browser_qa' in data:
        from portable_browser_qa import validate as validate_browser
        validate_browser(data['browser_qa'])
        if (data['container_port'] != 8080 or
                runtime_env != {'FEEDBACK_DB_PATH': '/tmp/feedback.db'}):
            raise ValueError('feedback browser QA requires an isolated temporary database')
    return data


def load(contract):
    selected = os.environ.get('DELIVERY_KIT_RUN_SPEC')
    if not selected:
        return None
    path = Path(selected)
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
        raise ValueError('run spec must be a bounded absolute regular file')
    spec = validate(json.loads(path.read_text()), contract)
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True,
                                 separators=(',', ':')).encode()).hexdigest()
    return {**spec, 'sha256': digest}
