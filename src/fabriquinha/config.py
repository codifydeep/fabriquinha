"""Versioned project configuration; supplied by the controller, never a worker."""
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from .artifacts import digest


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

    @classmethod
    def parse(cls, value):
        required = {'version', 'namespace', 'repository', 'branch', 'validation_image',
                    'tests_dir', 'reviewers', 'qualification'}
        if (not isinstance(value, dict) or not required <= set(value)
                or set(value) - required - {'max_workers', 'timeout_seconds', 'browser_image', 'technical_roles', 'coordination_roles', 'delivery_roles', 'local_ci'}
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
        return cls(**fields, reviewers=MappingProxyType(matrix), max_workers=workers,
                   timeout_seconds=timeout,browser_image=browser,
                   technical_roles=MappingProxyType(dict(roles)) if roles else None,
                   coordination_roles=MappingProxyType(dict(coordination)) if coordination else None,
                   delivery_roles=MappingProxyType(dict(delivery)) if delivery else None,
                   local_ci=MappingProxyType(dict(ci)) if ci else None)

    def fingerprint(self):
        return digest({name: dict(value) if name in ('reviewers','technical_roles','coordination_roles','delivery_roles','local_ci') and value is not None else value
                       for name in self.__dataclass_fields__ for value in (getattr(self, name),)
                       if name not in ('browser_image','technical_roles','coordination_roles','delivery_roles','local_ci') or value is not None})

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


def execution_context(project):
    """Bounded public constraints, not credentials or a grant to change policy."""
    return dict(stack='python-http',repository=project.repository,branch=project.branch,
        workers=project.max_workers,tests_dir=project.tests_dir,iterations=40,
        reviewers={role:list(project.reviewers_for(role)) for role in project.reviewers},
        coordination_roles=dict(project.coordination_roles or {}),delivery_roles=dict(project.delivery_roles or {}),
        deployment='Local Docker only; container HTTP port 8080, dynamic host port and URL supplied by controller; GET /health and /identity; immutable reviewed image.',
        http_contract=dict(entrypoint=['python','-B','/app/app.py','8080'],
            health=dict(path='/health',status=200,json={'status':'ok'}),
            identity=dict(path='/identity',status=200,json_fields=['source_sha'],
                source_sha='Exact runtime value of FABRIQUINHA_SOURCE_SHA environment variable; do not hardcode a commit.'),
            assets='Same-origin HTTP only; no CDN/downloads or WebSockets in this qualified stack.'),
        quality='Red -> independent test freeze -> Green -> mutations -> independent delivery review -> integrated suite -> deployed browser QA.',
        browser_checks=dict(maximum=20,required_count='Not a target of 20. Use proportionate scenarios covering the approved criterion IDs.'),
        network='No network, downloads, infrastructure credentials or Docker socket in product sandboxes.')
