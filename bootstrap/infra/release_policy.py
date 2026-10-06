"""Fail-closed release evidence validation; no LLM verdicts or inferred success."""
import json
import re
from pathlib import Path

REGISTRY = Path('/opt/data/governance/active-release.json')
SHA = re.compile(r'^[0-9a-f]{40}$')

def active_release():
    data = json.loads(REGISTRY.read_text())
    if data.get('state') in {'CANCELADA_PELO_CEO', 'HOMOLOGADA', 'ESTABILIZACAO'}:
        raise ValueError('release is not executable')
    if not re.fullmatch(r'release/v\d+\.\d+(?:\.\d+)?', data.get('branch', '')):
        raise ValueError('invalid release branch in registry')
    if not data.get('controller') or not data.get('repo'):
        raise ValueError('release registry missing controller/repo')
    return data

def validate_report(report, tasks, baseline=None):
    """Structural gate plus persisted card states. External proofs checked separately."""
    if report.get('state') != 'HOMOLOGADA':
        raise ValueError('release state must be HOMOLOGADA')
    commit = report.get('commit', '')
    if not SHA.fullmatch(commit):
        raise ValueError('immutable 40-character commit required')
    if report.get('deployed_commit') != commit:
        raise ValueError('deployed commit differs from release commit')
    if not report.get('brief_approval', {}).get('evidence'):
        raise ValueError('explicit brief approval evidence required')
    criteria = report.get('acceptance', [])
    if not criteria or any(not c.get('criterion') or not c.get('cards') for c in criteria):
        raise ValueError('acceptance-to-card coverage required')
    if baseline is not None:
        if not baseline.get('attempt') or report.get('attempt') != baseline['attempt']:
            raise ValueError('report belongs to another execution attempt')
        expected = baseline.get('approved_criteria', [])
        supplied = [c.get('criterion') for c in criteria]
        if not expected or len(set(supplied)) != len(supplied) or set(supplied) != set(expected):
            raise ValueError('report must cover exactly the approved acceptance baseline')
        if not baseline.get('brief_sha256') or report['brief_approval'].get('sha256') != baseline['brief_sha256']:
            raise ValueError('brief approval differs from immutable baseline')
        if report.get('platforms') != baseline.get('platforms'):
            raise ValueError('report platforms differ from approved scope')
    required = {card for c in criteria for card in c['cards']}
    if any(tasks.get(card) != 'done' for card in required):
        raise ValueError('required acceptance cards not completed')
    for key, owner in [('qa', 'quality_security'), ('deployment', 'devops')]:
        item = report.get(key, {})
        if item.get('profile') != owner or item.get('commit') != commit or not item.get('evidence'):
            raise ValueError(f'{key} evidence with correct profile and commit required')
        if tasks.get(item.get('card')) != 'done':
            raise ValueError(f'{key} card must be completed')
    if not report.get('url') or not report.get('rollback'):
        raise ValueError('URL and rollback procedure required')
    if report.get('platforms') != ['web'] and not report.get('mobile_artifacts'):
        raise ValueError('mobile artifacts required for mobile scope')
    if 'limitations' not in report:
        raise ValueError('limitations must be explicit, even if empty')
    return True
