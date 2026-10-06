"""Versioned, scope-preserving presentation of controller-generated briefs."""
import hashlib
import json

COMMAND = 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'
START = 'Scope is ONLY the contract-declared files in /workspace. PHASE 1: write only NEW discoverable tests '
END = ('. Use actual HTTP/JS behavior, bounded subprocesses and the baseline harnesses. '
       'No sleeps, skipped tests, invented app logic or swallowed exceptions. '
       'Controller captures Red and independent immutable test review BEFORE implementation. '
       'PHASE 2: edit only the declared product paths; frozen tests NEVER change. '
       'Keep every preexisting test byte-identical. Run exactly: ' + COMMAND + '. '
       'Do not use GitHub, Docker, credentials or administrative operations. '
       'Controller owns publication, required CI and independent deployed/browser QA.')


def compact(description):
    if not isinstance(description, str) or len(description) <= 4000:
        return description, None
    if '\nApproved CEO request: ' not in description or '\nBinding CTO proposal: ' not in description:
        return description, None
    head, marker, rest = description.partition(START)
    if not marker:
        return description, None
    try:
        files, offset = json.JSONDecoder().raw_decode(rest)
    except ValueError:
        return description, None
    tail = rest[offset:]
    if (not isinstance(files, list) or not files or any(not isinstance(p, str) for p in files)
            or tail not in (END, END + '\nDELIVERY_TYPED_TEST_SOURCE_V1\n')):
        return description, None
    policy = ('Contract /workspace paths only. PHASE 1 NEW tests: '
        + json.dumps(files) + '. Real HTTP/JS baseline harnesses; bounded subprocesses. '
        'No sleeps/skips/invented logic/swallowed exceptions. Controller Red/independent '
        'immutable test review before PHASE 2 product edits. Tests frozen; '
        'baseline byte-identical. Run: ' + COMMAND + '. No GitHub/Docker/credentials/admin. '
        'Controller: publication/required CI/independent deployed/browser QA.')
    result = head + policy + tail[len(END):]
    proof = {'operation': 'generated_policy_presentation_v1',
             'original_sha256': hashlib.sha256(description.encode()).hexdigest(),
             'effective_sha256': hashlib.sha256(result.encode()).hexdigest(),
             'original_characters': len(description), 'effective_characters': len(result),
             'brief_acceptance_cto_unchanged': True, 'delivery_approval': False}
    return result, proof
