"""Deterministic effective-policy manifest; excludes secrets and mutable state."""
import hashlib,json
from pathlib import Path
from product_policy import VERSION,MODEL,ROLES,CAPABILITIES,review_error
from product_workspace import digest

def manifest():
    root=Path(__file__).parent
    names=['product_policy.py','product_boundary.py','product_claim.py','product_tdd.py','product_team.py','product_memory.py','product_test_maintenance.py','product_review_policy.py']
    modules={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names}
    from product_skills import root,catalog
    skills={n:hashlib.sha256((root()/n/'SKILL.md').read_bytes()).hexdigest() for n in set(s for names in catalog()['profiles'].values() for s in names)}
    return dict(version=VERSION,model=MODEL,fallback=False,max_turns=40,max_workers=2,max_per_profile=1,skills=skills,skill_assignment=catalog()['profiles'],
        roles=ROLES,capabilities=CAPABILITIES,modules=modules,authority='controller_registration_not_agent_text')

def verify(config):
    expected=config.get('runtime_manifest_sha256')
    if expected and expected!=digest(manifest()):raise PermissionError('effective runtime policy drift; maintenance migration required')
    for card in config['cards'].values():
        if card.get('policy_version'):
            error=review_error(card['author'],card['reviewer'],card)
            if error:raise PermissionError(error)
    return dict(verified=bool(expected),sha256=digest(manifest()))

def profile_check(root,profile):
    import yaml
    config=yaml.safe_load((Path(root)/'profiles'/profile/'config.yaml').read_text())
    if config.get('model')!=MODEL or config.get('fallback_providers')!=[] or config.get('agent',{}).get('max_turns')!=40:
        raise PermissionError('profile model, fallback or execution-budget drift')
    return True
