"""Logical reviewer policy for the single-account, cooperative-agent PoC.

This is not an identity/security boundary against an agent with root/GH access.
"""
REVIEWERS = {
    'produto': 'techlead', 'designer': 'produto', 'cto': 'techlead',
    'techlead': 'cto', 'backend_data': 'techlead', 'frontend': 'techlead',
    'mobile': 'techlead', 'devops': 'quality_security',
    'quality_security': 'techlead',
}

def validate_review(implementer, reviewer):
    expected = REVIEWERS.get(implementer)
    if expected is None:
        return 'unknown implementer; review requires canonical profile provenance'
    if reviewer != expected:
        return f'reviewer for {implementer} must be {expected}, not {reviewer}'
    return None
