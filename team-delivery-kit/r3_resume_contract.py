"""Fixed conditional-recovery policy; no delivery approval or execution grant."""
import hashlib

POLICY = ('Initial missing-handle and unverified-delivery facts describe the held episode, not a ban on recovery. '
    'After distinct probes pass, assess propose_resume with experiment=none; exhausting probes is not itself a blocker. '
    'Resume requires independent approve_resume and fresh controller verification of immutable approval, snapshot, '
    'same inputs, idle capacity and absent process before one journalled launch. Normal CI/deploy/QA gates still apply. '
    'Retain hold only with a concrete remaining safety or evidence gap; no execution authority is granted here.')

def sha():return hashlib.sha256(POLICY.encode()).hexdigest()
