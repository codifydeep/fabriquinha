"""Versioned project configuration; supplied by the controller, never a worker."""
from dataclasses import dataclass
from pathlib import PurePosixPath
import ipaddress
import re
from types import MappingProxyType
from .artifacts import digest


def pool_subnets(pool):
    if pool is None:return {}
    if not isinstance(pool,str):raise ValueError('private aligned IPv4 /26 pool required')
    try:network=ipaddress.IPv4Network(pool,strict=True)
    except (ValueError,TypeError):raise ValueError('private aligned IPv4 /26 pool required') from None
    if network.prefixlen!=26 or not any(network.subnet_of(ipaddress.IPv4Network(cidr))
            for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        raise ValueError('private aligned IPv4 /26 pool required')
    return {name:str(subnet) for name,subnet in zip(('default','qa','core'),network.subnets(new_prefix=28))}


@dataclass(frozen=True)
class Project:
    namespace: str
    repository: str
    branch: str
    validation_image: str
    tests_dir: str
    reviewers: dict
    qualification: bool
    max_workers: int = 2
    timeout_seconds: int = 120
    browser_image: str | None = None
    technical_roles: dict | None = None
    coordination_roles: dict | None = None
    delivery_roles: dict | None = None
    local_ci: dict | None = None
    browser_tdd: bool | None = None
    network_pool: str | None = None

    @classmethod
    def parse(cls, value):
        required = {'version', 'namespace', 'repository', 'branch', 'validation_image',
                    'tests_dir', 'reviewers', 'qualification'}
        if (not isinstance(value, dict) or not required <= set(value)
                or set(value) - required - {'max_workers', 'timeout_seconds', 'browser_image', 'technical_roles', 'coordination_roles', 'delivery_roles', 'local_ci', 'browser_tdd','network_pool'}
                or type(value['version']) is not int or value['version'] != 1):
            raise ValueError('versioned project contract required')
        if (not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}', str(value['namespace']))
                or not re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', str(value['repository']))
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,120}', str(value['branch']))
                or '..' in value['branch'] or type(value['qualification']) is not bool
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', str(value['validation_image']))):
            raise ValueError('exact project, image and qualification identity required')
        path = value['tests_dir']
        if not isinstance(path, str) or str(PurePosixPath(path)) != path or path.startswith('/') or '..' in PurePosixPath(path).parts:
            raise ValueError('relative tests directory required')
        reviewers = value['reviewers']
        if not isinstance(reviewers, dict) or not reviewers:
            raise ValueError('independent role matrix required')
        matrix = {}
        for author, configured in reviewers.items():
            candidates = [configured] if isinstance(configured, str) else configured
            if (not isinstance(author, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', author)
                    or not isinstance(candidates, list) or not 1 <= len(candidates) <= 9
                    or any(not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', name)
                           for name in candidates)
                    or len(set(candidates)) != len(candidates) or author in candidates):
                raise ValueError('independent role matrix required')
            # Preserve existing single-reviewer fingerprints. Copy ordered pools
            # so mutation of a parsed config cannot change review authority.
            matrix[author] = configured if isinstance(configured, str) else tuple(candidates)
        workers, timeout = value.get('max_workers', 2), value.get('timeout_seconds', 120)
        if type(workers) is not int or not 1 <= workers <= 2 or type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError('bounded execution required')
        fields = {k: value[k] for k in required - {'version', 'reviewers'}}
        browser=value.get('browser_image')
        if browser is not None and not re.fullmatch(r'sha256:[a-f0-9]{64}',str(browser)):
            raise ValueError('exact browser toolchain image required')
        roles=value.get('technical_roles')
        if roles is not None and (not isinstance(roles,dict) or set(roles)!={'lead','cto'}
                or any(not isinstance(role,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}',role) for role in roles.values())
                or roles['lead']==roles['cto']):
            raise ValueError('independent technical lead and CTO roles required')
        coordination=value.get('coordination_roles')
        if coordination is not None and (not isinstance(coordination,dict) or set(coordination)!={'product','lead'}
                or any(not isinstance(role,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}',role) for role in coordination.values())
                or coordination['product']==coordination['lead'] or coordination['lead'] not in matrix
                or roles is not None and coordination['lead']!=roles['lead']):
            raise ValueError('product and independently reviewed technical lead required')
        delivery=value.get('delivery_roles')
        if delivery is not None and (not coordination or not browser or not isinstance(delivery,dict)
                or set(delivery)!={'tests','integration'} or delivery['tests']==delivery['integration']
                or any(not isinstance(role,str) or role not in matrix for role in delivery.values())):
            raise ValueError('explicit reviewed tests/integration roles, coordination and browser required')
        ci=value.get('local_ci')
        if ci is not None and (not isinstance(ci,dict) or set(ci)!={'context','publisher'}
                or ci['context']!='fabriquinha-local-ci' or value['branch'] in ('main','master')
                or not isinstance(ci['publisher'],str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',ci['publisher'])):
            raise ValueError('fixed local CI context, publisher and non-primary branch required')
        browser_tdd=value.get('browser_tdd')
        if browser_tdd is not None and type(browser_tdd) is not bool:
            raise ValueError('explicit qualified browser TDD capability required')
        pool=value.get('network_pool');pool_subnets(pool)
        return cls(**fields, reviewers=MappingProxyType(matrix), max_workers=workers,
                   timeout_seconds=timeout,browser_image=browser,
                   technical_roles=MappingProxyType(dict(roles)) if roles else None,
                   coordination_roles=MappingProxyType(dict(coordination)) if coordination else None,
                   delivery_roles=MappingProxyType(dict(delivery)) if delivery else None,
                   local_ci=MappingProxyType(dict(ci)) if ci else None,browser_tdd=browser_tdd,network_pool=pool)

    def fingerprint(self):
        return digest({name: dict(value) if name in ('reviewers','technical_roles','coordination_roles','delivery_roles','local_ci') and value is not None else value
                       for name in self.__dataclass_fields__ for value in (getattr(self, name),)
                       if name not in ('browser_image','technical_roles','coordination_roles','delivery_roles','local_ci','browser_tdd','network_pool') or value is not None})

    def reviewers_for(self, author):
        try:
            configured = self.reviewers[author]
        except KeyError:
            raise ValueError('author outside configured review matrix') from None
        return (configured,) if isinstance(configured, str) else configured

    def reviewer(self, author, *, exclude=()):
        for candidate in self.reviewers_for(author):
            if candidate not in exclude:
                return candidate
        raise ValueError('no independent reviewer available in approved matrix')


def execution_context(project,*,browser_mode=1):
    """Bounded public constraints, not credentials or a grant to change policy."""
    result=dict(stack='python-http',repository=project.repository,branch=project.branch,
        workers=project.max_workers,tests_dir=project.tests_dir,iterations=40,
        reviewers={role:list(project.reviewers_for(role)) for role in project.reviewers},
        review_contract=('The reviewers mapping lists eligible alternative reviewers, not cumulative sign-offs. '
            'The controller selects one independent reviewer for each handoff. '
            'Plan review, test freeze, implementation review and deployed QA are distinct gates. '
            'Describe only the installed gates; do not promise additional frontend/backend/CTO signatures '
            'that are not represented by the workflow. Technical consultation does not create another approval gate.'),
        coordination_roles=dict(project.coordination_roles or {}),delivery_roles=dict(project.delivery_roles or {}),
        test_tooling=dict(command='python -B /opt/fabriquinha/suite.py',browser_tdd=bool(project.browser_tdd),
            available=['unittest','playwright.sync_api','Chromium'] if project.browser_tdd else ['unittest'],
            runtime='The shipped application remains Python stdlib only; browser libraries belong in tests, never product imports.',
            contract=('Browser behaviors must be exercised in tests, not inferred from HTML/JS token strings. '
                'Tests may start their own temporary local HTTP app and Chromium; register cleanup for both. '
                'Use assertions/expectations before interacting with missing elements so Red fails by assertion, not a selector timeout. '
                'Browser tests use the same immutable, no-network suite job as unit tests.' if project.browser_tdd else
                'No JavaScript engine or browser is provided for Red/Green in this image; post-deploy browser QA is separate.')),
        build_contract='Controller supplies the trusted build recipe, CI and deployment; do not add product Dockerfiles or workflows to duplicate them.',
        deployment='Local Docker only; container HTTP port 8080, dynamic host port and URL supplied by controller; GET /health and /identity; immutable reviewed image.',
        rollback='First-ever release uses a validated bootstrap. A subsequent release uses its exact last homologated same-project artifact, matching the new release seed. Later packages use immediate independent parent QA. Preserve any unmatched current deployment; never delete it to bypass a mismatch.',
        http_contract=dict(entrypoint=['python','-B','/app/app.py','8080'],
            health=dict(path='/health',status=200,json={'status':'ok'}),
            identity=dict(path='/identity',status=200,json_fields=['source_sha'],
                source_sha='Exact runtime value of FABRIQUINHA_SOURCE_SHA environment variable; do not hardcode a commit.'),
            assets='Same-origin HTTP only; no CDN/downloads or WebSockets in this qualified stack.'),
        quality='Red -> independent test freeze -> Green -> mutations -> independent delivery review -> integrated suite -> deployed browser QA.',
        browser_checks=dict(maximum=20,required_count='Not a target of 20. Use proportionate scenarios covering the approved criterion IDs.'),
        frozen_qa_preview=('The exact frozen browser contract also runs after the full suite in Green, delivery review and integrated CI. '
            'text is the exact normalized full locator text, never a substring. Unit Green alone cannot satisfy this check. '
            'It does not replace post-deploy QA or historical Red.' if project.browser_tdd and project.delivery_roles else None),
        network='No network, downloads, infrastructure credentials or Docker socket in product sandboxes.')
    if browser_mode==2:
        from .browser import author_protocol
        result['browser_protocol']=author_protocol(2)
        result['test_tooling']['contract']='Unit/integration tests use test*.py; shared acceptance uses acceptance_*.py and self.target supplied by the fixed runner. All inventories run in every TDD phase. Use real browser assertions and independently reviewed criterion coverage.'
        result['frozen_qa_preview']='The same frozen Python acceptance inventory runs in the full suite and on the deployed SHA. Multiple isolated sessions and explicit timing assertions are available.'
        result['test_authority']='The installed owner-approved F3 quality contract supersedes older brief boilerplate requiring CEO approval for every technical correction; the brief still governs business scope. Lead and independent reviewer classify technical corrections; CTO resolves ambiguity. CEO decides scope changes or coverage removal. Existing frozen tests stay immutable; unsupported technical repair remains a visible CTO impediment, never an implicit waiver.'
    return result
