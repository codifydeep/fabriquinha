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

    @classmethod
    def parse(cls, value):
        required = {'version', 'namespace', 'repository', 'branch', 'validation_image',
                    'tests_dir', 'reviewers', 'qualification'}
        if (not isinstance(value, dict) or not required <= set(value)
                or set(value) - required - {'max_workers', 'timeout_seconds'}
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
        if (not isinstance(reviewers, dict) or not reviewers or
                any(not re.fullmatch('[a-z][a-z0-9_-]{0,63}', str(name)) for name in [*reviewers, *reviewers.values()])
                or any(a == r for a, r in reviewers.items())):
            raise ValueError('independent role matrix required')
        workers, timeout = value.get('max_workers', 2), value.get('timeout_seconds', 120)
        if type(workers) is not int or not 1 <= workers <= 2 or type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError('bounded execution required')
        fields = {k: value[k] for k in required - {'version', 'reviewers'}}
        return cls(**fields, reviewers=MappingProxyType(dict(reviewers)), max_workers=workers, timeout_seconds=timeout)

    def fingerprint(self):
        return digest({name: dict(value) if name == 'reviewers' else value
                       for name in self.__dataclass_fields__ for value in (getattr(self, name),)})

    def reviewer(self, author):
        try:
            return self.reviewers[author]
        except KeyError:
            raise ValueError('author outside configured review matrix') from None
