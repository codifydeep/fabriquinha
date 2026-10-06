"""Credential-free GitHub availability probe; never emits CLI/token output."""
import subprocess


class WaitingPublicationAccess(Exception):
    pass


def require_access():
    try:
        result = subprocess.run(['gh', 'api', 'user', '--jq', '.login'],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise WaitingPublicationAccess('github_unavailable') from None
    if result.returncode:
        reason = ('github_auth_required' if any(value in result.stderr for value in
            ('HTTP 401', 'HTTP 403', 'gh auth login')) else 'github_unavailable')
        raise WaitingPublicationAccess(reason)
    if not result.stdout.strip():
        raise WaitingPublicationAccess('github_unavailable')

