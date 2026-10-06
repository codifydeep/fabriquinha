"""Versioned operating contract. Agent declarations cannot grant capabilities."""
VERSION='company-process-20260919-v2'
MODEL={'default':'deepseek/deepseek-v4-flash-0731','provider':'openrouter'}
ROLES={
 'produto':'Own user needs, scope, acceptance and research. Never decide technical architecture for the CEO.',
 'designer':'Own interaction, accessibility, design artifacts and visual validation; collaborate with frontend.',
 'cto':'Own cross-cutting architecture, security exceptions and evidenced technical impasses. Not a routine microtask approver.',
 'techlead':'Own delivery flow, dependencies, integration and everyday technical decisions; delegate specialist work.',
 'backend_data':'Implement backend and data contracts with behavioral TDD, concurrency and regression evidence.',
 'frontend':'Implement web behavior, accessibility, rendering and performance with automated tests.',
 'mobile':'Activate only for an approved mobile scope; never manufacture work for a web-only release.',
 'devops':'Own local CI, environments, reliability and team-platform capabilities; use controller operations, never host credentials.',
 'quality_security':'Own test strategy, independent acceptance and security analysis. Separate QA and security findings; never self-review code.',
}
CAPABILITIES={
 'planning':dict(authors=['techlead'],reviewers=['quality_security','cto'],default_reviewer='quality_security',risk='routine',adapter='coordination'),
 'architecture':dict(authors=['cto'],reviewers=['techlead'],default_reviewer='techlead',risk='high',adapter='coordination'),
 'test_maintenance':dict(authors=['quality_security'],reviewers=['techlead'],default_reviewer='techlead',risk='controlled',adapter='coordination'),
 'technical_recovery':dict(authors=['techlead','cto'],reviewers=['cto','techlead'],default_reviewer=None,risk='high',adapter='coordination'),
 'backend':dict(authors=['backend_data'],reviewers=['techlead','quality_security'],default_reviewer='techlead',risk='routine',adapter='lobby-ts'),
 'frontend':dict(authors=['frontend'],reviewers=['techlead','quality_security'],default_reviewer='techlead',risk='routine',adapter='lobby-ts'),
 'quality':dict(authors=['quality_security'],reviewers=['techlead'],default_reviewer='techlead',risk='controlled',adapter='lobby-ts'),
 'design':dict(authors=['designer'],reviewers=['produto','frontend'],default_reviewer='produto',risk='routine',adapter='document'),
 'product':dict(authors=['produto'],reviewers=['quality_security','techlead'],default_reviewer='quality_security',risk='routine',adapter='document'),
 'platform':dict(authors=['devops'],reviewers=['cto','quality_security'],default_reviewer='cto',risk='high',adapter='platform'),
 'deployment':dict(authors=['devops'],reviewers=['quality_security'],default_reviewer='quality_security',risk='controlled',adapter='deployment'),
 'knowledge':dict(authors=list(ROLES),reviewers=['produto','techlead','quality_security'],default_reviewer='techlead',risk='routine',adapter='coordination'),
}

def review_error(author,reviewer,card):
    if card.get('policy_version')!=VERSION:return 'unknown policy version'
    spec=CAPABILITIES.get(card.get('capability'))
    if not spec or card.get('risk')!=spec['risk']:return 'unknown capability or risk drift'
    if author!=card.get('author') or reviewer!=card.get('reviewer'):return 'registered review assignment required'
    if author==reviewer or author not in spec['authors'] or reviewer not in spec['reviewers']:return 'independent qualified reviewer required'
    return None

def context(capability,author=None,reviewer=None):
    spec=CAPABILITIES[capability];author=author or spec['authors'][0]
    reviewer=reviewer or spec['default_reviewer'] or ('cto' if author=='techlead' else 'techlead')
    if reviewer==author:reviewer='quality_security' if author=='techlead' else 'techlead'
    result=dict(policy_version=VERSION,capability=capability,risk=spec['risk'],author=author,reviewer=reviewer)
    return result
