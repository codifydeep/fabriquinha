"""Versioned descriptions of fixed controller operations, not instructions to execute."""
import hashlib
import json

OPERATIONS = {
    'observe_existing_controller': 'Observe processes for the exact persisted publication label. Returns absent, one present, or ambiguous. No live controller handle is required; absence is a valid observation.',
    'verify_frozen_delivery': 'Verify the exact independently approved R2 snapshot and physical manifest hashes. Reads the immutable snapshot using an isolated probe. No running publication controller is required.',
    'verify_github_ci': 'Verify the persisted merged PR and CI at its exact merge SHA. No running publication controller is required. A missing release receipt is reported as unavailable, not success.',
    'verify_local_deployment': 'Verify the persisted Docker deployment ownership, health and source SHA. No running publication controller is required. A missing deployment receipt is unavailable, not success.',
}


def sha():
    return hashlib.sha256(json.dumps(OPERATIONS,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def note():
    return ('\nFixed controller capability catalogue (descriptions, not execution evidence):\n'+
            '\n'.join(name+': '+description for name,description in OPERATIONS.items())+
            '\nA missing controller handle alone does not make these experiments unavailable. '
            'Choose a distinct experiment when facts are missing; do not claim it ran. '
            'A genuinely unsafe or unavailable operation may retain a justified hold. '
            'Every experiment requires independent review and controller verification. '
            'Only observed evidence can support a conditional resume; no approval or restart is granted here.')
