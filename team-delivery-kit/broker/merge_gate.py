"""Offline, fixed-artifact pre-merge guard for the disposable calculator pilot.

The caller must obtain review and CI receipts from trusted controller storage.
Arbitrary JSON supplied by a worker is not authoritative.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess


FILES = ('AGENTS.md', 'calc.py', 'test_calc.py')


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def verify_local_merge_preconditions(repo, proposed_head, source_task_id,
                                     review, ci, snapshot):
    """Fail closed unless the current commit, CI and review name one artifact."""
    repo, snapshot = Path(repo), Path(snapshot)
    if not isinstance(proposed_head, str) or not re.fullmatch(r'[0-9a-f]{40}', proposed_head):
        raise ValueError('invalid proposed commit')
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != proposed_head:
        raise ValueError('PR head moved')
    tracked = set(git(repo, 'ls-tree', '-r', '--name-only', proposed_head).decode().splitlines())
    if tracked != set(FILES):
        raise ValueError('PR commit contains unreviewed files')
    if (review.get('status') != 'approved'
            or review.get('source_task_id') != source_task_id
            or review.get('head_sha') != proposed_head
            or not re.fullmatch(r'[0-9a-f]{64}', review.get('manifest_sha256', ''))):
        raise ValueError('review does not cover current source')
    manifest_bytes = (snapshot / 'manifest.json').read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != review['manifest_sha256']:
        raise ValueError('review manifest changed')
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {'files'} or set(manifest['files']) != set(FILES):
        raise ValueError('unexpected artifact set')
    for name in FILES:
        content = (snapshot / name).read_bytes()
        if (hashlib.sha256(content).hexdigest() != manifest['files'][name]['sha256']
                or len(content) != manifest['files'][name]['bytes']):
            raise ValueError('snapshot hash mismatch')
        if git(repo, 'show', proposed_head + ':' + name) != content:
            raise ValueError('PR commit differs from reviewed snapshot')
    if (ci.get('head_sha') != proposed_head or ci.get('status') != 'success'
            or ci.get('review_manifest_sha256') != review['manifest_sha256']
            or not isinstance(ci.get('tests'), int) or ci['tests'] < 3):
        raise ValueError('CI does not cover current commit and review')
    return {'head_sha': proposed_head, 'source_task_id': source_task_id,
            'review_manifest_sha256': review['manifest_sha256'], 'tests': ci['tests']}
