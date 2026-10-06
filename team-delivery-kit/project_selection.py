"""Operator-owned repository selection for the fixed calculator evaluation.

This is not an agent-supplied project manifest. It only chooses a checkout and
GitHub repository; the narrow calculator test contract remains fixed.
"""
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
DEFAULT = {'repository': 'codifydeep/descartavel', 'checkout': 'sandbox-github'}


def current():
    selected = os.environ.get('DELIVERY_KIT_PROJECT_CONFIG')
    if selected:
        path = Path(selected)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError('project config must be an absolute regular file')
        config = json.loads(path.read_text())
    else:
        config = DEFAULT.copy()
    if not isinstance(config, dict) or set(config) != {'repository', 'checkout'}:
        raise ValueError('project config fields invalid')
    repository, checkout = config['repository'], config['checkout']
    if not isinstance(repository, str) or not re.fullmatch(
            r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('invalid GitHub repository')
    if not isinstance(checkout, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,63}', checkout):
        raise ValueError('invalid checkout name')
    path = ROOT / checkout
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError('unsafe project checkout')
    return {'repository': repository, 'checkout': path,
            'remote_https': 'https://github.com/' + repository + '.git',
            'remote_ssh': 'git@github.com:' + repository + '.git'}
