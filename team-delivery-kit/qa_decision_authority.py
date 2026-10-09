"""Role authority for diagnosis proposals, not product execution permissions."""
import re

VERSION = 2
CONTRACT = (
    ' QA_DECISION_AUTHORITY_V2: A repair decision is a scoped PROPOSAL, not '
    'an executed fix or a delivery approval. You are the CTO and already own '
    'the technical decision within the listed editable paths and existing '
    'test roots. Do not wait for permission from the CTO (your own role). '
    'Use the controller-executed failed QA and actual read-only code evidence '
    'to propose a repair with one new regression test and acceptance criteria. '
    'You are not required or allowed to edit the code or rerun the failure in '
    'this diagnosis. The implementation agent will execute Red-Green-Refactor; '
    'independent review, CI and browser QA will verify the fix. Do not claim '
    'those future actions occurred. Use blocked only for a concrete unresolved '
    'dependency outside your authority, missing evidence, scenario or '
    'infrastructure defect, or an out-of-scope change. Never infer permission '
    'to change tests, broaden scope, bypass a gate or approve a release.'
)


def self_referral(decision):
    """Narrow protocol-error detector. It grants only a clarified diagnosis."""
    if (not isinstance(decision, dict) or decision.get('decision') != 'blocked'
            or decision.get('editable_code_files') != []
            or decision.get('new_test_file') != '' or decision.get('acceptance') != []):
        return False
    cause = decision.get('root_cause')
    return isinstance(cause, str) and bool(re.search(
        r'\b(?:pending|awaiting|waiting for|requires?)\s+CTO\s+(?:authorization|approval)\b',
        cause, re.IGNORECASE))
